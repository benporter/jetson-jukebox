#!/usr/bin/env python3
"""
pipeline.py — shared voice pipeline: transcript → intent → Sonos action.

Used by both the fixed-window tester (listen_and_play.py) and the Paw Key
push-to-talk daemon (pawkey_listen.py). Recording + the listening LED live in
those entry points; this module owns transcription and acting on the intent.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
import intent as intent_mod      # noqa: E402
import spotify_resolve           # noqa: E402
import audible_resolve           # noqa: E402
import db                        # noqa: E402
import blocklist                 # noqa: E402
import tts                       # noqa: E402

WHISPER_BIN = REPO / "tools/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = REPO / "tools/whisper.cpp/models/ggml-base.en.bin"
LED = REPO / "setup/respeaker_led.sh"
SONOS_PLAY = REPO / "setup/sonos_play.sh"
QUIET_HOURS = REPO / "setup/within_play_hours.sh"
PLAY_SOUND = REPO / "setup/play_sound.sh"
SONOS_API = os.environ.get("SONOS_API", "http://127.0.0.1:5005")
VOLUME_STEP = int(os.environ.get("JUKEBOX_VOLUME_STEP", "8"))

# Audiobooks are the special case: a spoken keyword routes to Audible (favorites);
# everything else is a Spotify song. Deterministic in code — we don't trust the
# 1.5B model to switch services.
AUDIBLE_KEYWORDS = [k.strip().lower() for k in os.environ.get(
    "JUKEBOX_AUDIBLE_KEYWORDS", "audible,audiobook,book,story").split(",") if k.strip()]
# "continue my book" → resume the active Audible book via its container favorite.
# (The new Sonos app keeps per-book favorites in the cloud, invisible to local
#  FV:2 — see docs/audible.md — so resuming the active book is the local path.)
AUDIBLE_CONTAINER = os.environ.get("JUKEBOX_AUDIBLE_CONTAINER", "Audible.com")
AUDIBLE_RESUME_PHRASES = [p.strip().lower() for p in os.environ.get(
    "JUKEBOX_AUDIBLE_RESUME_PHRASES",
    "continue my book,resume my book,continue my audiobook,continue the book,"
    "keep reading,continue reading,play my book,continue my story,continue book"
).split(",") if p.strip()]

# Easter egg ("No Stairway. Denied!"): a request that resolves to Led Zeppelin's
# Stairway to Heaven plays a LOCAL clip on the Pebble instead of the song on Sonos.
# IDs are the official Led Zeppelin remasters our resolver returns; _is_stairway()
# also title-matches as a safety net. The clip is user-supplied + gitignored (the
# real audio is copyrighted — never committed).
EASTEREGG_SOUND = os.environ.get("JUKEBOX_EASTEREGG_SOUND", "assets/no_stairway.wav")
STAIRWAY_TRACK_IDS = {i.strip() for i in os.environ.get(
    "JUKEBOX_STAIRWAY_IDS",
    "5CQ30WqJwcep0pYcV4AMNc,0RO9W1xJoUEpq5MEelddFb,"
    "12wlYeErSUNGg1B5d64077,3sxIm3lTgdvXJdNHNn64BS").split(",") if i.strip()}

# Spoken on the Pebble (Piper TTS) when a request is refused outside play hours.
QUIET_HOURS_MESSAGE = os.environ.get(
    "JUKEBOX_QUIET_HOURS_MESSAGE", "It's past your bedtime. Go to bed!")
_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}

LEADING_FILLERS = (
    "can you please play", "could you please play", "can you play",
    "could you play", "please play", "i want to hear", "i want to listen to",
    "put on", "play the song", "play me", "play the", "play",
    # STT very often hears "played" / "play the" as one slurred word — treat the
    # "played …" forms as the same leading filler (longer phrases first so the
    # whole-word match below picks them over the bare word).
    "played the song", "played me", "played the", "played",
)


def set_led(mode: str) -> None:
    """Best-effort LED control; never let a mic-light failure break the flow."""
    try:
        subprocess.run([str(LED), mode], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def transcribe(wav: Path) -> str:
    out = subprocess.run(
        [str(WHISPER_BIN), "-m", str(WHISPER_MODEL), "-f", str(wav),
         "-nt", "-l", "en", "--no-prints"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _clean_query(text: str) -> str:
    q = re.sub(r"[\[(][^\])]*[\])]", " ", text)  # drop [BLANK_AUDIO], (music), …
    q = q.strip().lower().strip(".,!?\"' ")
    for filler in LEADING_FILLERS:
        # Match the filler as a whole word, not a prefix — otherwise "play" eats
        # the "play" inside "played" and leaves a garbage stub ("ed the frozen"),
        # which once resolved to a doom-metal album. (STT often hears "played".)
        if q == filler or q.startswith(filler + " "):
            q = q[len(filler):].strip(".,!?\"' ")
            break
    return q.strip()


def _sonos(room: str, path: str) -> None:
    """Fire a node-sonos-http-api GET, e.g. _sonos('Living Room', 'pause')."""
    url = f"{SONOS_API}/{urllib.parse.quote(room)}/{path}"
    with urllib.request.urlopen(url, timeout=15):
        pass


def _quiet_hours_block():
    """Return a reason string if the clock is outside play hours, else None.

    Deterministic clock check delegated to setup/within_play_hours.sh, whose
    contract is: exit 0 = allowed, exit 3 = blocked, any other code = the script
    itself errored. We fail OPEN on an error (return None) so a bug in the gate
    can never lock the jukebox up.
    """
    try:
        r = subprocess.run([str(QUIET_HOURS)], capture_output=True, text=True)
        if r.returncode == 0:
            return None                                  # allowed
        if r.returncode == 3:
            return r.stderr.strip() or "outside play hours"   # blocked
        print(f"(quiet-hours check errored rc={r.returncode}, allowing: "
              f"{r.stderr.strip()})", file=sys.stderr)
        return None                                      # fail open on error
    except Exception as e:
        print(f"(quiet-hours check failed, allowing: {e})", file=sys.stderr)
        return None


def _play_blocked_feedback(reason: str) -> None:
    """Audibly tell the requestor their song was refused.

    Plays JUKEBOX_BLOCKED_SOUND (repo-relative or absolute) to the jukebox audio
    device. Until that clip is recorded/generated (a spoken "sorry, that song
    isn't allowed" — TTS later), this is a no-op that just notes the missing
    config, so the block itself still works. Best-effort: never breaks the flow.
    """
    sound = os.environ.get("JUKEBOX_BLOCKED_SOUND", "").strip()
    if not sound:
        print("(blocked: no JUKEBOX_BLOCKED_SOUND configured — silent for now)",
              file=sys.stderr)
        return
    _play_local_sound(sound)


def _play_local_sound(sound: str) -> bool:
    """Play a WAV through the LOCAL speaker (Pebble, via play_sound.sh) — NOT Sonos.
    Best-effort: returns False (and never raises) if the file is missing/unplayable."""
    sound = (sound or "").strip()
    if not sound:
        return False
    path = sound if os.path.isabs(sound) else str(REPO / sound)
    if not os.path.exists(path):
        print(f"(local sound not found: {path})", file=sys.stderr)
        return False
    try:
        subprocess.run([str(PLAY_SOUND), path], check=False)
        return True
    except Exception as e:
        print(f"(local sound failed: {e})", file=sys.stderr)
        return False


def _is_stairway(track) -> bool:
    """True if the resolved track is Led Zeppelin's Stairway to Heaven (the egg)."""
    if (track.get("id") or "") in STAIRWAY_TRACK_IDS:
        return True
    name = (track.get("name") or "").lower()
    artist = (track.get("artist") or "").lower()
    return "stairway to heaven" in name and "led zeppelin" in artist


def _clean_for_speech(name: str) -> str:
    """Drop trailing version/remaster tags ("Song - 2014 Remaster" -> "Song") so
    the spoken read-back sounds natural."""
    return (name or "").split(" - ")[0].strip()


def _speak_blocked(name: str, artist: str, kind: str = "song",
                   reason: str = "explicit") -> None:
    """Speak the RETRIEVED title + artist on the local Pebble, so the requestor
    hears what was actually found — STT/intent often mishear, and the resolved
    track is frequently not what they meant. Falls back to the static blocked
    sound if Piper TTS isn't installed."""
    title = _clean_for_speech(name) or f"that {kind}"
    by = f" by {artist}" if artist else ""
    if reason == "explicit":
        what = "has explicit lyrics" if kind == "song" else "has explicit songs"
        msg = f"Sorry, {title}{by} {what}, so I can't play it."
    else:
        msg = f"Sorry, {title}{by} isn't allowed."
    wav = tts.speak_to_wav(msg)
    if not (wav and _play_local_sound(wav)):
        _play_blocked_feedback(reason)        # fallback: static "denied" clip


def _speak_quiet_hours() -> None:
    """Speak the bedtime message on the local Pebble (Piper TTS); fall back to the
    static beep if TTS isn't installed."""
    wav = tts.speak_to_wav(QUIET_HOURS_MESSAGE)
    if not (wav and _play_local_sound(wav)):
        _play_blocked_feedback("blocked_time")


def _play_song(transcript, intent, query, room, vol, source, held_seconds) -> int:
    """Resolve a song in Python, LOG the request, then play it. Returns 0 on play.

    Resolving here (not in the shell) lets us record the returned track and its
    explicit flag — and is where the future blocklist / quiet-hours gate will
    decide whether to play at all.
    """
    rec = {
        "source": source, "held_seconds": held_seconds, "transcript": transcript,
        "intent_type": "song", "intent_title": intent.get("title", ""),
        "intent_artist": intent.get("artist", ""), "intent_room": intent.get("room", ""),
        "intent_volume": vol, "intent_json": json.dumps(intent, ensure_ascii=False),
        "spotify_query": query, "room": room, "volume_applied": vol,
        "played": False, "outcome": "no_match",
    }
    # Quiet-hours gate first — deterministic clock check, before we even search,
    # so nothing plays (and no Spotify call is made) outside the allowed window.
    blocked = _quiet_hours_block()
    if blocked:
        rec.update(outcome="blocked_time", block_reason=blocked)
        print(f"\N{LAST QUARTER MOON} quiet hours — {blocked}; not playing")
        _speak_quiet_hours()
        db.log_request(rec)
        return 1

    track = None
    try:
        # Progressive fallback: precise (title+artist) → title-only → loose, so a
        # hallucinated/wrong artist can't blackhole the search. used_query is the
        # query that actually matched (logged for visibility).
        track, used_query = spotify_resolve.resolve_song(
            intent.get("title", ""), intent.get("artist", ""), extra_query=query)
        rec["spotify_query"] = used_query
    except Exception as e:                       # couldn't search (creds/503 storm)
        rec["outcome"] = "play_failed"
        rec["error_message"] = f"resolve: {e}"
        print(f"(spotify resolve failed: {e})", file=sys.stderr)

    if track:
        rec.update({
            "result_track_id": track["id"], "result_track_name": track["name"],
            "result_artist": track["artist"], "result_uri": track["uri"],
            "result_explicit": track["explicit"],
        })
        # Easter egg: "No Stairway. Denied!" — if the search returns Led Zeppelin's
        # Stairway to Heaven, play a LOCAL clip on the Pebble instead of the song on
        # Sonos, and log it (block_reason "Easter egg").
        if _is_stairway(track):
            rec.update(outcome="blocked_easteregg", block_reason="Easter egg")
            print(f"\N{EGG} Easter egg — \"{track['name']} - {track['artist']}\": "
                  f"no Stairway! Denied! (local clip, not Sonos)")
            _play_local_sound(EASTEREGG_SOUND)
            db.log_request(rec)
            return 1
        # Content gate: refuse explicit (and, later, blocklisted) tracks. We log
        # WHAT was blocked (result_* already set) and WHY, play the "not allowed"
        # feedback, and stop — no Sonos call.
        reason = blocklist.check(track)
        if reason:
            rec.update(outcome=blocklist.outcome_for(reason), block_reason=reason)
            print(f"\N{NO ENTRY} blocked ({reason}): "
                  f"\"{track['name']} - {track['artist']}\" — not playing")
            _speak_blocked(track["name"], track["artist"], "song", reason)
            db.log_request(rec)
            return 1
        flag = " [explicit]" if track["explicit"] else ""
        at = f" at volume {vol}" if vol is not None else ""
        print(f"\N{LEFT-POINTING MAGNIFYING GLASS} {used_query!r} → "
              f"\"{track['name']} - {track['artist']}\"{flag} → {room}{at}")
        env = dict(os.environ)
        env["VOLUME"] = str(vol) if vol is not None else ""   # "" = maintain volume
        env["TRACK_ID"] = track["id"]                          # skip a 2nd search
        env["TRACK_LABEL"] = f"{track['name']} - {track['artist']}"
        code = subprocess.run([str(SONOS_PLAY), query, room], env=env).returncode
        if code == 0:
            rec.update(outcome="played", played=True, played_at=datetime.now())
        else:
            rec["outcome"] = "play_failed"
            rec.setdefault("error_message", f"sonos_play exit {code}")
    elif rec["outcome"] != "play_failed":
        print(f"no Spotify match for {rec['spotify_query']!r}", file=sys.stderr)

    db.log_request(rec)
    return 0 if rec["played"] else 1


def _extract_room(text: str, default: str):
    """Pull a spoken room out of `text` (e.g. 'in the kids room'); return
    (room, text_without_the_room_phrase). The audiobook paths are deterministic
    and skip the LLM, so they parse the room here instead of via intent JSON."""
    for r in intent_mod.ROOMS:
        words = re.findall(r"[a-z]+", r.lower())          # "Kids' Room" -> kids,room
        pat = r"(?:\bin\s+the\s+|\bin\s+)?\b" + r"\W*".join(words) + r"\b"
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            rest = (text[:m.start()] + " " + text[m.end():])
            return r, re.sub(r"\s+", " ", rest).strip(" .,")
    return default, text


def _audible_resume_phrase(transcript: str) -> bool:
    """True if the request asks to resume the active audiobook ('continue my book')."""
    t = transcript.lower()
    return any(p in t for p in AUDIBLE_RESUME_PHRASES)


def _resume_audiobook(transcript, room, source, held_seconds) -> int:
    """Path 1: resume the active Audible book by playing its container favorite
    (Audible/Sonos picks up where it left off). No per-book selection — that's the
    cloud-API path (docs/audible.md / docs/sonos-cloud-api.md)."""
    rec = {
        "source": source, "held_seconds": held_seconds, "transcript": transcript,
        "intent_type": "audiobook", "intent_title": "(resume)", "intent_artist": "",
        "intent_room": "", "intent_volume": None, "room": room, "volume_applied": None,
        "spotify_query": "resume", "result_track_name": AUDIBLE_CONTAINER,
        "result_artist": "Audible", "played": False, "outcome": "no_match",
        "intent_json": json.dumps({"type": "audiobook", "service": "audible",
                                   "action": "resume"}),
    }
    blocked = _quiet_hours_block()               # same quiet-hours window as music
    if blocked:
        rec.update(outcome="blocked_time", block_reason=blocked)
        print(f"\N{LAST QUARTER MOON} quiet hours — {blocked}; not resuming")
        _speak_quiet_hours()
        db.log_request(rec)
        return 1
    try:
        _sonos(room, f"favorite/{urllib.parse.quote(AUDIBLE_CONTAINER)}")
        print(f"\N{OPEN BOOK} resuming audiobook ({AUDIBLE_CONTAINER}) in {room}")
        rec.update(outcome="played", played=True, played_at=datetime.now())
    except Exception as e:
        rec.update(outcome="play_failed", error_message=f"resume: {e}")
        print(f"(audiobook resume failed: {e})", file=sys.stderr)
    db.log_request(rec)
    return 0 if rec["played"] else 1


def _audible_keyword(cleaned: str):
    """If the request starts with an Audible keyword, return the remaining text
    (the book/command); else None. Spotify stays the default for everything else."""
    for kw in AUDIBLE_KEYWORDS:
        if cleaned == kw or cleaned.startswith(kw + " "):
            return cleaned[len(kw):].strip()
    return None


def _parse_audible(text: str):
    """Split keyword-stripped text into (book, chapter, nav).

    nav: 'next'/'previous' for chapter navigation with no book; else None.
    chapter: an int if the request named one ("... chapter 3"), else None.
    """
    t = text.strip()
    low = t.lower()
    if low in ("next", "next chapter", "skip", "skip chapter"):
        return "", None, "next"
    if low in ("previous", "previous chapter", "back", "go back", "last chapter"):
        return "", None, "previous"

    chapter = None
    m = re.search(r"\bchapter\s+(\w+)\b", low)
    if m:
        tok = m.group(1)
        chapter = int(tok) if tok.isdigit() else _NUM_WORDS.get(tok)
        t = re.sub(r"\s*\bchapter\s+\w+\b", "", t, flags=re.IGNORECASE).strip()
    return t, chapter, None


def _play_audiobook(transcript, text, room, vol, source, held_seconds) -> int:
    """Play an Audible audiobook from a parent-curated Sonos favorite.

    Audible has no catalog search API, so we fuzzy-match the spoken title against
    the Audible favorites (src/audible_resolve.py) and play by exact title. Best-
    effort chapter selection via next/previous (Audible chapters are queue tracks).
    """
    book, chapter, nav = _parse_audible(text)
    rec = {
        "source": source, "held_seconds": held_seconds, "transcript": transcript,
        "intent_type": "audiobook", "intent_title": book, "intent_artist": "",
        "intent_room": "", "intent_volume": vol, "room": room, "volume_applied": vol,
        "spotify_query": book, "result_artist": "Audible",
        "played": False, "outcome": "no_match",
        "intent_json": json.dumps({"type": "audiobook", "service": "audible",
                                   "book": book, "chapter": chapter, "nav": nav}),
    }

    # Chapter navigation only ("audible next chapter") — no book to resolve.
    if nav:
        try:
            _sonos(room, nav)
            print(f"\N{OPEN BOOK} audiobook: {nav} chapter in {room}")
            rec.update(outcome="played", played=True, played_at=datetime.now())
        except Exception as e:
            rec.update(outcome="play_failed", error_message=f"nav: {e}")
            print(f"(audiobook nav failed: {e})", file=sys.stderr)
        db.log_request(rec)
        return 0 if rec["played"] else 1

    # Same quiet-hours window as music (per design decision).
    blocked = _quiet_hours_block()
    if blocked:
        rec.update(outcome="blocked_time", block_reason=blocked)
        print(f"\N{LAST QUARTER MOON} quiet hours — {blocked}; not playing")
        _speak_quiet_hours()
        db.log_request(rec)
        return 1

    try:
        title, candidates = audible_resolve.resolve_audiobook(book)
    except Exception as e:                       # couldn't reach Sonos favorites
        rec.update(outcome="play_failed", error_message=f"audible resolve: {e}")
        print(f"(audible resolve failed: {e})", file=sys.stderr)
        db.log_request(rec)
        return 1

    if not title:
        rec["outcome"] = "no_match"
        print(f"no Audible favorite matched {book!r}. "
              f"Favorite the book in the Sonos app first. "
              f"(shelf: {candidates})", file=sys.stderr)
        db.log_request(rec)
        return 1

    rec["result_track_name"] = title
    ch = f" chapter {chapter}" if chapter else ""
    print(f"\N{OPEN BOOK} audiobook: {book!r} → \"{title}\"{ch} → {room}")
    try:
        if vol is not None:
            _sonos(room, f"volume/{vol}")
        _sonos(room, f"favorite/{urllib.parse.quote(title)}")
        # Best-effort chapter: Audible chapters are queue tracks, so advance.
        if chapter and chapter > 1:
            time.sleep(1.5)                      # let playback settle first
            for _ in range(chapter - 1):
                _sonos(room, "next")
                time.sleep(0.4)
        rec.update(outcome="played", played=True, played_at=datetime.now())
    except Exception as e:
        rec.update(outcome="play_failed", error_message=f"play: {e}")
        print(f"(audiobook play failed: {e})", file=sys.stderr)

    db.log_request(rec)
    return 0 if rec["played"] else 1


_COLLECTION_ARTICLES = {"the", "a", "an", "my", "this", "that", "some"}


def _collection_keyword(cleaned: str):
    """If the request names an 'album' or 'playlist', return (kind, query) with the
    keyword + surrounding articles stripped; else None. Songs are the default, so a
    request without one of these words is never treated as a collection."""
    words = cleaned.split()
    for kind in ("album", "playlist"):
        if kind in words:
            rest = [w for w in words if w != kind]
            while rest and rest[0] in _COLLECTION_ARTICLES:
                rest.pop(0)
            while rest and rest[-1] in _COLLECTION_ARTICLES:
                rest.pop()
            return kind, " ".join(rest).strip()
    return None


def _play_collection(transcript, kind, query, room, vol, source, held_seconds) -> int:
    """Play a whole Spotify album or playlist via the same /spotify/now/ container
    endpoint as songs. Albums are explicit-pre-scanned (and blocked if any track is
    explicit); playlists can't always be scanned (Spotify 403s user playlists), so
    that gate is best-effort for them — see docs/collections.md."""
    rec = {
        "source": source, "held_seconds": held_seconds, "transcript": transcript,
        "intent_type": kind, "intent_title": query, "intent_artist": "",
        "intent_room": "", "intent_volume": vol, "room": room, "volume_applied": vol,
        "spotify_query": query, "played": False, "outcome": "no_match",
        "intent_json": json.dumps({"type": kind, "query": query}),
    }
    blocked = _quiet_hours_block()               # same quiet-hours window as songs
    if blocked:
        rec.update(outcome="blocked_time", block_reason=blocked)
        print(f"\N{LAST QUARTER MOON} quiet hours — {blocked}; not playing")
        _speak_quiet_hours()
        db.log_request(rec)
        return 1

    try:
        coll = spotify_resolve.resolve_collection(kind, query)
    except Exception as e:
        rec.update(outcome="play_failed", error_message=f"resolve: {e}")
        print(f"(spotify {kind} resolve failed: {e})", file=sys.stderr)
        db.log_request(rec)
        return 1
    if not coll:
        print(f"no Spotify {kind} match for {query!r}", file=sys.stderr)
        db.log_request(rec)
        return 1
    rec.update(result_track_id=coll["id"], result_track_name=coll["name"],
               result_artist=coll.get("artist", ""), result_uri=coll["uri"])

    # Content gate: refuse a collection that contains explicit tracks (consistent
    # with the per-song explicit refusal). Best-effort for playlists (may 403).
    if blocklist.BLOCK_EXPLICIT:
        has_expl, n_expl, n_checked = spotify_resolve.collection_explicit(coll)
        if has_expl:
            rec.update(outcome="blocked_explicit", result_explicit=True,
                       block_reason=f"explicit:{n_expl}/{n_checked} tracks")
            print(f"\N{NO ENTRY} blocked ({kind} has {n_expl} explicit of "
                  f"{n_checked}): \"{coll['name']}\" — not playing")
            _speak_blocked(coll["name"], coll.get("artist", ""), kind, "explicit")
            db.log_request(rec)
            return 1

    label = coll["name"] + (f" — {coll['artist']}" if coll.get("artist") else "")
    print(f"\N{MULTIPLE MUSICAL NOTES} {kind}: {query!r} → \"{label}\" → {room}")
    try:
        if vol is not None:
            _sonos(room, f"volume/{vol}")
        # Container play can transiently 500 like track play — retry a few times.
        last = None
        for _ in range(4):
            try:
                _sonos(room, f"spotify/now/{coll['uri']}")
                last = None
                break
            except Exception as e:
                last = e
                time.sleep(1.5)
        if last:
            raise last
        rec.update(outcome="played", played=True, played_at=datetime.now())
    except Exception as e:
        rec.update(outcome="play_failed", error_message=f"play: {e}")
        print(f"({kind} play failed: {e})", file=sys.stderr)

    db.log_request(rec)
    return 0 if rec["played"] else 1


def act_on_transcript(transcript: str, room: str,
                      source: str = "pawkey", held_seconds=None) -> int:
    """Parse intent and perform the Sonos action. Returns a shell-style code."""
    # Audible is the special case, handled deterministically BEFORE the LLM.
    # "continue my book" resumes the active book; a leading keyword ("audible X")
    # tries to play a specific one. Everything else falls through to Spotify.
    if _audible_resume_phrase(transcript):
        eff_room, _ = _extract_room(transcript, room)
        return _resume_audiobook(transcript, eff_room, source, held_seconds)
    rest = _audible_keyword(_clean_query(transcript))
    if rest is not None:
        eff_room, book = _extract_room(rest, room)
        return _play_audiobook(transcript, book, eff_room, None, source, held_seconds)

    # "album" / "playlist" keyword → play a whole collection (songs are the default).
    coll = _collection_keyword(_clean_query(transcript))
    if coll is not None:
        kind, cq = coll
        eff_room, cq = _extract_room(cq, room)
        return _play_collection(transcript, kind, cq, eff_room, None, source, held_seconds)

    try:
        intent = intent_mod.extract_intent(transcript)
        print(f"\N{BRAIN} intent: {intent}")
    except RuntimeError as e:
        print(f"(llm unavailable: {e}; keyword fallback)", file=sys.stderr)
        q = _clean_query(transcript)
        if not q:
            print("nothing recognized — try again.", file=sys.stderr)
            return 1
        fb = {"type": "song", "title": q, "artist": "", "room": "", "volume": None}
        return _play_song(transcript, fb, q, room, None, source, held_seconds)

    itype = intent.get("type")
    # A spoken room overrides the default; volume is an absolute target or None.
    eff_room = intent.get("room") or room
    vol = intent.get("volume")
    if itype == "song":
        query = intent_mod.spotify_query(intent) or _clean_query(transcript)
        if not query:
            print("didn't catch a song — try again.", file=sys.stderr)
            return 1
        return _play_song(transcript, intent, query, eff_room, vol, source, held_seconds)
    if itype == "pause":
        print(f"\N{DOUBLE VERTICAL BAR} pausing {eff_room}")
        _sonos(eff_room, "pause")
        return 0
    if itype == "resume":
        blocked = _quiet_hours_block()       # resuming also plays music
        if blocked:
            print(f"\N{LAST QUARTER MOON} quiet hours — {blocked}; not resuming")
            _speak_quiet_hours()
            return 1
        print(f"\N{BLACK RIGHT-POINTING TRIANGLE} resuming {eff_room}")
        _sonos(eff_room, "play")
        return 0
    if itype == "volume":
        if vol is not None:                       # absolute "set volume to N"
            print(f"\N{SPEAKER WITH THREE SOUND WAVES} volume {vol} in {eff_room}")
            _sonos(eff_room, f"volume/{vol}")
        else:                                     # relative "louder"/"quieter"
            direction = intent.get("direction", "up")
            delta = f"+{VOLUME_STEP}" if direction != "down" else f"-{VOLUME_STEP}"
            print(f"\N{SPEAKER WITH THREE SOUND WAVES} volume {direction} ({delta}) in {eff_room}")
            _sonos(eff_room, f"volume/{delta}")
        return 0
    print("didn't catch a request — try again.", file=sys.stderr)
    return 1


def process_wav(wav: Path, room: str, source: str = "pawkey",
                held_seconds=None) -> int:
    """Transcribe a recording and act on it."""
    if not WHISPER_BIN.exists():
        print(f"error: whisper-cli not built at {WHISPER_BIN}", file=sys.stderr)
        return 1
    transcript = transcribe(wav)
    print(f"\N{SPEECH BALLOON} heard: {transcript!r}")
    return act_on_transcript(transcript, room, source=source,
                             held_seconds=held_seconds)
