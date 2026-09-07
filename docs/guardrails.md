# Deterministic guardrails — the if/then spine of the workflow

This is an AI **workflow**, not an autonomous agent. There is **intentionally no
agent loop.** The models do two narrow jobs — whisper.cpp turns speech into text,
and a small LLM parses that text into a structured intent — and then **plain code
decides what actually happens.** Every decision that matters for safety is a
hard-coded `if/then`, not a model choice. The LLM never decides whether to play,
when it's allowed, or what's appropriate.

Each guardrail below has a one-line description, a link to the exact code, and the
block itself. Links point to `main` on GitHub; local `path:line` is IDE-clickable.

---

## 1. No agent loop — keyword routing runs *before* the LLM

Special cases (audiobooks, albums, playlists) are matched by deterministic keyword
rules first. The model is only consulted for the leftover *song / pause / resume /
volume* case — it can't reroute the request to a different service.

**Code:** [`src/pipeline.py` L557–573](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L557-L573)

```python
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
```

---

## 2. Push-to-talk — only records while the paw is physically held

The mic records only between the key-down and key-up of the paw button; there is
no wake word and no always-on listening. A press shorter than 0.3 s is treated as
a mis-tap and thrown away, so a bump never sends audio down the pipeline.

**Code:** [`src/pawkey_listen.py` L104–124](https://github.com/benporter/jetson-jukebox/blob/main/src/pawkey_listen.py#L104-L124)

```python
    def stop_and_process(self):
        if self.proc is None:
            return
        held = time.monotonic() - self.start
        self.proc.send_signal(signal.SIGINT)   # let arecord finalize the WAV
        ...
        if held < MIN_RECORD_SECONDS:
            print("(too quick — hold the paw down while you talk)")
        else:
            try:
                pipeline.process_wav(proc_wav, self.room,
                                     source="pawkey", held_seconds=held)
```

---

## 3. Quiet-hours (after-hours) gate — a clock, not the model

Before anything plays, a shell script compares the local system clock to a fixed
window (default 05:00–22:00). No LLM, no guessing. Outside the window the request
is logged as `blocked_time` and never reaches Spotify.

**Code:** [`setup/within_play_hours.sh` L43–53](https://github.com/benporter/jetson-jukebox/blob/main/setup/within_play_hours.sh#L43-L53)

```bash
if (( s <= e )); then
  (( n >= s && n < e )) && ok=1 || ok=0          # same-day window
else
  (( n >= s || n < e )) && ok=1 || ok=0          # window wraps midnight
fi

if (( ok )); then
  exit 0
fi
echo "outside play hours ${START}-${END} (now ${NOW})" >&2
exit 3
```

The caller **fails open**: if the gate script itself errors, the jukebox still
plays. A bug in a guardrail must never brick the appliance.

**Code:** [`src/pipeline.py` L128–139](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L128-L139)

```python
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
```

---

## 4. Explicit-lyrics refusal — per song

After a track resolves, a content gate refuses anything Spotify flags as
`explicit`. The refused track is still logged (so a parent sees what was asked
for), the reason becomes the DB outcome, and no Sonos call is made.

**Code:** [`src/blocklist.py` L27–41](https://github.com/benporter/jetson-jukebox/blob/main/src/blocklist.py#L27-L41)

```python
def check(track: dict | None) -> str | None:
    """Return a block reason if `track` must NOT play, else None."""
    if not track:
        return None
    if BLOCK_EXPLICIT and track.get("explicit"):
        return "explicit"
    # Future rules slot in here, e.g.:
    #   if track.get("artist") in artist_blocklist(): return f"artist:{track['artist']}"
    #   if track.get("name")   in title_blocklist():  return f"title:{track['name']}"
    return None
```

The gate runs *after* resolve (so the refused track is logged) and *before* the
Sonos call:

**Code:** [`src/pipeline.py` L274–281](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L274-L281)

```python
        reason = blocklist.check(track)
        if reason:
            rec.update(outcome=blocklist.outcome_for(reason), block_reason=reason)
            print(f"\N{NO ENTRY} blocked ({reason}): "
                  f"\"{track['name']} - {track['artist']}\" — not playing")
            _speak_blocked(track["name"], track["artist"], "song", reason)
            db.log_request(rec)
            return 1
```

---

## 5. Full album / playlist scan — every track, not just one

A request for a whole album or playlist is not trusted on the strength of one
song. The gate paginates through **every** track (up to a cap) and refuses the
entire collection if **any** track is explicit.

**Code:** [`src/spotify_resolve.py` L257–277](https://github.com/benporter/jetson-jukebox/blob/main/src/spotify_resolve.py#L257-L277)

```python
        n = n_expl = 0
        if kind == "album":
            url = (f"https://api.spotify.com/v1/albums/{cid}/tracks"
                   f"?limit=50&market={market}")
            while url and n < max_tracks:
                body = _api_get(url, token)
                for t in body.get("items", []):
                    n += 1
                    n_expl += 1 if t.get("explicit") else 0
                url = body.get("next")
        else:  # playlist — fields= keeps the payload tiny
            url = (f"https://api.spotify.com/v1/playlists/{cid}/tracks"
                   f"?limit=100&market={market}&fields=next,items(track(explicit))")
            while url and n < max_tracks:
                body = _api_get(url, token)
                for it in body.get("items", []):
                    t = it.get("track") or {}
                    n += 1
                    n_expl += 1 if t.get("explicit") else 0
                url = body.get("next")
        return (n_expl > 0, n_expl, n)
```

Any explicit track blocks the whole collection:

**Code:** [`src/pipeline.py` L517–526](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L517-L526)

```python
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
```

> Note: playlist track-enumeration can 403 under client-credentials auth, in which
> case the scan **fails open** — so kid safety leans on curated playlists. See
> [docs/collections.md](collections.md).

---

## 6. Stairway easter egg — a hard track-ID match

A deterministic check by track ID (and a title/artist fallback): if the search
resolves to Led Zeppelin's *Stairway to Heaven*, a local clip plays on the Pebble
instead of the song on Sonos. It's playful, but it's the same pattern — an exact
`if` on the resolved result, not a model judgment.

**Code:** [`src/pipeline.py` L176–182](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L176-L182) (match) · [L264–270](https://github.com/benporter/jetson-jukebox/blob/main/src/pipeline.py#L264-L270) (action)

```python
def _is_stairway(track) -> bool:
    """True if the resolved track is Led Zeppelin's Stairway to Heaven (the egg)."""
    if (track.get("id") or "") in STAIRWAY_TRACK_IDS:
        return True
    name = (track.get("name") or "").lower()
    artist = (track.get("artist") or "").lower()
    return "stairway to heaven" in name and "led zeppelin" in artist
```

```python
        if _is_stairway(track):
            rec.update(outcome="blocked_easteregg", block_reason="Easter egg")
            print(f"\N{EGG} Easter egg — \"{track['name']} - {track['artist']}\": "
                  f"no Stairway! Denied! (local clip, not Sonos)")
            _play_local_sound(EASTEREGG_SOUND)
            db.log_request(rec)
            return 1
```

---

### The pattern

Resolve first, then gate. Every gate is a small, testable `if` in plain Python or
shell; each one logs *what* it stopped and *why*, and the safety-critical ones
fail open so a bug never bricks playback. The models advise; the code decides.
