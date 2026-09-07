/* Jukebox dashboard — fetches the snapshot-backed API and renders an
   interactive, filterable table. No build step; vendored Grid.js. */
'use strict';

const state = { status: 'all', range: '30', room: '' };
let grid = null;

/* ---- time range → from/to (local naive ISO the DuckDB TIMESTAMP accepts) ---- */
function pad(n) { return String(n).padStart(2, '0'); }
function fmt(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
         `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function rangeBounds(r) {
  const now = new Date();
  if (r === 'all') return { from: null, to: null };
  if (r === 'today') {
    const start = new Date(now); start.setHours(0, 0, 0, 0);
    return { from: fmt(start), to: null };
  }
  const days = parseInt(r, 10);
  const start = new Date(now.getTime() - days * 86400000);
  return { from: fmt(start), to: null };
}

function badge(outcome, played) {
  let cls = 'b-other', txt = outcome || '—';
  if (played) cls = 'b-played';
  else if (outcome === 'no_match' || outcome === 'play_failed') cls = 'b-failed';
  else if (outcome && outcome.startsWith('blocked')) cls = 'b-blocked';
  return gridjs.html(`<span class="badge ${cls}">${txt}</span>`);
}

// Split the stored timestamp ("2026-06-14 07:43:10.123456", or ISO with 'T')
// into [date, time] for display. Milliseconds are dropped here only — the
// underlying requested_at keeps full precision in the data/API.
function splitDateTime(s) {
  if (!s) return ['', ''];
  const [d, t = ''] = s.replace('T', ' ').split(' ');
  return [d, t.replace(/\.\d+$/, '').slice(0, 8)];  // HH:MM:SS, no ms
}

function renderKpis(s) {
  const pct = s.total ? Math.round((s.played / s.total) * 100) : 0;
  const cards = [
    ['Requests', s.total, ''],
    [`Played (${pct}%)`, s.played, 'ok'],
    ['Failed', s.failed, s.failed ? 'bad' : ''],
    ['Blocked', s.blocked, s.blocked ? 'warn' : ''],
  ];
  document.getElementById('kpis').innerHTML = cards.map(([l, n, c]) =>
    `<div class="kpi ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`
  ).join('');
}

function gb(b) { return (b / 1e9).toFixed(1) + ' GB'; }
function kb(b) { return b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB'
                                 : (b / 1e3).toFixed(0) + ' KB'; }

