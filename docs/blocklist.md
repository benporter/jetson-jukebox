# Content gate / blocklist

The gate that decides whether a resolved track is allowed to play. It lives in
`src/blocklist.py` and runs in `pipeline._play_song()` **after** the Spotify
resolve (so we've recorded *what* the track is) and **before** the Sonos call.

This is separate from the **quiet-hours** gate (`docs/data-logging.md`), which
runs earlier and is about *when* music may play. The blocklist is about *what*.

## Rules (today)

1. **Explicit lyrics** — refuse any track Spotify flags `explicit: true`.
   Toggle with `JUKEBOX_BLOCK_EXPLICIT` in `config/jukebox.env` (default **on**).

A blocked request is still **fully logged**: `outcome` = `blocked_<kind>` (e.g.
`blocked_explicit`), `block_reason` = the reason string (e.g. `explicit`), and the
`result_*` fields record the track that was refused. So the dashboard's **Blocked**
chip and **most-blocked artists** card show exactly what got stopped and why.

## How a rule works

`check(track) -> reason | None` returns a short reason string when a track must
not play. Convention: `"<kind>"` or `"<kind>:<detail>"` — the part before the
colon becomes the outcome suffix (`blocked_<kind>`), the full string is the logged
`block_reason`. `outcome_for(reason)` does that mapping. Deterministic: if any
rule returns a reason, the song does not play.

## Planned rules (next increments)

These slot into `check()` with no pipeline changes — just more branches and a data
source:

- **Per-artist blocklist** → `return f"artist:{name}"` → `blocked_artist`.
- **Per-title blocklist** → `return f"title:{name}"` → `blocked_title`.

Storage options for the lists (decide when building): a small DuckDB `blocklist`
table the parent edits, or simple lines in `config/`. The DB request log already
carries `result_artist` / `result_explicit` / `external_ids` ideas to key on, and
the dashboard is the natural place to review candidates and curate the list.

## Audible feedback when refused (TODO — flagged for later)

When a song is blocked we **tell the requestor what happened** (a kid shouldn't
just get silence) — and specifically **read back the retrieved song + artist**,
because STT/intent often mishear and the resolved track is frequently not what the
child meant. Hearing it explains the disconnect.

- `pipeline._speak_blocked(name, artist, kind, reason)` uses local **Piper TTS**
  (`src/tts.py`) to speak e.g. *"Sorry, &lt;song&gt; by &lt;artist&gt; has explicit
  lyrics, so I can't play it."* on the Pebble (`_clean_for_speech` drops " -
  Remaster"-style tags first). Synthesized WAVs are cached (`data/tts-cache/`).
- **Fallback:** if Piper isn't installed, it plays the static beep
  (`JUKEBOX_BLOCKED_SOUND`, default `assets/blocked.wav`) so blocking is still
  audible. So the feature degrades gracefully.
- **Install Piper:** `setup/install_piper.sh` (downloads the aarch64 binary + a
  voice into `tools/piper/`, gitignored). See `docs/project_plan.md` / `src/tts.py`.

Both the per-song explicit gate and the album explicit pre-scan speak the read-back.

## Config

```
JUKEBOX_BLOCK_EXPLICIT="1"          # 0 to allow explicit tracks
# JUKEBOX_BLOCKED_SOUND="assets/blocked.wav"   # spoken "not allowed" clip (unset = silent)
```

Changes need a daemon restart: `sudo systemctl restart jukebox-pawkey`.
