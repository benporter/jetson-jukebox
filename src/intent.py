#!/usr/bin/env python3
"""
intent.py — turn a raw speech transcript into a structured jukebox command,
using a local llama.cpp server (Qwen2.5-1.5B-Instruct).

Returns a dict like:
    {"type": "song", "title": "Count 'Em", "artist": "Brandon Lake"}
    {"type": "volume", "direction": "up"}
    {"type": "pause"} / {"type": "resume"}
    {"type": "unknown"}

v1 only acts on "song"; the other types are extracted now so the router
(volume / pause / resume) can be wired up next without prompt changes.

Run standalone to test the parser without recording:
    src/intent.py "can you put on count em by brandon lake"
    src/intent.py "turn it up"
"""
import json
import os
import sys
import urllib.error
import urllib.request

LLAMA_URL = os.environ.get("LLAMA_URL", "http://localhost:8080")

# Rooms the jukebox can target by voice; the model must pick a name from this list.
ROOMS = [r.strip() for r in os.environ.get(
    "JUKEBOX_ROOMS", "Living Room,Boys Room,Kids Room").split(",") if r.strip()]
_ROOM_LIST = ", ".join(f'"{r}"' for r in ROOMS)

SYSTEM_PROMPT = f"""You convert a young child's spoken music request (transcribed by \
speech-to-text, so it may be messy) into a JSON command for a jukebox that plays \
songs on Spotify.

Respond with ONLY a JSON object, no prose. Keys:
  "type":   one of "song", "volume", "pause", "resume", "unknown"
  "title":  the song title, or "" if not a song request
  "artist": the artist name if the child said one, else ""
  "room":   the room/speaker if they name one, chosen EXACTLY from this list:
            [{_ROOM_LIST}]; otherwise "".
  "volume": an integer 0-100 if they ask for a SPECIFIC level ("at volume 40",
            "set it to thirty"); otherwise null.
  "direction": for relative volume changes only ("louder"/"quieter"), "up" or
            "down"; otherwise omit.

Rules:
- If they ask to play / put on / hear a song, type="song". Pull out the title and
  (if mentioned) the artist. Strip filler like "can you", "please", "I want to hear".
- ONLY set "artist" if the child actually named one. Do NOT guess or add an artist
  they didn't say — leave "artist":"" so search ranks on the title alone.
- Room: "in the boys room", "play it in the kids room" => set "room" to the
  matching name from the list. No room mentioned => "room":"".
- Volume: a specific NUMBER => "volume": that number. On its own ("set the volume
  to 40", "volume 25") that's type="volume" with "volume":N. Combined with a song
  ("play X at volume 30") keep type="song" and also set "volume":30.
- "louder"/"turn it up"/"too quiet" => type="volume", direction="up" (no number).
  "quieter"/"turn it down"/"too loud" => type="volume", direction="down".
- "stop"/"pause" => type="pause".  "resume"/"keep playing"/"unpause" => type="resume".
- If you cannot tell, type="unknown".
- Fix obvious transcription mishearings of well-known songs/artists when confident.

Examples:
  "play count em by brandon lake" -> {{"type":"song","title":"Count 'Em","artist":"Brandon Lake","room":"","volume":null}}
  "can you put on let it go" -> {{"type":"song","title":"Let It Go","artist":"","room":"","volume":null}}
  "play baby shark in the boys room" -> {{"type":"song","title":"Baby Shark","artist":"","room":"Boys Room","volume":null}}
  "play purple haze in the kids room at volume 25" -> {{"type":"song","title":"Purple Haze","artist":"","room":"Kids Room","volume":25}}
  "set the volume to 40" -> {{"type":"volume","volume":40}}
  "turn it up in the living room" -> {{"type":"volume","direction":"up","room":"Living Room"}}
  "stop the music" -> {{"type":"pause"}}
  "uhh i dunno" -> {{"type":"unknown"}}"""

def extract_intent(transcript: str, timeout: float = 20.0) -> dict:
    """Call llama-server and return the parsed intent dict.

    Raises RuntimeError on transport/parse failure so the caller can fall back.
    Uses json_object mode (supported by every llama-server build); the system
    prompt enumerates the allowed keys/values and temperature 0 keeps it stable.
    """
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        "temperature": 0,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{LLAMA_URL}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"llama-server unreachable at {LLAMA_URL}: {e}")

    try:
        content = body["choices"][0]["message"]["content"]
        intent = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"could not parse intent from model output: {e}")

    intent.setdefault("type", "unknown")
    intent.setdefault("title", "")
    intent.setdefault("artist", "")
    intent["room"] = canonical_room(intent.get("room", ""))
    intent["volume"] = _parse_volume(intent.get("volume"))
    return intent


def canonical_room(value) -> str:
    """Map a model-produced room string to one of the exact ROOMS names, or "".

    Tolerant of case and partial phrasing ("the boys room", "kids") so a small
    model's slightly-off output still resolves; unknown rooms fall back to "".
    """
    if not value:
        return ""
    t = str(value).strip().lower()
    if not t:
        return ""
    for r in ROOMS:                       # exact (case-insensitive)
        if r.lower() == t:
            return r
    for r in ROOMS:                       # containment either direction
        if r.lower() in t or t in r.lower():
            return r
    for r in ROOMS:                       # first keyword: living / boys / kids
        key = r.lower().replace("'s", "").split()[0]
        if key and key in t:
            return r
    return ""


def _parse_volume(value):
    """Coerce a volume to an int in [0, 100], or None if unspecified/invalid."""
    if value is None or value == "":
        return None
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, v))


def spotify_query(intent: dict) -> str:
    """Build the best Spotify search string for a song intent.

    Uses field filters (track:/artist:) when both are known — far more accurate
    than a raw string, and avoids the connector-word ("by") relevance problems.
    """
    title = (intent.get("title") or "").strip()
    artist = (intent.get("artist") or "").strip()
    if title and artist:
        return f"track:{title} artist:{artist}"
    return title or artist


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or sys.stdin.read().strip()
    result = extract_intent(text)
    print(json.dumps(result, ensure_ascii=False))
    if result.get("type") == "song":
        print("spotify query:", spotify_query(result), file=sys.stderr)