function renderTuning(s) {
  const ft = (s.top_failed_titles || []).map(x =>
    `<li><span>${esc(x.title)}</span><span class="n">${x.n}</span></li>`).join('');
  const ba = (s.top_blocked_artists || []).map(x =>
    `<li><span>${esc(x.artist)}</span><span class="n">${x.n}</span></li>`).join('');
  document.getElementById('tuning').innerHTML = `
    <div class="tuning">
      <div class="tcard"><h3>Top titles that failed to play</h3>
        ${ft ? `<ol>${ft}</ol>` : '<div class="empty">none in range 🎉</div>'}</div>
      <div class="tcard"><h3>Most-blocked artists</h3>
        ${ba ? `<ol>${ba}</ol>` : '<div class="empty">nothing blocked in range</div>'}</div>
    </div>`;
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

async function loadStats(params) {
  try {
    const res = await fetch('/api/stats?' + params.toString());
    const s = await res.json();
    renderKpis(s);
    renderTuning(s);
  } catch (e) { /* KPIs fall back to blank */ }
}

async function loadDisk() {
  try {
    const res = await fetch('/api/disk');
    const d = await res.json();
    const usedPct = (100 - d.free_pct).toFixed(1);
    const lvl = d.level === 'ok' ? '' : d.level;
    const tag = d.level === 'ok' ? '' :
      ` · <span class="stale">${d.level === 'critical' ? '⚠ critically low' : '⚠ low'}</span>`;
    const age = d.snapshot_age == null ? '—' : Math.round(d.snapshot_age) + 's';
    document.getElementById('disk').innerHTML = `
      <div class="disk ${lvl}">
        <div class="row">
          <span class="t"><b>Disk</b> ${d.free_pct}% free${tag}</span>
          <span class="det">${gb(d.free_bytes)} free of ${gb(d.total_bytes)} ·
            DB ${kb(d.db_bytes)}${d.db_wal_bytes ? ' (+' + kb(d.db_wal_bytes) + ' wal)' : ''} ·
            snapshot ${kb(d.snapshot_bytes)}, ${age} old</span>
        </div>
        <div class="bar"><div style="width:${usedPct}%"></div></div>
      </div>`;
  } catch (e) { /* non-fatal */ }
}

const COLS = [
  { id: 'date', name: 'Date' },
  { id: 'time', name: 'Time' },
  { id: 'intent_type', name: 'Type' },
  { id: 'transcript', name: 'Heard' },
  { id: 'intent_title', name: 'Title' },
  { id: 'intent_artist', name: 'Artist' },
  { id: 'result_track_name', name: 'Got (track)' },
  { id: 'result_artist', name: 'Got (artist)' },
  { id: 'result_explicit', name: 'Explicit' },
  { id: 'outcome', name: 'Outcome' },
  { id: 'room', name: 'Room' },
  { id: 'volume_applied', name: 'Vol' },
  { id: 'block_reason', name: 'Block' },
  { id: 'error_message', name: 'Error' },
];

function toRow(r) {
  const [date, time] = splitDateTime(r.requested_at);
  return COLS.map(col => {
    if (col.id === 'date') return date;
    if (col.id === 'time') return time;
    if (col.id === 'outcome') return badge(r.outcome, r.played);
    if (col.id === 'result_explicit') {
      return r.result_explicit
        ? gridjs.html('<span class="badge b-blocked">explicit</span>') : '';
    }
    const v = r[col.id];
    return v === null || v === undefined ? '' : v;
  });
}

async function load() {
  const { from, to } = rangeBounds(state.range);
  const p = new URLSearchParams({ status: state.status, limit: '2000' });
  if (from) p.set('from', from);
  if (to) p.set('to', to);
  if (state.room) p.set('room', state.room);

  // Stats (accurate counts + tuning lists) and disk run alongside the table.
  loadStats(p);
  loadDisk();

  document.getElementById('meta').textContent = 'loading…';
  let data;
  try {
    const res = await fetch('/api/requests?' + p.toString());
    data = await res.json();
  } catch (e) {
    document.getElementById('meta').textContent = 'API error: ' + e;
    return;
  }

  const rows = data.rows || [];

  const age = data.snapshot_age == null ? '—' : Math.round(data.snapshot_age) + 's';
  const stale = data.snapshot_age != null && data.snapshot_age > 180;
  document.getElementById('meta').innerHTML =
    `${rows.length} request(s) shown · snapshot ` +
    `<span class="${stale ? 'stale' : ''}">${age} old</span>` +
    (data.snapshot_ready ? '' : ' · <span class="stale">no data yet</span>');

  const config = {
    columns: COLS.map(c => c.name),
    data: rows.map(toRow),
    search: true,
    sort: true,
    pagination: { limit: 25 },
  };
  if (grid) { grid.updateConfig(config).forceRender(); }
  else { grid = new gridjs.Grid(config); grid.render(document.getElementById('table')); }
}

async function loadRooms() {
  try {
    const res = await fetch('/api/rooms');
    const { rooms } = await res.json();
    const sel = document.getElementById('room');
    rooms.forEach(r => {
      const o = document.createElement('option'); o.value = r; o.textContent = r;
      sel.appendChild(o);
    });
  } catch (e) { /* non-fatal */ }
}

function wire() {
  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.status = btn.dataset.status;
      load();
    });
  });
  document.getElementById('range').addEventListener('change', e => {
    state.range = e.target.value; load();
  });
  document.getElementById('room').addEventListener('change', e => {
    state.room = e.target.value; load();
  });
}

wire();
loadRooms();
load();
setInterval(load, 30000); // auto-refresh view every 30s
