# Request logging & the quiet-hours gate

How the jukebox records what gets requested/played, and how the time gate works.
Both are recent additions; this is the reference for them.

## What's logged, and where

Every **song request** is logged as one row in a **DuckDB** database at
`data/jukebox.duckdb` (gitignored). Non-song interactions (pause/resume/volume)
are intentionally **not** logged — songs are what we care to review.

Written by `src/db.py`, called from `src/pipeline.py` after each song request.
Schema (see `db.py` for the authoritative `CREATE TABLE`):

| group | columns |
|---|---|
| when/who | `request_id`, `requested_at` (local time), `source` (`pawkey`/`cli`/`test`), `held_seconds` |
| said/understood | `transcript`, `intent_type`, `intent_title`, `intent_artist`, `intent_room`, `intent_volume`, `intent_json` |
| search | `spotify_query`, `result_track_id`, `result_track_name`, `result_artist`, `result_uri`, `result_explicit` |
| outcome | `outcome`, `played`, `played_at`, `room`, `volume_applied`, `block_reason`, `error_message` |

`outcome` is the disposition of the request:
`played` · `no_match` · `play_failed` · `blocked_time` *(quiet hours)* ·
`blocked_explicit` *(explicit-lyrics gate)* · `blocked_artist` / `blocked_title`
*(future per-item blocklist)*.

`result_explicit` is Spotify's per-track explicit flag. The **content gate**
(`src/blocklist.py`, `docs/blocklist.md`) refuses explicit tracks by default
(`outcome='blocked_explicit'`). `result_*` (what search returned) is kept separate
from `played` so a request that's **blocked** still
records the song that *would* have played, which is the whole point of being able
to review what's getting blocked.

## ⚠️ DuckDB is single-writer — connect read-only to inspect

DuckDB allows one read-write process at a time. The daemon therefore
**opens → inserts one row → closes** per request (`src/db.py`), keeping the file
free between writes. To look at the data while the jukebox is running, connect
**read-only** so you don't fight the writer:

```bash
python3 -c "import duckdb; [print(r) for r in duckdb.connect('data/jukebox.duckdb', read_only=True).execute('select requested_at, transcript, result_track_name, result_artist, result_explicit, outcome from requests order by requested_at desc limit 20').fetchall()]"
```

Handy queries:
```sql
-- most-requested songs
SELECT intent_title, count(*) n FROM requests WHERE outcome='played'
  GROUP BY 1 ORDER BY n DESC LIMIT 20;
-- what got blocked, and why
SELECT requested_at, transcript, outcome, block_reason FROM requests
  WHERE outcome LIKE 'blocked_%' ORDER BY requested_at DESC;
-- explicit tracks that slipped through (pre-blocklist)
SELECT requested_at, result_track_name, result_artist FROM requests
  WHERE result_explicit ORDER BY requested_at DESC;
```

Writes are **best-effort**: if logging fails (locked file, etc.) the daemon warns
to stderr and keeps playing. Logging never breaks playback.

## Quiet hours (the time gate)

Songs play only when the **local system clock** is inside the allowed window.
Deterministic — it reads the clock, no LLM involved.

- Gate script: `setup/within_play_hours.sh` — exit **0 = allowed**, **3 = blocked**,
  any other code = the script errored. Takes an optional `HH:MM` arg for testing
  (`setup/within_play_hours.sh 23:15`).
- Window: `JUKEBOX_PLAY_START` / `JUKEBOX_PLAY_END` in `config/jukebox.env`
  (default **05:00–22:00**, inclusive start, exclusive end). Env vars win over the
  file; the file is the fallback for standalone CLI use.
- Enforcement: `pipeline._quiet_hours_block()` checks the gate **before** searching
  Spotify (no API call when blocked). It gates **song play and resume** (both play
  music). Blocked song requests log `outcome='blocked_time'` + `block_reason`.
- **Fails open:** if the gate script errors (non-0/3 exit), playback is *allowed*
  — a bug in the gate must never brick the jukebox. (A genuine block is exit 3.)

To change the hours, edit `config/jukebox.env` and restart `jukebox-pawkey`.

## Content gate (built — see docs/blocklist.md)
The **explicit-lyrics** rule is live: `pipeline._play_song` runs
`blocklist.check()` right after resolving the track; explicit tracks log
`outcome='blocked_explicit'` and don't play. Per-artist/title blocklists slot into
the same gate next (`blocked_artist` / `blocked_title`).

## See also
- `src/db.py` (schema + write path), `src/spotify_resolve.py` (search/explicit),
  `src/pipeline.py` (`_play_song`, `_quiet_hours_block`).
- `config/jukebox.env` (window + room/volume defaults).
- `requirements.txt` / `setup/install_build_deps.sh` (the `duckdb` dependency).
