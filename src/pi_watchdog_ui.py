#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime
from time import monotonic
from threading import Lock
import calendar
import json
import os
import re

LOG_PATH = Path(os.environ.get("PI_WATCHDOG_LOG_PATH", "/var/log/pi-watchdog.log"))
HOST = "0.0.0.0"
PORT = int(os.environ.get("PI_WATCHDOG_PORT", "8098"))
SUMMARY_WINDOW = 1000

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PiWatchdog</title>
  <style>
    :root { color-scheme: light; --bg:#edf3f7; --card:rgba(255,255,255,.92); --card-strong:#ffffff; --text:#12202b; --muted:#60717d; --ok:#18794e; --bad:#c0362c; --soft:#eef3f7; --accent:#0a6dff; --accent-2:#14b8a6; --accent-warm:#ff8a3d; --border:rgba(120,145,164,.22); --shadow:0 20px 45px rgba(18,32,43,.08); }
    * { box-sizing:border-box; }
    body { margin:0; font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:
      radial-gradient(circle at top left, rgba(20,184,166,.18), transparent 24%),
      radial-gradient(circle at top right, rgba(10,109,255,.16), transparent 30%),
      linear-gradient(180deg,#eef5f8,#f9fbfc 38%, #f6fafc 100%); color:var(--text); }
    header { padding:28px 20px 22px; color:#fff; background:
      radial-gradient(circle at 10% 10%, rgba(20,184,166,.28), transparent 24%),
      radial-gradient(circle at 85% 20%, rgba(255,138,61,.24), transparent 20%),
      linear-gradient(135deg, #0b2238 0%, #103452 50%, #0b2238 100%); border-bottom:1px solid rgba(255,255,255,.08); }
    .hero { max-width:1180px; margin:0 auto; }
    .eyebrow { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; background:rgba(255,255,255,.12); color:#dbe8f3; font-size:12px; letter-spacing:.08em; text-transform:uppercase; }
    .eyebrow::before { content:""; width:8px; height:8px; border-radius:999px; background:linear-gradient(135deg,var(--accent-2),#8cf5d8); box-shadow:0 0 18px rgba(20,184,166,.55); }
    .hero-top { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
    .machine-chip { display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border-radius:999px; background:rgba(255,255,255,.12); color:#eef6fb; font-size:13px; border:1px solid rgba(255,255,255,.14); }
    .machine-chip strong { font-size:14px; }
    h1 { margin:14px 0 0; font-size:34px; letter-spacing:-.03em; }
    .sub { margin-top:10px; color:#c7d5e2; font-size:15px; max-width:760px; }
    main { max-width:1180px; margin:0 auto; padding:24px 20px 30px; display:grid; gap:20px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }
    .card, .chart-card { position:relative; background:var(--card); backdrop-filter:blur(10px); border:1px solid var(--border); border-radius:18px; padding:14px 16px; box-shadow:var(--shadow); overflow:hidden; }
    .card::before, .chart-card::before { content:""; position:absolute; inset:0 auto auto 0; width:100%; height:4px; background:linear-gradient(90deg,var(--accent),var(--accent-2),var(--accent-warm)); opacity:.9; }
    .label { font-size:13px; color:var(--muted); margin-bottom:6px; }
    .value { font-size:28px; font-weight:700; }
    .value.compact { font-size:20px; line-height:1.25; }
    .toolbar { display:flex; gap:12px; flex-wrap:wrap; align-items:center; padding:14px; background:rgba(255,255,255,.66); border:1px solid var(--border); border-radius:18px; box-shadow:var(--shadow); backdrop-filter:blur(10px); }
    .toolbar input, .toolbar select, .toolbar button { padding:10px 12px; border-radius:12px; border:1px solid var(--border); background:rgba(255,255,255,.92); color:var(--text); }
    .toolbar input { min-width:240px; flex:1 1 260px; }
    .toolbar select { min-width:130px; }
    .toolbar button { background:linear-gradient(135deg,var(--accent),#2d86ff); color:#fff; border:none; cursor:pointer; box-shadow:0 10px 22px rgba(10,109,255,.18); font-weight:600; }
    .toolbar button:hover { transform:translateY(-1px); }
    .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
    .chart-head { display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:8px; }
    .chart-title { font-size:14px; font-weight:700; }
    .chart-meta { font-size:12px; color:var(--muted); }
    .chart-svg { width:100%; height:120px; display:block; }
    .chart-empty { color:var(--muted); font-size:13px; padding:24px 0; text-align:center; }
    .chart-axis { stroke:#bfd0dc; stroke-width:1; }
    .chart-grid { stroke:#e8f0f5; stroke-width:1; }
    .chart-line { fill:none; stroke-width:2.5; stroke-linecap:round; stroke-linejoin:round; }
    .chart-dot { r:2.2; }
    table { width:100%; border-collapse:collapse; background:var(--card-strong); border:1px solid var(--border); border-radius:18px; overflow:hidden; box-shadow:var(--shadow); }
    th, td { padding:10px 12px; border-bottom:1px solid var(--border); text-align:left; font-size:14px; vertical-align:top; }
    th { background:linear-gradient(180deg,#f9fbfd,#f2f7fa); color:#41515c; position:sticky; top:0; }
    tr.fail { background:#fff4f2; }
    tbody tr:hover { background:#f7fbfe; }
    .pill { display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700; }
    .ok { background:#e9f7ef; color:var(--ok); }
    .bad { background:#fdecea; color:var(--bad); }
    .muted-pill { background:var(--soft); color:var(--muted); }
    .raw { white-space:pre-wrap; background:#0f1720; color:#d6e2ef; padding:14px; border-radius:12px; overflow:auto; max-height:60vh; font-size:13px; }
    dialog { width:min(1000px,95vw); border:none; border-radius:20px; padding:0; box-shadow:0 30px 80px rgba(0,0,0,.25); }
    dialog::backdrop { background:rgba(4,12,20,.5); }
    .modal-head { display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border-bottom:1px solid var(--border); background:#fff; }
    .modal-body { padding:18px; background:#f8fbfd; }
    .close { background:#e9eef2; color:#10202b; }
    .hint, .time-sub { color:var(--muted); font-size:12px; }
    .time-sub { display:block; margin-top:4px; }
    @media (max-width: 720px) {
      header { padding:16px; }
      h1 { font-size:26px; }
      main { padding:14px; gap:14px; }
      .cards { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
      .toolbar { display:grid; grid-template-columns:1fr 1fr; }
      .toolbar input { grid-column:1 / -1; }
      .toolbar button, .toolbar select, .toolbar input { width:100%; }
      table, thead, tbody, th, td, tr { display:block; }
      table { border:none; box-shadow:none; background:transparent; }
      thead { display:none; }
      tbody { display:grid; gap:12px; }
      tr { background:var(--card); border:1px solid var(--border); border-radius:14px; box-shadow:0 8px 24px rgba(12,37,62,.06); overflow:hidden; }
      tr.fail { background:#fff4f2; }
      td { border-bottom:1px solid var(--border); display:grid; grid-template-columns:96px 1fr; gap:10px; align-items:start; }
      td:last-child { border-bottom:none; }
      td::before { content:attr(data-label); color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.03em; }
    }
  </style>
</head>
<body>
<header>
  <div class="hero">
    <div class="hero-top">
      <div class="eyebrow">Realtime board watchdog</div>
      <div class="machine-chip">Machine <strong id="machineName">Loading...</strong></div>
    </div>
    <h1>PiWatchdog</h1>
    <div class="sub">Browse watchdog snapshots, draw trends, and inspect raw diagnostics with a cleaner live dashboard that stays fast on small boards.</div>
  </div>
</header>
<main>
  <section class="cards" id="cards"></section>
  <section class="charts" id="charts"></section>
  <section class="toolbar">
    <input id="search" placeholder="Search raw text or timestamp">
    <select id="limit">
      <option value="100">100 rows</option>
      <option value="250" selected>250 rows</option>
      <option value="500">500 rows</option>
      <option value="1000">1000 rows</option>
    </select>
    <select id="filter">
      <option value="all">All snapshots</option>
      <option value="fail">Failures only</option>
      <option value="actionable">Actionable only</option>
      <option value="ok">Healthy only</option>
    </select>
    <button id="sort" type="button">Sort: Newest First</button>
    <button id="autoload" type="button">Auto Load: Off</button>
    <button id="reload" type="button">Reload</button>
    <span class="hint" id="hint"></span>
  </section>
  <section>
    <table>
      <thead>
        <tr><th>Timestamp</th><th>Ping</th><th>DNS</th><th>Kernel</th><th>Root Use</th><th>Temp Max</th><th>Notes</th><th>Raw</th></tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </section>
</main>
<dialog id="modal">
  <div class="modal-head">
    <strong id="modalTitle">Snapshot</strong>
    <button class="close" onclick="document.getElementById('modal').close()">Close</button>
  </div>
  <div class="modal-body">
    <div class="raw" id="raw"></div>
  </div>
</dialog>
<script>
let snapshots = [];
let snapshotMap = new Map();
const DEFAULT_LIMIT = 250;
const AUTOLOAD_INTERVAL_MS = 30000;
let autoLoadTimer = null;
let isLoading = false;
let sortDirection = 'desc';

function getSelectedLimit() {
  const value = Number(document.getElementById('limit').value);
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_LIMIT;
}
function pill(kind, text) { return `<span class="pill ${kind}">${text}</span>`; }
function esc(s) { return (s || '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function formatLocalTime(value) {
  if (!value) return { main: '-', sub: '' };
  const iso = value.split(' ')[0];
  const host = value.slice(iso.length).trim();
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return { main: value, sub: '' };
  const main = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(dt);
  const sub = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).format(dt);
  return { main, sub: host ? `${host} · ${sub}` : sub };
}
function hostFromTimestamp(value) {
  if (!value) return 'Unknown';
  const parts = value.split(' ');
  return parts.length > 1 ? parts.slice(1).join(' ') : 'Unknown';
}
function updateMachineName(summary) {
  const machine = hostFromTimestamp(summary.last || summary.first || '');
  document.getElementById('machineName').textContent = machine;
  document.title = `${machine} · PiWatchdog`;
}
function cards(summary) {
  const first = formatLocalTime(summary.first);
  const last = formatLocalTime(summary.last);
  const data = [
    ['Loaded', summary.count],
    ['First', `<span>${esc(first.main)}</span><span class="time-sub">${esc(first.sub || '-')}</span>`, true],
    ['Last', `<span>${esc(last.main)}</span><span class="time-sub">${esc(last.sub || '-')}</span>`, true],
    ['Ping Failures', summary.ping_failures],
    ['DNS Failures', summary.dns_failures],
    ['Actionable Kernel', summary.actionable_kernel],
    ['Boot Noise', summary.boot_noise],
    ['Max Temp', summary.max_temp_c == null ? '-' : `${summary.max_temp_c.toFixed(1)} C`],
  ];
  document.getElementById('cards').innerHTML = data.map(([l,v,compact]) => `<div class="card"><div class="label">${l}</div><div class="value ${compact ? 'compact' : ''}">${v}</div></div>`).join('');
}
function seriesRange(values) {
  const nums = values.filter(v => Number.isFinite(v));
  if (!nums.length) return null;
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (min === max) { min -= 1; max += 1; }
  return { min, max };
}
function linePath(values, width, height, pad, range) {
  const nums = values.map(v => Number.isFinite(v) ? v : null);
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const points = [];
  nums.forEach((value, index) => {
    if (value == null) return;
    const x = pad + (nums.length === 1 ? innerW / 2 : (index / (nums.length - 1)) * innerW);
    const y = pad + (1 - ((value - range.min) / (range.max - range.min))) * innerH;
    points.push([x, y]);
  });
  if (!points.length) return { path: '', dots: '' };
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(' ');
  const dots = points.map(point => `<circle class="chart-dot" cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}"></circle>`).join('');
  return { path, dots };
}
function renderChart(title, meta, values, color, formatter) {
  const width = 320;
  const height = 120;
  const pad = 16;
  const range = seriesRange(values);
  if (!range) return `<div class="chart-card"><div class="chart-head"><div class="chart-title">${esc(title)}</div><div class="chart-meta">${esc(meta)}</div></div><div class="chart-empty">No data in this window.</div></div>`;
  const { path, dots } = linePath(values, width, height, pad, range);
  const top = formatter(range.max);
  const bottom = formatter(range.min);
  const latest = formatter(values.filter(v => Number.isFinite(v)).slice(-1)[0]);
  return `<div class="chart-card"><div class="chart-head"><div class="chart-title">${esc(title)}</div><div class="chart-meta">${esc(meta)} · latest ${esc(latest)}</div></div><svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="${esc(title)} trend"><line class="chart-grid" x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}"></line><line class="chart-grid" x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}"></line><line class="chart-axis" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line><path class="chart-line" stroke="${color}" d="${path}"></path><g fill="${color}">${dots}</g><text x="${pad}" y="12" font-size="11" fill="#5b6b76">${esc(top)}</text><text x="${pad}" y="${height - 2}" font-size="11" fill="#5b6b76">${esc(bottom)}</text></svg></div>`;
}
function renderCharts() {
  const charts = [
    ['Disk Usage', 'root filesystem', snapshots.map(s => s.root_use_pct), '#0057b8', v => `${v.toFixed(0)}%`],
    ['CPU Load', '1-minute load', snapshots.map(s => s.load_1), '#b85c00', v => v.toFixed(2)],
    ['Memory Used', 'RAM in use', snapshots.map(s => s.mem_used_pct), '#18794e', v => `${v.toFixed(0)}%`],
    ['Temperature', 'max thermal zone', snapshots.map(s => s.temp_max_c), '#c0362c', v => `${v.toFixed(1)} C`],
    ['Ping Latency', 'gateway RTT', snapshots.map(s => s.ping_avg_ms), '#7a3cff', v => `${v.toFixed(1)} ms`],
  ];
  document.getElementById('charts').innerHTML = charts.map(([title, meta, values, color, formatter]) => renderChart(title, meta, values, color, formatter)).join('');
}
function kernelPill(s) {
  if (s.kernel_status === 'actionable') return pill('bad', 'active warning');
  if (s.kernel_status === 'boot-noise') return pill('muted-pill', 'boot noise');
  return pill('ok', 'quiet');
}
function rowNotes(s) {
  const notes = [];
  if (s.failure_diagnostics) notes.push('extra diagnostics');
  if (s.kernel_status === 'boot-noise') notes.push('kernel lines are old boot-time noise');
  if (s.kernel_status === 'actionable' && s.kernel_hits.length) notes.push(s.kernel_hits.slice(0, 2).join(' | '));
  return notes.join(' ; ') || '-';
}
function rowHtml(s, index) {
  const local = formatLocalTime(s.timestamp);
  return `<tr class="${(s.ping_status !== 'ok' || s.dns_status !== 'ok') ? 'fail' : ''}"><td data-label="Timestamp"><div>${esc(local.main)}</div><span class="time-sub">${esc(local.sub || '-')}</span></td><td data-label="Ping">${pill(s.ping_status === 'ok' ? 'ok' : 'bad', s.ping_status)}</td><td data-label="DNS">${pill(s.dns_status === 'ok' ? 'ok' : 'bad', s.dns_status)}</td><td data-label="Kernel">${kernelPill(s)}</td><td data-label="Root Use">${esc(s.root_use || '-')}</td><td data-label="Temp Max">${s.temp_max_c == null ? '-' : s.temp_max_c.toFixed(1) + ' C'}</td><td data-label="Notes">${esc(rowNotes(s))}</td><td data-label="Raw"><button data-i="${index}">Open</button></td></tr>`;
}
function bindRowButtons(filtered) {
  document.querySelectorAll('button[data-i]').forEach(btn => btn.onclick = async () => {
    const s = filtered[Number(btn.dataset.i)];
    document.getElementById('modalTitle').textContent = s.timestamp;
    document.getElementById('raw').textContent = 'Loading...';
    document.getElementById('modal').showModal();
    const raw = await loadRaw(s.id);
    document.getElementById('raw').textContent = raw;
  });
}
function currentFilterState() {
  return { q: document.getElementById('search').value.toLowerCase(), mode: document.getElementById('filter').value };
}
function sortedSnapshots(items) {
  const list = [...items];
  list.sort((a, b) => sortDirection === 'asc' ? a.timestamp.localeCompare(b.timestamp) : b.timestamp.localeCompare(a.timestamp));
  return list;
}
function matchesCurrentFilter(snapshot) {
  const { q, mode } = currentFilterState();
  const hasNetworkFailure = snapshot.ping_status !== 'ok' || snapshot.dns_status !== 'ok';
  const actionable = hasNetworkFailure || snapshot.kernel_status === 'actionable';
  if (mode === 'fail' && !hasNetworkFailure) return false;
  if (mode === 'actionable' && !actionable) return false;
  if (mode === 'ok' && hasNetworkFailure) return false;
  if (!q) return true;
  return (snapshot.timestamp + '\\n' + (snapshot.notes_text || '')).toLowerCase().includes(q);
}
function visibleSnapshots() {
  return sortedSnapshots(snapshots.filter(matchesCurrentFilter));
}
function updateSortButton() {
  document.getElementById('sort').textContent = `Sort: ${sortDirection === 'desc' ? 'Newest First' : 'Oldest First'}`;
}
function render() {
  const filtered = visibleSnapshots();
  document.getElementById('hint').textContent = `${filtered.length} shown`;
  document.getElementById('rows').innerHTML = filtered.map((s, i) => rowHtml(s, i)).join('');
  bindRowButtons(filtered);
}
function appendRows(newItems) {
  const rows = document.getElementById('rows');
  const filtered = visibleSnapshots();
  const visibleIds = new Set(filtered.map(s => s.id));
  const appendable = sortedSnapshots(newItems.filter(s => visibleIds.has(s.id)));
  if (!appendable.length) {
    document.getElementById('hint').textContent = `${filtered.length} shown`;
    return false;
  }
  rows.insertAdjacentHTML(sortDirection === 'desc' ? 'afterbegin' : 'beforeend', appendable.map(s => rowHtml(s, filtered.findIndex(item => item.id === s.id))).join(''));
  bindRowButtons(filtered);
  document.getElementById('hint').textContent = `${filtered.length} shown · ${appendable.length} new`;
  return true;
}
async function loadRaw(id) {
  const cached = snapshotMap.get(id);
  if (cached && cached.raw) return cached.raw;
  const res = await fetch(`/api/snapshot?id=${encodeURIComponent(id)}`);
  const data = await res.json();
  if (cached) cached.raw = data.raw;
  return data.raw || 'No raw log found.';
}
function mergeSnapshots(nextSnapshots, limit) {
  const previousIds = new Set(snapshots.map(s => s.id));
  const newItems = nextSnapshots.filter(s => !previousIds.has(s.id));
  snapshots = nextSnapshots;
  snapshotMap = new Map(nextSnapshots.map(s => [s.id, s]));
  if (snapshots.length > limit) {
    snapshots = snapshots.slice(-limit);
    snapshotMap = new Map(snapshots.map(s => [s.id, s]));
  }
  return newItems;
}
function updateAutoLoadButton() {
  const active = autoLoadTimer !== null;
  document.getElementById('autoload').textContent = `Auto Load: ${active ? 'On' : 'Off'}`;
}
function stopAutoLoad() {
  if (autoLoadTimer !== null) {
    window.clearInterval(autoLoadTimer);
    autoLoadTimer = null;
  }
  updateAutoLoadButton();
}
function startAutoLoad() {
  stopAutoLoad();
  autoLoadTimer = window.setInterval(() => refreshData(false), AUTOLOAD_INTERVAL_MS);
  updateAutoLoadButton();
}
async function refreshData(fullRender = true) {
  if (isLoading) return;
  isLoading = true;
  try {
    const limit = getSelectedLimit();
  const [summaryRes, snapshotsRes] = await Promise.all([fetch(`/api/summary?limit=${limit}`), fetch(`/api/snapshots?limit=${limit}`)]);
  const summary = await summaryRes.json();
  const nextSnapshots = await snapshotsRes.json();
  const newItems = mergeSnapshots(nextSnapshots, limit);
    updateMachineName(summary);
    cards(summary);
    renderCharts();
    if (fullRender || newItems.length === 0) {
      render();
    } else {
      const state = currentFilterState();
      const appended = !state.q && state.mode === 'all' && appendRows(newItems);
      if (!appended) {
        render();
        document.getElementById('hint').textContent = `${document.getElementById('hint').textContent} · ${newItems.length} new`;
      }
    }
  } finally {
    isLoading = false;
  }
}
async function load() { await refreshData(true); }

const savedLimit = window.localStorage.getItem('watchdog-limit');
if (savedLimit) {
  const limitSelect = document.getElementById('limit');
  if ([...limitSelect.options].some(option => option.value === savedLimit)) limitSelect.value = savedLimit;
}
const savedSort = window.localStorage.getItem('watchdog-sort');
if (savedSort === 'asc' || savedSort === 'desc') sortDirection = savedSort;

document.getElementById('search').addEventListener('input', render);
document.getElementById('limit').addEventListener('change', event => {
  window.localStorage.setItem('watchdog-limit', event.target.value);
  load();
});
document.getElementById('filter').addEventListener('change', render);
document.getElementById('sort').addEventListener('click', () => {
  sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
  window.localStorage.setItem('watchdog-sort', sortDirection);
  updateSortButton();
  render();
});
document.getElementById('autoload').addEventListener('click', () => {
  if (autoLoadTimer === null) {
    window.localStorage.setItem('watchdog-autoload', 'on');
    startAutoLoad();
    refreshData(false);
  } else {
    window.localStorage.setItem('watchdog-autoload', 'off');
    stopAutoLoad();
  }
});
document.getElementById('reload').addEventListener('click', load);
if (window.localStorage.getItem('watchdog-autoload') === 'on') startAutoLoad();
updateSortButton();
updateAutoLoadButton();
load();
</script>
</body>
</html>
"""

KERNEL_PATTERN = re.compile(r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})")
INTERESTING_KERNEL_WORDS = ("brcmf", "failed", "reset", "oom", "no buffer space", "mmc", "ext4")


def split_blocks(text: str):
    blocks = []
    for part in text.split("=== "):
        if not part.strip():
            continue
        blocks.append("=== " + part.strip() + "\n")
    return blocks


def extract_section(block: str, start: str, end: str | None = None):
    if start not in block:
        return ""
    section = block.split(start, 1)[1]
    if end and end in section:
        section = section.split(end, 1)[0]
    return section.strip()


def parse_snapshot_ts(text: str):
    try:
        return datetime.fromisoformat(text.split()[0])
    except ValueError:
        return None


def parse_kernel_ts(line: str, snapshot_ts: datetime | None):
    if snapshot_ts is None:
        return None
    match = KERNEL_PATTERN.match(line)
    if not match:
        return None
    month = list(calendar.month_abbr).index(match.group("mon"))
    day = int(match.group("day"))
    time_text = match.group("time")
    candidate = datetime.strptime(f"{snapshot_ts.year}-{month:02d}-{day:02d} {time_text}", "%Y-%m-%d %H:%M:%S")
    if candidate > snapshot_ts.replace(tzinfo=None):
        candidate = candidate.replace(year=candidate.year - 1)
    return candidate


def classify_kernel_hits(snapshot_ts: datetime | None, kernel_hits: list[str]):
    if not kernel_hits:
        return "quiet"
    ages = []
    for line in kernel_hits:
        hit_ts = parse_kernel_ts(line, snapshot_ts)
        if hit_ts is None or snapshot_ts is None:
            return "actionable"
        ages.append((snapshot_ts.replace(tzinfo=None) - hit_ts).total_seconds())
    if ages and min(ages) > 6 * 3600:
        return "boot-noise"
    return "actionable"


def parse_block(raw: str):
    first = raw.splitlines()[0].replace("=== ", "").replace(" ===", "").strip()
    snapshot_ts = parse_snapshot_ts(first)
    load_section = extract_section(raw, "-- loadavg --", "-- memory --")
    memory_section = extract_section(raw, "-- memory --", "-- filesystem --")
    ping_section = extract_section(raw, "-- ping gateway --", "-- dns --")
    dns_section = extract_section(raw, "-- dns --", "-- recent kernel warnings --")

    root_use = None
    match = re.search(r"/\S+\s+\S+\s+\S+\s+\S+\s+(\d+%)\s+/", raw)
    if match:
        root_use = match.group(1)
    root_use_pct = float(root_use.rstrip("%")) if root_use else None

    load_1 = None
    match = re.search(r"([0-9.]+)\s+[0-9.]+\s+[0-9.]+\s+\d+/\d+\s+\d+", load_section)
    if match:
        load_1 = float(match.group(1))

    mem_used_pct = None
    match = re.search(r"Mem:\s+([0-9.]+)Gi\s+([0-9.]+)Gi", memory_section)
    if match:
        total = float(match.group(1))
        used = float(match.group(2))
        if total > 0:
            mem_used_pct = used / total * 100

    temps = [int(x) / 1000 for x in re.findall(r"thermal_zone\d+/temp=(\d+)", raw)]

    ping_avg_ms = None
    match = re.search(r"rtt min/avg/max/mdev = [0-9.]+/([0-9.]+)/", ping_section)
    if match:
        ping_avg_ms = float(match.group(1))

    kernel_hits = []
    for line in extract_section(raw, "-- recent kernel warnings --").splitlines():
        low = line.lower()
        if any(word in low for word in INTERESTING_KERNEL_WORDS):
            kernel_hits.append(line.strip())
    kernel_status = classify_kernel_hits(snapshot_ts, kernel_hits)

    ping_status = "ok" if "0% packet loss" in ping_section else "fail"
    dns_status = "ok" if ("changelogs.ubuntu.com" in dns_section and "google.com" in dns_section) else "fail"

    notes = []
    if "-- failure diagnostics --" in raw:
        notes.append("extra diagnostics")
    if kernel_status == "boot-noise":
        notes.append("kernel lines are old boot-time noise")
    if kernel_status == "actionable" and kernel_hits:
        notes.append(" | ".join(kernel_hits[:2]))

    return {
        "id": first,
        "timestamp": first,
        "ping_status": ping_status,
        "ping_avg_ms": ping_avg_ms,
        "dns_status": dns_status,
        "root_use": root_use,
        "root_use_pct": root_use_pct,
        "load_1": load_1,
        "mem_used_pct": mem_used_pct,
        "temp_max_c": max(temps) if temps else None,
        "failure_diagnostics": "-- failure diagnostics --" in raw,
        "kernel_hits": kernel_hits[:5],
        "kernel_status": kernel_status,
        "notes_text": " ; ".join(notes),
        "raw": raw,
    }


SNAPSHOT_CACHE = {
    "mtime_ns": None,
    "size": None,
    "loaded_at": 0.0,
    "snapshots": [],
    "by_id": {},
}
SNAPSHOT_LOCK = Lock()


def read_recent_blocks(limit: int):
    if not LOG_PATH.exists():
        return []
    marker = b"=== "
    chunk_size = 262144
    data = b""
    with LOG_PATH.open("rb") as fh:
        fh.seek(0, 2)
        position = fh.tell()
        while position > 0 and data.count(marker) <= limit:
            read_size = min(chunk_size, position)
            position -= read_size
            fh.seek(position)
            data = fh.read(read_size) + data
    return split_blocks(data.decode(errors="ignore"))[-limit:]


def load_snapshots():
    stat = LOG_PATH.stat() if LOG_PATH.exists() else None
    mtime_ns = stat.st_mtime_ns if stat else None
    size = stat.st_size if stat else None
    with SNAPSHOT_LOCK:
      if (
          SNAPSHOT_CACHE["snapshots"]
          and SNAPSHOT_CACHE["mtime_ns"] == mtime_ns
          and SNAPSHOT_CACHE["size"] == size
          and monotonic() - SNAPSHOT_CACHE["loaded_at"] < 15
      ):
          return SNAPSHOT_CACHE["snapshots"]
      snapshots = [parse_block(block) for block in read_recent_blocks(SUMMARY_WINDOW)]
      SNAPSHOT_CACHE.update({
          "mtime_ns": mtime_ns,
          "size": size,
          "loaded_at": monotonic(),
          "snapshots": snapshots,
          "by_id": {s["id"]: s for s in snapshots},
      })
      return snapshots


def snapshot_brief(snapshot: dict):
    return {
        "id": snapshot["id"],
        "timestamp": snapshot["timestamp"],
        "ping_status": snapshot["ping_status"],
        "ping_avg_ms": snapshot["ping_avg_ms"],
        "dns_status": snapshot["dns_status"],
        "root_use": snapshot["root_use"],
        "root_use_pct": snapshot["root_use_pct"],
        "load_1": snapshot["load_1"],
        "mem_used_pct": snapshot["mem_used_pct"],
        "temp_max_c": snapshot["temp_max_c"],
        "failure_diagnostics": snapshot["failure_diagnostics"],
        "kernel_hits": snapshot["kernel_hits"],
        "kernel_status": snapshot["kernel_status"],
        "notes_text": snapshot["notes_text"],
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body, code=200):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._html(HTML)
        if parsed.path == "/api/snapshots":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["200"])[0])
            snaps = load_snapshots()
            if limit:
                snaps = snaps[-limit:]
            return self._json([snapshot_brief(s) for s in snaps])
        if parsed.path == "/api/snapshot":
            qs = parse_qs(parsed.query)
            snapshot_id = qs.get("id", [""])[0]
            snap = SNAPSHOT_CACHE["by_id"].get(snapshot_id)
            if snap is None:
                load_snapshots()
                snap = SNAPSHOT_CACHE["by_id"].get(snapshot_id)
            if snap is None:
                return self._json({"error": "not found"}, 404)
            return self._json({"id": snapshot_id, "raw": snap["raw"]})
        if parsed.path == "/api/summary":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", [str(SUMMARY_WINDOW)])[0])
            snaps = load_snapshots()
            if limit:
                snaps = snaps[-limit:]
            temps = [s["temp_max_c"] for s in snaps if s["temp_max_c"] is not None]
            return self._json({
                "count": len(snaps),
                "first": snaps[0]["timestamp"] if snaps else None,
                "last": snaps[-1]["timestamp"] if snaps else None,
                "ping_failures": sum(1 for s in snaps if s["ping_status"] != "ok"),
                "dns_failures": sum(1 for s in snaps if s["dns_status"] != "ok"),
                "actionable_kernel": sum(1 for s in snaps if s["kernel_status"] == "actionable"),
                "boot_noise": sum(1 for s in snaps if s["kernel_status"] == "boot-noise"),
                "max_temp_c": max(temps) if temps else None,
            })
        return self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
