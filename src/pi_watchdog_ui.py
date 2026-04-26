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
import shutil
import subprocess

LOG_PATH = Path(os.environ.get("PI_WATCHDOG_LOG_PATH", "/var/log/pi-watchdog.log"))
SPEED_HISTORY_PATH = Path(os.environ.get(
    "PI_WATCHDOG_SPEED_HISTORY_PATH",
    str(Path.home() / ".local/share/pi-watchdog/speed-history.jsonl"),
) or str(Path.home() / ".local/share/pi-watchdog/speed-history.jsonl"))
HOST = "0.0.0.0"
PORT = int(os.environ.get("PI_WATCHDOG_PORT", "8098"))
SNAPSHOTS_PER_DAY = 24 * 60
SUMMARY_WINDOW = SNAPSHOTS_PER_DAY * 7
DEFAULT_SNAPSHOT_LIMIT = 250
MAX_SNAPSHOT_LIMIT = SUMMARY_WINDOW
SPEED_CHUNK = b"\0" * (1024 * 1024)
MAX_SPEED_BYTES = 1024 * 1024 * 1024

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PiWatchdog</title>
  <style>
    :root { color-scheme: light; --bg:#f4f7fa; --surface:#ffffff; --surface-2:#f8fafc; --surface-3:#eef4f8; --text:#152433; --muted:#647484; --ok:#117a52; --bad:#c23b32; --warn:#a65b00; --accent:#1468d8; --accent-2:#0d8f7f; --accent-warm:#df7a20; --border:#d8e1e8; --border-strong:#bdcbd7; --shadow:0 12px 28px rgba(25,43,58,.08); --shadow-soft:0 6px 18px rgba(25,43,58,.06); }
    * { box-sizing:border-box; }
    body { margin:0; font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }
    button, input, select { font:inherit; }
    button, a, input, select { transition:border-color .16s ease, box-shadow .16s ease, background-color .16s ease, transform .16s ease; }
    button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, .chart-card.clickable:focus-visible { outline:3px solid rgba(20,104,216,.22); outline-offset:2px; }
    header { padding:20px 20px 18px; color:#f7fbff; background:#10263a; border-bottom:1px solid #0b1c2b; box-shadow:0 1px 0 rgba(255,255,255,.05) inset; }
    .hero { max-width:1240px; margin:0 auto; }
    .eyebrow { display:inline-flex; align-items:center; gap:8px; padding:5px 9px; border-radius:6px; background:#18374f; color:#d7e4ee; font-size:12px; letter-spacing:.06em; text-transform:uppercase; border:1px solid rgba(255,255,255,.08); }
    .eyebrow::before { content:""; width:8px; height:8px; border-radius:999px; background:var(--accent-2); box-shadow:0 0 0 3px rgba(13,143,127,.16); }
    .hero-top { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
    .machine-chip { display:inline-flex; align-items:center; gap:8px; padding:7px 10px; border-radius:6px; background:#18374f; color:#edf5fb; font-size:13px; border:1px solid rgba(255,255,255,.1); }
    .machine-chip strong { font-size:14px; }
    h1 { margin:12px 0 0; font-size:32px; letter-spacing:0; line-height:1.1; }
    .sub { margin-top:8px; color:#bfd0de; font-size:14px; max-width:780px; line-height:1.5; }
    main { max-width:1240px; margin:0 auto; padding:18px 20px 28px; display:grid; gap:16px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:10px; }
    .card, .chart-card { position:relative; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:13px 14px; box-shadow:var(--shadow-soft); overflow:hidden; }
    .card::before, .chart-card::before { content:""; position:absolute; inset:0 auto auto 0; width:100%; height:3px; background:var(--accent); opacity:.95; }
    .label { font-size:12px; color:var(--muted); margin-bottom:6px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
    .value { font-size:26px; font-weight:800; line-height:1.15; }
    .value.compact { font-size:20px; line-height:1.25; }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:8px; box-shadow:var(--shadow-soft); }
    .toolbar input, .toolbar select, .toolbar button { min-height:40px; padding:9px 11px; border-radius:6px; border:1px solid var(--border); background:var(--surface); color:var(--text); }
    .toolbar input:focus, .toolbar select:focus, .speed-controls input:focus, .speed-controls select:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(20,104,216,.12); outline:none; }
    .toolbar input { min-width:240px; flex:1 1 260px; }
    .toolbar select { min-width:130px; }
    .toolbar button { background:var(--accent); color:#fff; border-color:var(--accent); cursor:pointer; box-shadow:0 8px 16px rgba(20,104,216,.16); font-weight:700; }
    .toolbar button:hover { transform:translateY(-1px); }
    .toolbar button:disabled, .toolbar select:disabled { opacity:.58; cursor:wait; transform:none; }
    .loading-status { display:none; align-items:center; gap:8px; min-height:40px; padding:9px 11px; border-radius:6px; background:#eef6ff; color:#23527f; border:1px solid #cfe0f2; font-size:13px; font-weight:800; }
    .loading-status.active { display:inline-flex; }
    .loading-status::before { content:""; width:14px; height:14px; border-radius:999px; border:2px solid rgba(35,82,127,.22); border-top-color:var(--accent); animation:spin .75s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }
    .speed-panel { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; box-shadow:var(--shadow-soft); display:grid; gap:14px; }
    .speed-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }
    .speed-title { font-size:16px; font-weight:800; }
    .speed-sub { color:var(--muted); font-size:13px; margin-top:4px; }
    .speed-controls { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .speed-controls input, .speed-controls select, .speed-controls button { min-height:40px; padding:9px 11px; border-radius:6px; border:1px solid var(--border); background:#fff; color:var(--text); }
    .speed-controls input { min-width:170px; }
    .speed-controls button { border-color:var(--accent); background:var(--accent); color:#fff; cursor:pointer; font-weight:700; box-shadow:0 8px 16px rgba(20,104,216,.15); }
    .speed-controls button:disabled { opacity:.55; cursor:not-allowed; transform:none; }
    .speed-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
    .speed-result { background:var(--surface-2); border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
    .speed-metric { font-size:26px; font-weight:800; line-height:1.2; }
    .speed-detail { color:var(--muted); font-size:12px; margin-top:4px; }
    .speed-bar { height:8px; border-radius:999px; background:#e2ebf2; overflow:hidden; }
    .speed-bar span { display:block; height:100%; width:0%; background:var(--accent-2); transition:width .18s ease; }
    .history-toolbar { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    .history-actions { display:flex; gap:10px; flex-wrap:wrap; }
    .history-actions button, .history-actions a { display:inline-flex; align-items:center; min-height:38px; padding:8px 11px; border-radius:6px; background:#fff; color:var(--text); text-decoration:none; cursor:pointer; font-weight:700; border:1px solid var(--border); }
    .history-actions button:hover, .history-actions a:hover { border-color:var(--border-strong); background:var(--surface-2); }
    .history-chart { width:100%; height:180px; display:block; background:#fff; border:1px solid var(--border); border-radius:8px; }
    .history-list { display:grid; gap:10px; }
    .history-item { display:grid; grid-template-columns:130px 1fr auto; gap:12px; align-items:start; background:#fff; border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
    .history-main { min-width:0; }
    .history-title { font-size:14px; font-weight:800; color:var(--text); }
    .history-detail { color:var(--muted); font-size:12px; line-height:1.45; margin-top:4px; }
    .quality { display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px; font-size:12px; font-weight:800; background:var(--surface-3); color:var(--muted); white-space:nowrap; }
    .quality.excellent { background:#e9f7ef; color:var(--ok); }
    .quality.ok { background:#eef3f7; color:#315064; }
    .quality.slow { background:#fff4e8; color:#9a5200; }
    .quality.unstable { background:#fdecea; color:var(--bad); }
    .maintenance { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; box-shadow:var(--shadow-soft); display:grid; gap:14px; }
    .maintenance-head { display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }
    .maintenance-title { font-size:16px; font-weight:800; }
    .maintenance-sub { color:var(--muted); font-size:13px; margin-top:4px; }
    .maintenance button { min-height:40px; padding:9px 11px; border:1px solid var(--accent); border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; font-weight:700; box-shadow:0 8px 16px rgba(20,104,216,.15); }
    .maintenance-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }
    .maintenance-card { background:var(--surface-2); border:1px solid var(--border); border-radius:8px; padding:12px 14px; min-width:0; }
    .maintenance-card h3 { margin:0 0 10px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
    .metric-list { display:grid; gap:8px; }
    .metric-row { display:flex; justify-content:space-between; gap:12px; color:#213847; font-size:13px; }
    .metric-row span:first-child { color:var(--muted); }
    .metric-row strong { text-align:right; overflow-wrap:anywhere; }
    .status-line { display:flex; align-items:center; gap:8px; margin-bottom:8px; font-size:13px; color:#213847; }
    .status-dot { width:9px; height:9px; border-radius:999px; background:var(--muted); flex:0 0 auto; }
    .status-dot.ok { background:var(--ok); }
    .status-dot.bad { background:var(--bad); }
    .status-dot.warn { background:var(--accent-warm); }
    .maintenance-note { color:var(--muted); font-size:12px; line-height:1.45; }
    .ops-section { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; box-shadow:var(--shadow-soft); display:grid; gap:14px; }
    .ops-head { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    .ops-title { font-size:16px; font-weight:800; }
    .ops-sub { color:var(--muted); font-size:13px; margin-top:4px; }
    .ops-head button { min-height:40px; padding:9px 11px; border:1px solid var(--accent); border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; font-weight:700; box-shadow:0 8px 16px rgba(20,104,216,.15); }
    .timeline { display:grid; gap:10px; }
    .timeline-item { display:grid; grid-template-columns:98px 1fr; gap:12px; background:#fff; border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
    .timeline-time { color:var(--muted); font-size:12px; line-height:1.4; }
    .timeline-title { font-size:14px; font-weight:800; color:var(--text); }
    .timeline-body { color:#315064; font-size:13px; line-height:1.45; margin-top:3px; }
    .container-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
    .container-card { background:#fff; border:1px solid var(--border); border-radius:8px; padding:12px 14px; min-width:0; }
    .container-top { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; margin-bottom:10px; }
    .container-name { font-weight:800; color:var(--text); overflow-wrap:anywhere; }
    .container-image { color:var(--muted); font-size:12px; margin-top:3px; overflow-wrap:anywhere; }
    .container-status { font-size:12px; font-weight:800; border-radius:999px; padding:4px 8px; background:var(--surface-3); color:var(--muted); white-space:nowrap; }
    .container-status.ok { background:#e9f7ef; color:var(--ok); }
    .container-status.bad { background:#fdecea; color:var(--bad); }
    .alerts-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
    .alert-card { background:#fff; border:1px solid var(--border); border-radius:8px; padding:12px 14px; display:grid; gap:8px; }
    .alert-card.warn { border-color:rgba(255,138,61,.45); background:#fffaf5; }
    .alert-card.bad { border-color:rgba(192,54,44,.35); background:#fff5f4; }
    .alert-card.ok { border-color:rgba(24,121,78,.24); background:#f7fcf9; }
    .alert-top { display:flex; align-items:center; justify-content:space-between; gap:10px; }
    .alert-title { font-weight:800; color:var(--text); }
    .alert-body { color:#315064; font-size:13px; line-height:1.45; }
    .alert-badge { border-radius:999px; padding:4px 8px; font-size:12px; font-weight:800; background:var(--surface-3); color:var(--muted); }
    .alert-badge.warn { background:#fff0df; color:#9a5200; }
    .alert-badge.bad { background:#fdecea; color:var(--bad); }
    .alert-badge.ok { background:#e9f7ef; color:var(--ok); }
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
    .chart-focus-line { stroke:rgba(18,32,43,.28); stroke-width:1.5; stroke-dasharray:4 4; }
    .chart-focus-dot { stroke:#fff; stroke-width:2; }
    .chart-tooltip { position:absolute; z-index:3; min-width:140px; max-width:220px; padding:10px 12px; border-radius:8px; background:rgba(11,34,56,.94); color:#eef6fb; box-shadow:0 18px 36px rgba(7,18,30,.24); pointer-events:none; font-size:12px; line-height:1.45; transform:translateX(-50%); }
    .chart-tooltip-time { color:#d7e7f4; font-weight:700; margin-bottom:6px; }
    .chart-tooltip-row { display:flex; align-items:center; justify-content:space-between; gap:10px; }
    .chart-tooltip-label { display:inline-flex; align-items:center; gap:6px; color:#d7e7f4; }
    .chart-tooltip-swatch { width:9px; height:9px; border-radius:999px; }
    .chart-tooltip-value { color:#fff; font-weight:700; }
    .chart-card.clickable { cursor:pointer; transition:transform .16s ease, box-shadow .16s ease; }
    .chart-card.clickable:hover { transform:translateY(-1px); border-color:var(--border-strong); box-shadow:var(--shadow); }
    .chart-legend { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:8px; }
    .legend-item { display:inline-flex; align-items:center; gap:6px; color:var(--muted); font-size:12px; }
    .legend-swatch { width:10px; height:10px; border-radius:999px; }
    table { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:8px; overflow:hidden; box-shadow:var(--shadow-soft); }
    th, td { padding:10px 12px; border-bottom:1px solid var(--border); text-align:left; font-size:14px; vertical-align:top; }
    th { background:#f2f7fa; color:#41515c; position:sticky; top:0; }
    tr.fail { background:#fff4f2; }
    tbody tr:hover { background:#f7fbfe; }
    .pill { display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700; }
    .ok { background:#e9f7ef; color:var(--ok); }
    .bad { background:#fdecea; color:var(--bad); }
    .muted-pill { background:var(--surface-3); color:var(--muted); }
    .raw { white-space:pre-wrap; background:#0f1720; color:#d6e2ef; padding:14px; border-radius:8px; overflow:auto; max-height:60vh; font-size:13px; }
    .inspect-btn { display:inline-flex; align-items:center; gap:8px; min-height:36px; padding:8px 11px; border:1px solid var(--accent); border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; font-weight:800; letter-spacing:0; box-shadow:0 8px 16px rgba(20,104,216,.15); }
    .inspect-btn::before { content:""; width:7px; height:7px; border-radius:999px; background:rgba(255,255,255,.92); }
    .inspect-btn::after { content:"Open"; font-weight:700; opacity:.95; }
    .inspect-btn:hover { transform:translateY(-1px); }
    dialog { width:min(1000px,95vw); border:none; border-radius:8px; padding:0; box-shadow:0 30px 80px rgba(0,0,0,.25); }
    dialog::backdrop { background:rgba(4,12,20,.5); }
    .modal-head { display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border-bottom:1px solid var(--border); background:#fff; }
    .modal-body { padding:18px; background:#f8fbfd; }
    .close { display:inline-flex; align-items:center; justify-content:center; min-width:42px; height:40px; padding:0 14px; border:1px solid var(--border); border-radius:6px; background:#fff; color:#10202b; font-weight:800; cursor:pointer; box-shadow:var(--shadow-soft); transition:transform .16s ease, box-shadow .16s ease, background .16s ease; }
    .close:hover { transform:translateY(-1px); box-shadow:var(--shadow); background:var(--surface-2); }
    .close:active { transform:translateY(0); box-shadow:inset 0 2px 4px rgba(18,32,43,.08); }
    .hint, .time-sub { color:var(--muted); font-size:12px; }
    .time-sub { display:block; margin-top:4px; }
    .chart-modal-svg { width:100%; height:min(72vh,720px); display:block; }
    .mode-switch { display:flex; gap:10px; margin-bottom:14px; }
    .mode-btn { padding:8px 12px; border-radius:6px; border:1px solid var(--border); background:#fff; color:var(--muted); font-weight:700; cursor:pointer; }
    .mode-btn.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .readable { display:grid; gap:14px; }
    [hidden] { display:none !important; }
    .readable-overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }
    .overview-card { background:#ffffff; border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
    .overview-label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; font-weight:700; margin-bottom:6px; }
    .overview-value { color:var(--text); font-size:18px; font-weight:800; line-height:1.2; }
    .readable-card { background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px; }
    .readable-title { margin:0 0 8px; font-size:14px; font-weight:800; color:var(--text); }
    .readable-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }
    .readable-item { background:#f6fafc; border:1px solid var(--border); border-radius:8px; padding:10px 12px; }
    .readable-item strong { display:block; font-size:12px; text-transform:uppercase; color:var(--muted); letter-spacing:.04em; margin-bottom:5px; }
    .readable-item span { color:#173246; font-size:13px; line-height:1.45; white-space:pre-wrap; word-break:break-word; }
    .readable-list { display:grid; gap:8px; }
    .readable-list-item { background:#f7fbfd; border:1px solid var(--border); border-radius:8px; padding:10px 12px; color:#1f3f54; font-size:13px; line-height:1.5; white-space:pre-wrap; word-break:break-word; }
    .readable-empty { color:var(--muted); font-size:13px; }
    .readable-pre { margin:0; white-space:pre-wrap; color:#274052; font-size:13px; line-height:1.5; }
    @media (max-width: 720px) {
      header { padding:16px; }
      h1 { font-size:26px; }
      main { padding:14px; gap:14px; }
      .cards { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
      .toolbar { display:grid; grid-template-columns:1fr 1fr; }
      .toolbar input { grid-column:1 / -1; }
      .toolbar button, .toolbar select, .toolbar input { width:100%; }
      .speed-controls { display:grid; grid-template-columns:1fr 1fr; width:100%; }
      .speed-controls input, .speed-controls select { grid-column:1 / -1; }
      .speed-controls button { width:100%; }
      .history-item { grid-template-columns:1fr; }
      .maintenance button { width:100%; }
      .ops-head button { width:100%; }
      .timeline-item { grid-template-columns:1fr; }
      table, thead, tbody, th, td, tr { display:block; }
      table { border:none; box-shadow:none; background:transparent; }
      thead { display:none; }
      tbody { display:grid; gap:12px; }
      tr { background:var(--surface); border:1px solid var(--border); border-radius:8px; box-shadow:0 8px 24px rgba(12,37,62,.06); overflow:hidden; }
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
  <section class="speed-panel">
    <div class="speed-head">
      <div>
        <div class="speed-title">LAN Speed Test</div>
        <div class="speed-sub">Measures this browser to this Pi over the current local network path.</div>
      </div>
      <div class="speed-controls">
        <input id="speedClientLabel" placeholder="Client label">
        <select id="speedSize">
          <option value="32">32 MB</option>
          <option value="128" selected>128 MB</option>
          <option value="256">256 MB</option>
          <option value="512">512 MB</option>
          <option value="1024">1 GB</option>
        </select>
        <button id="speedDownload" type="button">Download</button>
        <button id="speedUpload" type="button">Upload</button>
      </div>
    </div>
    <div class="speed-grid">
      <div class="speed-result">
        <div class="label">Pi to Browser</div>
        <div class="speed-metric" id="downloadSpeed">-</div>
        <div class="speed-detail" id="downloadDetail">Download not tested</div>
      </div>
      <div class="speed-result">
        <div class="label">Browser to Pi</div>
        <div class="speed-metric" id="uploadSpeed">-</div>
        <div class="speed-detail" id="uploadDetail">Upload not tested</div>
      </div>
    </div>
    <div class="speed-bar"><span id="speedProgress"></span></div>
  </section>
  <section class="ops-section">
    <div class="ops-head">
      <div>
        <div class="ops-title">Network Quality Timeline</div>
        <div class="ops-sub">Saved manual speed tests by client label, direction, and watchdog ping context.</div>
      </div>
      <div class="history-actions">
        <a id="speedExport" href="/api/speed/history/export">Export</a>
        <button id="speedClear" type="button">Clear</button>
        <button id="speedHistoryRefresh" type="button">Refresh</button>
      </div>
    </div>
    <svg class="history-chart" id="speedHistoryChart" viewBox="0 0 900 180" preserveAspectRatio="none"></svg>
    <div class="history-list" id="speedHistoryList"></div>
  </section>
  <section class="maintenance">
    <div class="maintenance-head">
      <div>
        <div class="maintenance-title">Maintenance</div>
        <div class="maintenance-sub">Rotation, cleanup, reboot history, and storage shape for this Pi.</div>
      </div>
      <button id="maintenanceRefresh" type="button">Refresh</button>
    </div>
    <div class="maintenance-grid" id="maintenanceGrid"></div>
  </section>
  <section class="ops-section">
    <div class="ops-head">
      <div>
        <div class="ops-title">Event Timeline</div>
        <div class="ops-sub">Recent failures, warnings, and reboot markers from watchdog data.</div>
      </div>
      <button id="timelineRefresh" type="button">Refresh</button>
    </div>
    <div class="timeline" id="eventTimeline"></div>
  </section>
  <section class="ops-section">
    <div class="ops-head">
      <div>
        <div class="ops-title">Alerts</div>
        <div class="ops-sub">Threshold checks for disk, temperature, DNS, ping, and containers.</div>
      </div>
      <button id="alertsRefresh" type="button">Refresh</button>
    </div>
    <div class="alerts-grid" id="alertsGrid"></div>
  </section>
  <section class="ops-section">
    <div class="ops-head">
      <div>
        <div class="ops-title">Container Health</div>
        <div class="ops-sub">Current Docker container status, uptime, and resource hints.</div>
      </div>
      <button id="containerRefresh" type="button">Refresh</button>
    </div>
    <div class="container-grid" id="containerGrid"></div>
  </section>
  <section class="toolbar">
    <input id="search" placeholder="Search raw text or timestamp">
    <select id="limit">
      <option value="100">100 rows</option>
      <option value="250" selected>250 rows</option>
      <option value="500">500 rows</option>
      <option value="1000">1000 rows</option>
      <option value="1440">1 day</option>
      <option value="4320">3 days</option>
      <option value="10080">7 days</option>
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
    <span class="loading-status" id="loadingStatus" role="status" aria-live="polite">Loading snapshots...</span>
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
    <button class="close" type="button" onclick="document.getElementById('modal').close()" aria-label="Close details">Close</button>
  </div>
  <div class="modal-body">
    <div class="mode-switch">
      <button class="mode-btn active" id="modeReadable" type="button">Readable</button>
      <button class="mode-btn" id="modeRaw" type="button">Raw</button>
    </div>
    <div class="readable" id="readableView"></div>
    <div class="raw" id="raw" hidden></div>
  </div>
</dialog>
<dialog id="chartModal">
  <div class="modal-head">
    <strong id="chartModalTitle">Chart</strong>
    <button class="close" type="button" onclick="document.getElementById('chartModal').close()" aria-label="Close chart">Close</button>
  </div>
  <div class="modal-body">
    <div class="chart-meta" id="chartModalMeta"></div>
    <div class="chart-legend" id="chartModalLegend"></div>
    <div id="chartModalContent"></div>
  </div>
</dialog>
<script>
let snapshots = [];
let snapshotMap = new Map();
let chartDefinitions = [];
const DEFAULT_LIMIT = 250;
const AUTOLOAD_INTERVAL_MS = 30000;
let autoLoadTimer = null;
let isLoading = false;
let sortDirection = 'desc';
let speedTestRunning = false;

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
function metricRows(rows) {
  return `<div class="metric-list">${rows.map(([label, value]) => `<div class="metric-row"><span>${esc(label)}</span><strong>${esc(value == null ? '-' : String(value))}</strong></div>`).join('')}</div>`;
}
function statusLine(kind, text) {
  return `<div class="status-line"><span class="status-dot ${kind}"></span><span>${esc(text)}</span></div>`;
}
function renderMaintenance(data) {
  const rotation = data.rotation || {};
  const reboot = data.reboot || {};
  const storage = data.storage || {};
  const docker = storage.docker || {};
  const cleanup = data.cleanup || {};
  document.getElementById('maintenanceGrid').innerHTML = [
    `<div class="maintenance-card"><h3>Log Rotation</h3>
      ${statusLine(rotation.docker_logrotate ? 'ok' : 'warn', rotation.docker_logrotate ? 'Docker JSON logrotate rule found' : 'Docker JSON logrotate rule not found')}
      ${statusLine(rotation.docker_daemon_rotation ? 'ok' : 'warn', rotation.docker_daemon_rotation ? 'Docker daemon rotation configured' : 'Docker daemon rotation not detected')}
      ${metricRows([
        ['Journal usage', rotation.journal_usage || '-'],
        ['Watchdog log', rotation.watchdog_log_size || '-'],
        ['Docker logrotate', rotation.docker_logrotate_path || '-'],
      ])}
    </div>`,
    `<div class="maintenance-card"><h3>Cleanup Status</h3>
      ${metricRows([
        ['Apt cache', cleanup.apt_cache || '-'],
        ['Apt lists', cleanup.apt_lists || '-'],
        ['Largest Docker log', cleanup.largest_docker_log || '-'],
        ['wtmp', cleanup.wtmp || '-'],
      ])}
      <div class="maintenance-note">${esc(cleanup.note || '')}</div>
    </div>`,
    `<div class="maintenance-card"><h3>Reboot History</h3>
      ${metricRows([
        ['Boot ID', reboot.boot_id || '-'],
        ['Uptime', reboot.uptime || '-'],
        ['Boot time', reboot.boot_time || '-'],
        ['Recent reboots', reboot.recent_reboots || '-'],
      ])}
    </div>`,
    `<div class="maintenance-card"><h3>Storage</h3>
      ${metricRows([
        ['Root filesystem', storage.root || '-'],
        ['/var', storage.var || '-'],
        ['/var/lib', storage.var_lib || '-'],
        ['Docker total', docker.total || '-'],
        ['Docker images', docker.images || '-'],
        ['Docker containers', docker.containers_df || docker.containers || '-'],
        ['Docker overlay2', docker.overlay2 || '-'],
        ['Docker volumes', docker.volumes_df || docker.volumes || '-'],
      ])}
    </div>`,
  ].join('');
}
async function loadMaintenance() {
  const grid = document.getElementById('maintenanceGrid');
  grid.innerHTML = '<div class="maintenance-card"><h3>Loading</h3><div class="maintenance-note">Collecting maintenance status...</div></div>';
  try {
    const res = await fetch(`/api/maintenance?_=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderMaintenance(await res.json());
  } catch (error) {
    grid.innerHTML = `<div class="maintenance-card"><h3>Maintenance</h3>${statusLine('bad', 'Unable to load maintenance status')}<div class="maintenance-note">${esc(error.message)}</div></div>`;
  }
}
function renderTimeline(events) {
  const target = document.getElementById('eventTimeline');
  if (!events.length) {
    target.innerHTML = '<div class="maintenance-card"><h3>Quiet</h3><div class="maintenance-note">No notable events in the loaded window.</div></div>';
    return;
  }
  target.innerHTML = events.map(event => {
    const local = formatLocalTime(event.timestamp);
    return `<div class="timeline-item">
      <div class="timeline-time"><strong>${esc(local.main)}</strong><span class="time-sub">${esc(local.sub || '')}</span></div>
      <div><div class="timeline-title">${esc(event.title)}</div><div class="timeline-body">${esc(event.detail || '')}</div></div>
    </div>`;
  }).join('');
}
async function loadTimeline() {
  const target = document.getElementById('eventTimeline');
  target.innerHTML = '<div class="maintenance-card"><h3>Loading</h3><div class="maintenance-note">Collecting recent events...</div></div>';
  try {
    const res = await fetch(`/api/events?limit=${getSelectedLimit()}&_=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderTimeline(await res.json());
  } catch (error) {
    target.innerHTML = `<div class="maintenance-card"><h3>Event Timeline</h3>${statusLine('bad', 'Unable to load event timeline')}<div class="maintenance-note">${esc(error.message)}</div></div>`;
  }
}
function renderAlerts(data) {
  const target = document.getElementById('alertsGrid');
  const alerts = data.alerts || [];
  if (!alerts.length) {
    target.innerHTML = '<div class="alert-card ok"><div class="alert-top"><div class="alert-title">All Clear</div><span class="alert-badge ok">OK</span></div><div class="alert-body">No threshold alerts are active.</div></div>';
    return;
  }
  target.innerHTML = alerts.map(alert => {
    const severity = alert.severity || 'warn';
    return `<div class="alert-card ${esc(severity)}">
      <div class="alert-top"><div class="alert-title">${esc(alert.title)}</div><span class="alert-badge ${esc(severity)}">${esc(alert.label || severity)}</span></div>
      <div class="alert-body">${esc(alert.detail || '')}</div>
    </div>`;
  }).join('');
}
async function loadAlerts() {
  const target = document.getElementById('alertsGrid');
  target.innerHTML = '<div class="maintenance-card"><h3>Loading</h3><div class="maintenance-note">Checking alert thresholds...</div></div>';
  try {
    const res = await fetch(`/api/alerts?_=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderAlerts(await res.json());
  } catch (error) {
    target.innerHTML = `<div class="alert-card bad"><div class="alert-top"><div class="alert-title">Alerts unavailable</div><span class="alert-badge bad">Error</span></div><div class="alert-body">${esc(error.message)}</div></div>`;
  }
}
function renderContainers(data) {
  const target = document.getElementById('containerGrid');
  if (!data.available) {
    target.innerHTML = `<div class="maintenance-card"><h3>Docker</h3>${statusLine('warn', data.reason || 'Docker is not available')}</div>`;
    return;
  }
  if (!data.containers.length) {
    target.innerHTML = '<div class="maintenance-card"><h3>Docker</h3><div class="maintenance-note">No containers found.</div></div>';
    return;
  }
  target.innerHTML = data.containers.map(container => {
    const ok = container.state === 'running';
    return `<div class="container-card">
      <div class="container-top">
        <div><div class="container-name">${esc(container.name)}</div><div class="container-image">${esc(container.image || '-')}</div></div>
        <span class="container-status ${ok ? 'ok' : 'bad'}">${esc(container.state || '-')}</span>
      </div>
      ${metricRows([
        ['Status', container.status || '-'],
        ['CPU', container.cpu || '-'],
        ['Memory', container.memory || '-'],
        ['Restart count', container.restart_count ?? '-'],
      ])}
    </div>`;
  }).join('');
}
async function loadContainers() {
  const target = document.getElementById('containerGrid');
  target.innerHTML = '<div class="maintenance-card"><h3>Loading</h3><div class="maintenance-note">Checking Docker containers...</div></div>';
  try {
    const res = await fetch(`/api/containers?_=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderContainers(await res.json());
  } catch (error) {
    target.innerHTML = `<div class="maintenance-card"><h3>Container Health</h3>${statusLine('bad', 'Unable to load containers')}<div class="maintenance-note">${esc(error.message)}</div></div>`;
  }
}
function speedBytes() {
  return Number(document.getElementById('speedSize').value) * 1024 * 1024;
}
function formatSpeed(bytes, ms) {
  if (!bytes || !ms) return '-';
  return `${speedMbps(bytes, ms).toFixed(1)} Mbps`;
}
function speedMbps(bytes, ms) {
  if (!bytes || !ms) return 0;
  return (bytes * 8) / (ms / 1000) / 1000000;
}
function formatBytes(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}
function setSpeedProgress(done, total) {
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  document.getElementById('speedProgress').style.width = `${pct}%`;
}
function setSpeedButtons(disabled) {
  document.getElementById('speedDownload').disabled = disabled;
  document.getElementById('speedUpload').disabled = disabled;
  document.getElementById('speedSize').disabled = disabled;
  document.getElementById('speedClientLabel').disabled = disabled;
}
function speedClientLabel() {
  const input = document.getElementById('speedClientLabel');
  const label = input.value.trim();
  window.localStorage.setItem('watchdog-speed-label', label);
  return label || 'Unnamed browser';
}
function qualityClass(value) {
  return String(value || '').toLowerCase().replace(/[^a-z]/g, '') || 'ok';
}
async function saveSpeedResult(direction, bytes, elapsedMs) {
  const payload = {
    direction,
    bytes,
    elapsed_ms: elapsedMs,
    mbps: speedMbps(bytes, elapsedMs),
    client_label: speedClientLabel(),
    user_agent: navigator.userAgent,
  };
  const res = await fetch('/api/speed/result', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`history HTTP ${res.status}`);
  await loadSpeedHistory();
}
async function runDownloadSpeedTest() {
  if (speedTestRunning) return;
  speedTestRunning = true;
  setSpeedButtons(true);
  const bytes = speedBytes();
  let received = 0;
  document.getElementById('downloadSpeed').textContent = 'Testing...';
  document.getElementById('downloadDetail').textContent = `Receiving ${formatBytes(bytes)}`;
  setSpeedProgress(0, bytes);
  const start = performance.now();
  try {
    const res = await fetch(`/api/speed/download?bytes=${bytes}&_=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      setSpeedProgress(received, bytes);
    }
    const elapsed = performance.now() - start;
    document.getElementById('downloadSpeed').textContent = formatSpeed(received, elapsed);
    document.getElementById('downloadDetail').textContent = `${formatBytes(received)} in ${(elapsed / 1000).toFixed(2)}s`;
    await saveSpeedResult('download', received, elapsed);
  } catch (error) {
    document.getElementById('downloadSpeed').textContent = 'Failed';
    document.getElementById('downloadDetail').textContent = error.message;
  } finally {
    setSpeedProgress(0, bytes);
    setSpeedButtons(false);
    speedTestRunning = false;
  }
}
async function runUploadSpeedTest() {
  if (speedTestRunning) return;
  speedTestRunning = true;
  setSpeedButtons(true);
  const bytes = speedBytes();
  const chunk = new Uint8Array(1024 * 1024);
  const parts = Array.from({ length: Math.ceil(bytes / chunk.byteLength) }, (_, index) => {
    const remaining = bytes - index * chunk.byteLength;
    return remaining >= chunk.byteLength ? chunk : chunk.slice(0, remaining);
  });
  const body = new Blob(parts);
  document.getElementById('uploadSpeed').textContent = 'Testing...';
  document.getElementById('uploadDetail').textContent = `Sending ${formatBytes(body.size)}`;
  setSpeedProgress(0, body.size);
  const start = performance.now();
  try {
    const res = await fetch(`/api/speed/upload?_=${Date.now()}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body,
    });
    const elapsed = performance.now() - start;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    document.getElementById('uploadSpeed').textContent = formatSpeed(data.bytes || body.size, elapsed);
    document.getElementById('uploadDetail').textContent = `${formatBytes(data.bytes || body.size)} in ${(elapsed / 1000).toFixed(2)}s`;
    await saveSpeedResult('upload', data.bytes || body.size, elapsed);
    setSpeedProgress(body.size, body.size);
  } catch (error) {
    document.getElementById('uploadSpeed').textContent = 'Failed';
    document.getElementById('uploadDetail').textContent = error.message;
  } finally {
    window.setTimeout(() => setSpeedProgress(0, bytes), 300);
    setSpeedButtons(false);
    speedTestRunning = false;
  }
}
function speedHistoryPath(points, width, height, pad, maxValue) {
  if (!points.length) return '';
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  return points.map((point, index) => {
    const x = pad + (points.length === 1 ? innerW / 2 : index / (points.length - 1) * innerW);
    const y = pad + (1 - Math.min(point.mbps, maxValue) / maxValue) * innerH;
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}
function renderSpeedHistory(data) {
  const results = data.results || [];
  const list = document.getElementById('speedHistoryList');
  const svg = document.getElementById('speedHistoryChart');
  if (!results.length) {
    svg.innerHTML = '<text x="24" y="92" font-size="14" fill="#60717d">No speed results yet</text>';
    list.innerHTML = '<div class="maintenance-card"><h3>Network Quality</h3><div class="maintenance-note">Run a download or upload test to start the timeline.</div></div>';
    return;
  }
  const chronological = [...results].reverse();
  const downloads = chronological.filter(item => item.direction === 'download');
  const uploads = chronological.filter(item => item.direction === 'upload');
  const maxValue = Math.max(10, ...chronological.map(item => Number(item.mbps) || 0)) * 1.12;
  svg.innerHTML = `
    <line class="chart-grid" x1="28" y1="28" x2="872" y2="28"></line>
    <line class="chart-grid" x1="28" y1="90" x2="872" y2="90"></line>
    <line class="chart-axis" x1="28" y1="152" x2="872" y2="152"></line>
    <path class="chart-line" stroke="#0a6dff" d="${speedHistoryPath(downloads, 900, 180, 28, maxValue)}"></path>
    <path class="chart-line" stroke="#14b8a6" d="${speedHistoryPath(uploads, 900, 180, 28, maxValue)}"></path>
    <text x="34" y="22" font-size="12" fill="#60717d">${esc(maxValue.toFixed(0))} Mbps</text>
    <text x="34" y="170" font-size="12" fill="#60717d">download blue / upload green</text>
  `;
  list.innerHTML = results.slice(0, 12).map(item => {
    const local = formatLocalTime(item.timestamp);
    const ping = item.ping_avg_ms == null ? 'ping -' : `ping avg ${Number(item.ping_avg_ms).toFixed(1)} ms, max ${item.ping_max_ms == null ? '-' : Number(item.ping_max_ms).toFixed(1)} ms`;
    return `<div class="history-item">
      <div class="timeline-time"><strong>${esc(local.main)}</strong><span class="time-sub">${esc(local.sub || '')}</span></div>
      <div class="history-main">
        <div class="history-title">${esc(item.client_label || 'Unnamed browser')} ${esc(item.direction)} ${Number(item.mbps || 0).toFixed(1)} Mbps</div>
        <div class="history-detail">${esc(item.client_ip || '-')} · ${esc(formatBytes(item.bytes || 0))} · ${esc(ping)}</div>
      </div>
      <span class="quality ${qualityClass(item.quality)}">${esc(item.quality || 'OK')}</span>
    </div>`;
  }).join('');
}
async function loadSpeedHistory() {
  const res = await fetch(`/api/speed/history?_=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  renderSpeedHistory(await res.json());
}
async function clearSpeedHistory() {
  if (!window.confirm('Clear saved speed test history?')) return;
  const res = await fetch('/api/speed/history', { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  await loadSpeedHistory();
}
function seriesRange(values) {
  const nums = values.filter(v => Number.isFinite(v));
  if (!nums.length) return null;
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (min === max) { min -= 1; max += 1; }
  return { min, max };
}
function combinedRange(seriesList) {
  const nums = seriesList.flatMap(series => series.values).filter(v => Number.isFinite(v));
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
function renderChart(title, meta, seriesList, formatter, index, large = false) {
  const width = large ? 1000 : 320;
  const height = large ? 620 : 120;
  const pad = 16;
  const range = combinedRange(seriesList);
  const legend = seriesList.length > 1
    ? `<div class="chart-legend">${seriesList.map(series => `<span class="legend-item"><span class="legend-swatch" style="background:${series.color}"></span>${esc(series.label)}</span>`).join('')}</div>`
    : '';
  const cardClass = large ? 'chart-card' : 'chart-card clickable';
  const dataAttr = large ? '' : ` data-chart="${index}"`;
  const svgClass = large ? 'chart-modal-svg' : 'chart-svg';
  if (!range) return `<div class="${cardClass}"${dataAttr}><div class="chart-head"><div class="chart-title">${esc(title)}</div><div class="chart-meta">${esc(meta)}</div></div>${legend}<div class="chart-empty">No data in this window.</div></div>`;
  const lines = seriesList.map(series => {
    const { path, dots } = linePath(series.values, width, height, pad, range);
    return `<path class="chart-line" stroke="${series.color}" d="${path}"></path><g fill="${series.color}">${dots}</g>`;
  }).join('');
  const top = formatter(range.max);
  const bottom = formatter(range.min);
  const latestParts = seriesList.map(series => {
    const latest = series.values.filter(v => Number.isFinite(v)).slice(-1)[0];
    return `${series.label} ${formatter(latest)}`;
  });
  const focusDots = seriesList.map(series => `<circle class="chart-focus-dot" data-focus-dot="${esc(series.label)}" r="${large ? 5 : 4}" fill="${series.color}" visibility="hidden"></circle>`).join('');
  return `<div class="${cardClass}"${dataAttr}><div class="chart-head"><div class="chart-title">${esc(title)}</div><div class="chart-meta">${esc(meta)} · latest ${esc(latestParts.join(' · '))}</div></div>${legend}<svg class="${svgClass}" data-chart-svg="${index}" data-chart-large="${large ? '1' : '0'}" data-chart-width="${width}" data-chart-height="${height}" data-chart-pad="${pad}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="${esc(title)} trend"><line class="chart-grid" x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}"></line><line class="chart-grid" x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}"></line><line class="chart-axis" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line>${lines}<line class="chart-focus-line" x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" visibility="hidden"></line>${focusDots}<text x="${pad}" y="12" font-size="11" fill="#5b6b76">${esc(top)}</text><text x="${pad}" y="${height - 2}" font-size="11" fill="#5b6b76">${esc(bottom)}</text></svg><div class="chart-tooltip" hidden></div></div>`;
}
function renderCharts() {
  chartDefinitions = [
    ['Disk Usage', 'root filesystem', [{ label: 'root', values: snapshots.map(s => s.root_use_pct), color: '#0057b8' }], v => `${v.toFixed(0)}%`],
    ['CPU Load', '1, 5, 15 minute load', [
      { label: '1m', values: snapshots.map(s => s.load_1), color: '#b85c00' },
      { label: '5m', values: snapshots.map(s => s.load_5), color: '#0a6dff' },
      { label: '15m', values: snapshots.map(s => s.load_15), color: '#14b8a6' },
    ], v => v.toFixed(2)],
    ['Memory Used', 'RAM in use', [{ label: 'used', values: snapshots.map(s => s.mem_used_pct), color: '#18794e' }], v => `${v.toFixed(0)}%`],
    ['Temperature', 'max thermal zone', [{ label: 'temp', values: snapshots.map(s => s.temp_max_c), color: '#c0362c' }], v => `${v.toFixed(1)} C`],
    ['Ping Latency', 'gateway RTT', [{ label: 'ping', values: snapshots.map(s => s.ping_avg_ms), color: '#7a3cff' }], v => `${v.toFixed(1)} ms`],
  ];
  document.getElementById('charts').innerHTML = chartDefinitions.map(([title, meta, seriesList, formatter], index) => renderChart(title, meta, seriesList, formatter, index)).join('');
  bindChartTooltips();
  document.querySelectorAll('.chart-card.clickable[data-chart]').forEach(card => card.onclick = () => openChartModal(Number(card.dataset.chart)));
}
function openChartModal(index) {
  const [title, meta, seriesList, formatter] = chartDefinitions[index];
  document.getElementById('chartModalTitle').textContent = title;
  document.getElementById('chartModalMeta').textContent = meta;
  document.getElementById('chartModalLegend').innerHTML = seriesList.length > 1
    ? seriesList.map(series => `<span class="legend-item"><span class="legend-swatch" style="background:${series.color}"></span>${esc(series.label)}</span>`).join('')
    : '';
  document.getElementById('chartModalContent').innerHTML = renderChart(title, meta, seriesList, formatter, index, true);
  bindChartTooltips(document.getElementById('chartModalContent'));
  document.getElementById('chartModal').showModal();
}
function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}
function buildChartTooltip(index, pointIndex) {
  const [, , seriesList, formatter] = chartDefinitions[index];
  const snapshot = snapshots[pointIndex];
  const local = snapshot ? formatLocalTime(snapshot.timestamp) : { main: `Point ${pointIndex + 1}`, sub: '' };
  const rows = seriesList.map(series => {
    const value = series.values[pointIndex];
    return `<div class="chart-tooltip-row"><span class="chart-tooltip-label"><span class="chart-tooltip-swatch" style="background:${series.color}"></span>${esc(series.label)}</span><span class="chart-tooltip-value">${esc(Number.isFinite(value) ? formatter(value) : '-')}</span></div>`;
  }).join('');
  return `<div class="chart-tooltip-time">${esc(local.main)}</div>${rows}`;
}
function bindChartTooltips(root = document) {
  root.querySelectorAll('svg[data-chart-svg]').forEach(svg => {
    const card = svg.closest('.chart-card');
    const tooltip = card ? card.querySelector('.chart-tooltip') : null;
    const focusLine = svg.querySelector('.chart-focus-line');
    const focusDots = [...svg.querySelectorAll('.chart-focus-dot')];
    if (!card || !tooltip || !focusLine) return;
    const index = Number(svg.dataset.chartSvg);
    const width = Number(svg.dataset.chartWidth);
    const height = Number(svg.dataset.chartHeight);
    const pad = Number(svg.dataset.chartPad);
    const updateTooltip = clientX => {
      const [, , seriesList] = chartDefinitions[index];
      const range = combinedRange(seriesList);
      if (!range || !snapshots.length) return;
      const rect = svg.getBoundingClientRect();
      const innerW = width - pad * 2;
      const innerH = height - pad * 2;
      const xRatio = clamp((clientX - rect.left) / rect.width, 0, 1);
      const pointIndex = snapshots.length === 1 ? 0 : clamp(Math.round(xRatio * (snapshots.length - 1)), 0, snapshots.length - 1);
      const focusX = pad + (snapshots.length === 1 ? innerW / 2 : (pointIndex / (snapshots.length - 1)) * innerW);
      focusLine.setAttribute('x1', focusX.toFixed(1));
      focusLine.setAttribute('x2', focusX.toFixed(1));
      focusLine.setAttribute('visibility', 'visible');
      tooltip.hidden = false;
      tooltip.innerHTML = buildChartTooltip(index, pointIndex);
      const cardRect = card.getBoundingClientRect();
      const tooltipLeft = clamp((clientX - cardRect.left), 86, cardRect.width - 86);
      tooltip.style.left = `${tooltipLeft}px`;
      tooltip.style.top = `${clamp(rect.top - cardRect.top + 14, 14, Math.max(14, cardRect.height - 72))}px`;
      focusDots.forEach((dot, seriesIndex) => {
        const value = chartDefinitions[index][2][seriesIndex].values[pointIndex];
        if (!Number.isFinite(value)) {
          dot.setAttribute('visibility', 'hidden');
          return;
        }
        const y = pad + (1 - ((value - range.min) / (range.max - range.min))) * innerH;
        dot.setAttribute('cx', focusX.toFixed(1));
        dot.setAttribute('cy', y.toFixed(1));
        dot.setAttribute('visibility', 'visible');
      });
    };
    const clearTooltip = () => {
      tooltip.hidden = true;
      focusLine.setAttribute('visibility', 'hidden');
      focusDots.forEach(dot => dot.setAttribute('visibility', 'hidden'));
    };
    svg.onmousemove = event => updateTooltip(event.clientX);
    svg.onmouseleave = clearTooltip;
    svg.ontouchstart = event => {
      if (event.touches[0]) updateTooltip(event.touches[0].clientX);
    };
    svg.ontouchmove = event => {
      if (event.touches[0]) updateTooltip(event.touches[0].clientX);
    };
    svg.ontouchend = clearTooltip;
  });
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
  return `<tr class="${(s.ping_status !== 'ok' || s.dns_status !== 'ok') ? 'fail' : ''}"><td data-label="Timestamp"><div>${esc(local.main)}</div><span class="time-sub">${esc(local.sub || '-')}</span></td><td data-label="Ping">${pill(s.ping_status === 'ok' ? 'ok' : 'bad', s.ping_status)}</td><td data-label="DNS">${pill(s.dns_status === 'ok' ? 'ok' : 'bad', s.dns_status)}</td><td data-label="Kernel">${kernelPill(s)}</td><td data-label="Root Use">${esc(s.root_use || '-')}</td><td data-label="Temp Max">${s.temp_max_c == null ? '-' : s.temp_max_c.toFixed(1) + ' C'}</td><td data-label="Notes">${esc(rowNotes(s))}</td><td data-label="Inspect"><button class="inspect-btn" data-i="${index}" type="button">Inspect</button></td></tr>`;
}
function bindRowButtons(filtered) {
  document.querySelectorAll('button[data-i]').forEach(btn => btn.onclick = async () => {
    const s = filtered[Number(btn.dataset.i)];
    document.getElementById('modalTitle').textContent = s.timestamp;
    setMode('readable');
    document.getElementById('raw').textContent = 'Loading...';
    document.getElementById('readableView').innerHTML = '<div class="readable-card"><h3 class="readable-title">Loading</h3><pre class="readable-pre">Preparing snapshot overview...</pre></div>';
    document.getElementById('modal').showModal();
    const raw = await loadRaw(s.id);
    document.getElementById('raw').textContent = raw;
    document.getElementById('readableView').innerHTML = renderReadable(raw, s);
  });
}
function setMode(mode) {
  const raw = document.getElementById('raw');
  const readable = document.getElementById('readableView');
  const rawBtn = document.getElementById('modeRaw');
  const readableBtn = document.getElementById('modeReadable');
  const showRaw = mode === 'raw';
  raw.hidden = !showRaw;
  readable.hidden = showRaw;
  rawBtn.classList.toggle('active', showRaw);
  readableBtn.classList.toggle('active', !showRaw);
}
function parseSections(raw) {
  const sections = [];
  let current = null;
  raw.split('\\n').forEach(line => {
    if (line.startsWith('=== ')) {
      sections.push({ title: 'Snapshot', body: line.replace(/^===\\s*/, '').replace(/\\s*===$/, '').trim() });
      current = null;
      return;
    }
    const match = line.match(/^--\\s(.+)\\s--$/);
    if (match) {
      current = { title: match[1], lines: [] };
      sections.push(current);
      return;
    }
    if (current) current.lines.push(line);
  });
  return sections.map(section => ({
    title: section.title,
    body: Array.isArray(section.lines) ? section.lines.join('\\n').trim() : section.body,
  }));
}
function formatMetricValue(value, digits = 2, suffix = '') {
  if (value == null || value === '') return '-';
  return `${Number(value).toFixed(digits)}${suffix}`;
}
function formatCpuLoads(snapshot) {
  return [snapshot.load_1, snapshot.load_5, snapshot.load_15].map(value => formatMetricValue(value)).join(' / ');
}
function renderOverview(snapshot) {
  return `<div class="readable-overview">
    <div class="overview-card"><div class="overview-label">Recorded</div><div class="overview-value">${esc(formatLocalTime(snapshot.timestamp).main)}</div></div>
    <div class="overview-card"><div class="overview-label">Network</div><div class="overview-value">${esc(snapshot.ping_status)} ping / ${esc(snapshot.dns_status)} dns</div></div>
    <div class="overview-card"><div class="overview-label">CPU Load</div><div class="overview-value">${esc(formatCpuLoads(snapshot))}</div></div>
    <div class="overview-card"><div class="overview-label">Memory</div><div class="overview-value">${snapshot.mem_used_pct == null ? '-' : snapshot.mem_used_pct.toFixed(1) + '%'}</div></div>
    <div class="overview-card"><div class="overview-label">Root Disk</div><div class="overview-value">${esc(snapshot.root_use || '-')}</div></div>
    <div class="overview-card"><div class="overview-label">Temperature</div><div class="overview-value">${snapshot.temp_max_c == null ? '-' : snapshot.temp_max_c.toFixed(1) + ' C'}</div></div>
  </div>`;
}
function tryRenderKeyValue(lines) {
  const pairs = lines.map(line => {
    const kvMatch = line.match(/^([^:=]{2,80})[:=]\\s*(.+)$/);
    if (kvMatch) return { key: kvMatch[1].trim(), value: kvMatch[2].trim() };
    const memMatch = line.match(/^(Mem|Swap):\\s+(.+)$/);
    if (memMatch) return { key: memMatch[1], value: memMatch[2].trim() };
    return null;
  });
  if (pairs.some(pair => pair === null)) return '';
  return `<div class="readable-grid">${pairs.map(pair => `<div class="readable-item"><strong>${esc(pair.key)}</strong><span>${esc(pair.value)}</span></div>`).join('')}</div>`;
}
function renderSectionBody(section) {
  const body = (section.body || '').trim();
  if (!body) return '<div class="readable-empty">No data</div>';
  const lines = body.split('\\n').map(line => line.trimEnd()).filter(Boolean);
  const grid = tryRenderKeyValue(lines);
  if (grid) return grid;
  if (lines.length <= 8 && lines.every(line => line.length < 180)) {
    return `<div class="readable-list">${lines.map(line => `<div class="readable-list-item">${esc(line)}</div>`).join('')}</div>`;
  }
  return `<pre class="readable-pre">${esc(body)}</pre>`;
}
function renderReadable(raw, snapshot) {
  const sections = parseSections(raw);
  return `${renderOverview(snapshot)}${sections.map(section => `<div class="readable-card"><h3 class="readable-title">${esc(section.title)}</h3>${renderSectionBody(section)}</div>`).join('')}`;
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
function setLoadingState(active) {
  const status = document.getElementById('loadingStatus');
  status.classList.toggle('active', active);
  status.setAttribute('aria-hidden', active ? 'false' : 'true');
  ['limit', 'reload'].forEach(id => {
    document.getElementById(id).disabled = active;
  });
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
  setLoadingState(true);
  try {
    const limit = getSelectedLimit();
    document.getElementById('hint').textContent = `Loading ${document.getElementById('limit').selectedOptions[0].textContent}...`;
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
  } catch (error) {
    document.getElementById('hint').textContent = `Load failed: ${error.message}`;
  } finally {
    isLoading = false;
    setLoadingState(false);
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
document.getElementById('speedClientLabel').value = window.localStorage.getItem('watchdog-speed-label') || '';

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
document.getElementById('speedDownload').addEventListener('click', runDownloadSpeedTest);
document.getElementById('speedUpload').addEventListener('click', runUploadSpeedTest);
document.getElementById('speedClientLabel').addEventListener('change', event => {
  window.localStorage.setItem('watchdog-speed-label', event.target.value.trim());
});
document.getElementById('speedHistoryRefresh').addEventListener('click', loadSpeedHistory);
document.getElementById('speedClear').addEventListener('click', clearSpeedHistory);
document.getElementById('maintenanceRefresh').addEventListener('click', loadMaintenance);
document.getElementById('timelineRefresh').addEventListener('click', loadTimeline);
document.getElementById('alertsRefresh').addEventListener('click', loadAlerts);
document.getElementById('containerRefresh').addEventListener('click', loadContainers);
document.getElementById('modeReadable').addEventListener('click', () => setMode('readable'));
document.getElementById('modeRaw').addEventListener('click', () => setMode('raw'));
['modal', 'chartModal'].forEach(id => {
  const dialog = document.getElementById(id);
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
});
if (window.localStorage.getItem('watchdog-autoload') === 'on') startAutoLoad();
updateSortButton();
updateAutoLoadButton();
setMode('readable');
load();
loadSpeedHistory();
loadMaintenance();
loadTimeline();
loadAlerts();
loadContainers();
</script>
</body>
</html>
"""

KERNEL_PATTERN = re.compile(r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})")
INTERESTING_KERNEL_WORDS = ("brcmf", "failed", "reset", "oom", "no buffer space", "mmc", "ext4")
SIZE_UNITS = {
    "B": 1,
    "Ki": 1024,
    "Mi": 1024 ** 2,
    "Gi": 1024 ** 3,
    "Ti": 1024 ** 4,
}


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


def parse_size_to_bytes(value: str, unit: str):
    factor = SIZE_UNITS.get(unit)
    if factor is None:
        return None
    return float(value) * factor


def run_cmd(args: list[str], timeout: float = 3.0):
    if shutil.which(args[0]) is None:
        return ""
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip()


def path_size(path: str):
    target = Path(path)
    try:
        exists = target.exists()
    except OSError:
        exists = False
    if not exists:
        return "-"
    output = run_cmd(["du", "-sh", path], timeout=5.0)
    if output:
        return output.split()[0]
    try:
        return human_bytes(target.stat().st_size)
    except OSError:
        return "-"


def human_bytes(value: int | float | None):
    if value is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


def parse_docker_size(text: str):
    match = re.match(r"^([0-9.]+)\s*([KMGT]?B)$", text.strip(), re.I)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    factors = {"B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4}
    return value * factors.get(unit, 1)


def parse_docker_system_df(text: str):
    parsed = {}
    total = 0
    labels = {
        "Images": "images",
        "Containers": "containers_df",
        "Local Volumes": "volumes_df",
        "Build Cache": "build_cache",
    }
    for line in text.splitlines():
        for prefix, key in labels.items():
            if not line.startswith(prefix):
                continue
            columns = re.split(r"\s{2,}", line.strip())
            if len(columns) >= 4:
                parsed[key] = columns[3]
                size = parse_docker_size(columns[3])
                if size:
                    total += size
    if total:
        parsed["total"] = human_bytes(total)
    return parsed


def first_line(text: str):
    return text.splitlines()[0].strip() if text.strip() else ""


def docker_json_log_summary():
    base = Path("/var/lib/docker/containers")
    try:
        if not base.exists():
            return "-"
    except OSError:
        return "-"
    largest = None
    try:
        for path in base.glob("*/*-json.log"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if largest is None or size > largest[0]:
                largest = (size, path)
    except OSError:
        return "-"
    if largest is None:
        return "0 B"
    container = largest[1].parent.name[:12]
    return f"{human_bytes(largest[0])} ({container})"


def docker_storage_summary():
    root = Path("/var/lib/docker")
    data = {
        "total": path_size("/var/lib/docker"),
        "overlay2": path_size("/var/lib/docker/overlay2"),
        "volumes": path_size("/var/lib/docker/volumes"),
        "containers": path_size("/var/lib/docker/containers"),
    }
    df = run_cmd(["docker", "system", "df"], timeout=6.0)
    if df:
        data["system_df"] = "available"
        data.update(parse_docker_system_df(df))
    else:
        try:
            data["system_df"] = "limited" if root.exists() else "not installed"
        except OSError:
            data["system_df"] = "limited"
    return data


def latest_ping_context():
    snaps = load_snapshots()
    for snap in reversed(snaps):
        if snap.get("ping_avg_ms") is not None or snap.get("ping_max_ms") is not None:
            return {
                "ping_avg_ms": snap.get("ping_avg_ms"),
                "ping_max_ms": snap.get("ping_max_ms"),
                "ping_status": snap.get("ping_status"),
                "snapshot_timestamp": snap.get("timestamp"),
            }
    return {"ping_avg_ms": None, "ping_max_ms": None, "ping_status": None, "snapshot_timestamp": None}


def speed_quality(mbps: float, ping_avg_ms: float | None, ping_max_ms: float | None):
    if ping_max_ms is not None and ping_max_ms >= 300:
        return "Unstable"
    if mbps >= 300 and (ping_avg_ms is None or ping_avg_ms < 50):
        return "Excellent"
    if mbps >= 80 and (ping_avg_ms is None or ping_avg_ms < 120):
        return "OK"
    if mbps >= 20:
        return "Slow"
    return "Unstable"


def read_speed_history(limit: int = 300):
    if not SPEED_HISTORY_PATH.exists():
        return []
    rows = []
    try:
        lines = SPEED_HISTORY_PATH.read_text(errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return rows


def append_speed_result(data: dict, client_ip: str):
    ping = latest_ping_context()
    mbps = float(data.get("mbps") or 0)
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "direction": str(data.get("direction") or "unknown")[:20],
        "bytes": int(data.get("bytes") or 0),
        "elapsed_ms": float(data.get("elapsed_ms") or 0),
        "mbps": mbps,
        "client_label": str(data.get("client_label") or "Unnamed browser")[:80],
        "client_ip": client_ip,
        "user_agent": str(data.get("user_agent") or "")[:240],
        "ping_avg_ms": ping["ping_avg_ms"],
        "ping_max_ms": ping["ping_max_ms"],
        "ping_status": ping["ping_status"],
        "ping_snapshot": ping["snapshot_timestamp"],
    }
    record["quality"] = speed_quality(mbps, record["ping_avg_ms"], record["ping_max_ms"])
    SPEED_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SPEED_HISTORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def clear_speed_history():
    SPEED_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEED_HISTORY_PATH.write_text("", encoding="utf-8")


def snapshot_events(limit: int):
    snaps = load_snapshots()
    if limit:
        snaps = snaps[-limit:]
    events = []
    previous = None
    for snap in snaps:
        timestamp = snap["timestamp"]
        if snap["ping_status"] != "ok":
            events.append({
                "timestamp": timestamp,
                "kind": "network",
                "title": "Gateway ping failure",
                "detail": "The watchdog could not reach the default gateway.",
            })
        elif snap["ping_avg_ms"] is not None and snap["ping_avg_ms"] >= 100:
            events.append({
                "timestamp": timestamp,
                "kind": "network",
                "title": "High gateway latency",
                "detail": f"Average ping was {snap['ping_avg_ms']:.1f} ms.",
            })
        if snap["dns_status"] != "ok":
            events.append({
                "timestamp": timestamp,
                "kind": "dns",
                "title": "DNS check failed",
                "detail": "One or more DNS probes failed.",
            })
        if snap["kernel_status"] == "actionable":
            detail = " | ".join(snap["kernel_hits"][:2]) if snap["kernel_hits"] else "Recent kernel warning needs attention."
            events.append({
                "timestamp": timestamp,
                "kind": "kernel",
                "title": "Kernel warning",
                "detail": detail,
            })
        if snap["failure_diagnostics"]:
            events.append({
                "timestamp": timestamp,
                "kind": "diagnostics",
                "title": "Failure diagnostics captured",
                "detail": "The watchdog saved extra network diagnostics for this snapshot.",
            })
        current_ts = parse_snapshot_ts(timestamp)
        previous_ts = parse_snapshot_ts(previous["timestamp"]) if previous else None
        if current_ts and previous_ts:
            gap = (current_ts - previous_ts).total_seconds()
            if gap > 180:
                events.append({
                    "timestamp": timestamp,
                    "kind": "gap",
                    "title": "Watchdog gap",
                    "detail": f"No snapshot was recorded for about {int(gap // 60)} minutes.",
                })
            if current_ts < previous_ts:
                events.append({
                    "timestamp": timestamp,
                    "kind": "reboot",
                    "title": "Timestamp moved backward",
                    "detail": "Snapshot ordering suggests a clock or boot-time discontinuity.",
                })
        previous = snap
    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events[:80]


def parse_json_lines(text: str):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def container_health():
    if shutil.which("docker") is None:
        return {"available": False, "reason": "Docker command not found", "containers": []}
    ps_output = run_cmd([
        "docker", "ps", "-a", "--no-trunc",
        "--format", "{{json .}}",
    ], timeout=6.0)
    if not ps_output:
        return {"available": False, "reason": "Docker is unavailable or permission-limited", "containers": []}
    stats_output = run_cmd([
        "docker", "stats", "--no-stream", "--format", "{{json .}}",
    ], timeout=8.0)
    stats_by_name = {}
    for row in parse_json_lines(stats_output):
        name = row.get("Name") or row.get("Container")
        if name:
            stats_by_name[name] = row
    inspect_rows = parse_json_lines(run_cmd([
        "docker", "inspect", "--format", "{{json .}}",
        *[row.get("ID", "") for row in parse_json_lines(ps_output) if row.get("ID")],
    ], timeout=8.0))
    restarts_by_id = {
        row.get("Id", "")[:12]: row.get("RestartCount", 0)
        for row in inspect_rows
    }
    containers = []
    for row in parse_json_lines(ps_output):
        name = row.get("Names") or row.get("Name") or row.get("ID", "")[:12]
        stats = stats_by_name.get(name, {})
        container_id = row.get("ID", "")
        containers.append({
            "id": container_id[:12],
            "name": name,
            "image": row.get("Image", ""),
            "state": (row.get("State", "") or "").lower(),
            "status": row.get("Status", ""),
            "cpu": stats.get("CPUPerc", ""),
            "memory": stats.get("MemUsage", ""),
            "restart_count": restarts_by_id.get(container_id[:12], "-"),
        })
    containers.sort(key=lambda item: (item["state"] != "running", item["name"]))
    return {"available": True, "containers": containers}


def trailing_failures(snaps: list[dict], key: str):
    count = 0
    for snap in reversed(snaps):
        if snap.get(key) != "ok":
            count += 1
        else:
            break
    return count


def alert_status():
    snaps = load_snapshots()
    latest = snaps[-1] if snaps else {}
    alerts = []

    disk_pct = latest.get("root_use_pct")
    if disk_pct is not None and disk_pct >= 80:
        alerts.append({
            "severity": "bad" if disk_pct >= 90 else "warn",
            "label": f"{disk_pct:.0f}%",
            "title": "Disk usage high",
            "detail": f"Root filesystem is at {disk_pct:.0f}% used.",
        })

    temp = latest.get("temp_max_c")
    if temp is not None and temp >= 70:
        alerts.append({
            "severity": "bad" if temp >= 80 else "warn",
            "label": f"{temp:.1f} C",
            "title": "Temperature high",
            "detail": "Latest watchdog snapshot is above the configured temperature threshold.",
        })

    dns_streak = trailing_failures(snaps, "dns_status")
    if dns_streak >= 5:
        alerts.append({
            "severity": "bad",
            "label": f"{dns_streak} checks",
            "title": "DNS failing",
            "detail": "DNS has failed for at least five consecutive watchdog snapshots.",
        })

    ping_streak = trailing_failures(snaps, "ping_status")
    if ping_streak >= 5:
        alerts.append({
            "severity": "bad",
            "label": f"{ping_streak} checks",
            "title": "Gateway ping failing",
            "detail": "Gateway ping has failed for at least five consecutive watchdog snapshots.",
        })

    containers = container_health()
    if containers.get("available"):
        stopped = [item for item in containers.get("containers", []) if item.get("state") != "running"]
        for item in stopped[:6]:
            alerts.append({
                "severity": "bad",
                "label": item.get("state") or "down",
                "title": f"Container down: {item.get('name')}",
                "detail": item.get("status") or item.get("image") or "Container is not running.",
            })

    return {
        "ok": not alerts,
        "checked_snapshot": latest.get("timestamp"),
        "thresholds": {
            "disk_pct": 80,
            "temp_c": 70,
            "dns_failed_snapshots": 5,
            "ping_failed_snapshots": 5,
        },
        "alerts": alerts,
    }


def maintenance_status():
    boot_id = "-"
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()[:12]
    except OSError:
        pass

    uptime_text = first_line(run_cmd(["uptime", "-p"])) or first_line(run_cmd(["uptime"]))
    boot_time = first_line(run_cmd(["who", "-b"]))
    recent_reboots = run_cmd(["last", "-x", "reboot", "-n", "3"], timeout=4.0)
    recent_reboots = " | ".join(line.strip() for line in recent_reboots.splitlines()[:3] if line.strip()) or "-"

    docker_daemon_rotation = False
    docker_daemon_json = Path("/etc/docker/daemon.json")
    try:
        docker_daemon_rotation = "max-size" in docker_daemon_json.read_text(errors="ignore")
    except OSError:
        docker_daemon_rotation = False

    docker_logrotate_path = "/etc/logrotate.d/docker-container-json"
    docker_logrotate = Path(docker_logrotate_path).exists()
    journal_usage = first_line(run_cmd(["journalctl", "--disk-usage"], timeout=4.0)).replace("Archived and active journals take up ", "")

    statvfs = os.statvfs("/")
    total = statvfs.f_blocks * statvfs.f_frsize
    available = statvfs.f_bavail * statvfs.f_frsize
    used = total - available
    root = f"{human_bytes(used)} used / {human_bytes(total)} ({(used / total * 100):.0f}%)" if total else "-"

    return {
        "rotation": {
            "docker_logrotate": docker_logrotate,
            "docker_logrotate_path": docker_logrotate_path if docker_logrotate else "-",
            "docker_daemon_rotation": docker_daemon_rotation,
            "journal_usage": journal_usage or "-",
            "watchdog_log_size": path_size(str(LOG_PATH)),
        },
        "cleanup": {
            "apt_cache": path_size("/var/cache/apt"),
            "apt_lists": path_size("/var/lib/apt/lists"),
            "largest_docker_log": docker_json_log_summary(),
            "wtmp": path_size("/var/log/wtmp"),
            "note": "Small values here usually mean cleanup and rotation are under control.",
        },
        "reboot": {
            "boot_id": boot_id,
            "uptime": uptime_text or "-",
            "boot_time": boot_time or "-",
            "recent_reboots": recent_reboots,
        },
        "storage": {
            "root": root,
            "var": path_size("/var"),
            "var_lib": path_size("/var/lib"),
            "docker": docker_storage_summary(),
        },
    }


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
    load_5 = None
    load_15 = None
    match = re.search(r"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+\d+/\d+\s+\d+", load_section)
    if match:
        load_1 = float(match.group(1))
        load_5 = float(match.group(2))
        load_15 = float(match.group(3))

    mem_used_pct = None
    match = re.search(r"Mem:\s+([0-9.]+)([KMGT]?i|B)\s+([0-9.]+)([KMGT]?i|B)", memory_section)
    if match:
        total = parse_size_to_bytes(match.group(1), match.group(2))
        used = parse_size_to_bytes(match.group(3), match.group(4))
        if total and used is not None and total > 0:
            mem_used_pct = used / total * 100

    temps = [int(x) / 1000 for x in re.findall(r"thermal_zone\d+/temp=(\d+)", raw)]

    ping_avg_ms = None
    ping_max_ms = None
    match = re.search(r"rtt min/avg/max/mdev = ([0-9.]+)/([0-9.]+)/([0-9.]+)/", ping_section)
    if match:
        ping_avg_ms = float(match.group(2))
        ping_max_ms = float(match.group(3))

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
        "ping_max_ms": ping_max_ms,
        "dns_status": dns_status,
        "root_use": root_use,
        "root_use_pct": root_use_pct,
        "load_1": load_1,
        "load_5": load_5,
        "load_15": load_15,
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


def requested_snapshot_limit(qs: dict, default: int = DEFAULT_SNAPSHOT_LIMIT):
    try:
        limit = int(qs.get("limit", [str(default)])[0])
    except (TypeError, ValueError):
        limit = default
    if limit <= 0:
        return MAX_SNAPSHOT_LIMIT
    return min(limit, MAX_SNAPSHOT_LIMIT)


def snapshot_brief(snapshot: dict):
    return {
        "id": snapshot["id"],
        "timestamp": snapshot["timestamp"],
        "ping_status": snapshot["ping_status"],
        "ping_avg_ms": snapshot["ping_avg_ms"],
        "ping_max_ms": snapshot["ping_max_ms"],
        "dns_status": snapshot["dns_status"],
        "root_use": snapshot["root_use"],
        "root_use_pct": snapshot["root_use_pct"],
        "load_1": snapshot["load_1"],
        "load_5": snapshot["load_5"],
        "load_15": snapshot["load_15"],
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

    def _speed_bytes(self, parsed):
        qs = parse_qs(parsed.query)
        try:
            requested = int(qs.get("bytes", [32 * 1024 * 1024])[0])
        except ValueError:
            requested = 32 * 1024 * 1024
        return max(1024 * 1024, min(requested, MAX_SPEED_BYTES))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._html(HTML)
        if parsed.path == "/api/speed/download":
            total = self._speed_bytes(parsed)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(total))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            remaining = total
            while remaining > 0:
                chunk = SPEED_CHUNK if remaining >= len(SPEED_CHUNK) else SPEED_CHUNK[:remaining]
                self.wfile.write(chunk)
                remaining -= len(chunk)
            return
        if parsed.path == "/api/speed/history":
            return self._json({"results": read_speed_history()})
        if parsed.path == "/api/speed/history/export":
            data = json.dumps(read_speed_history(limit=10000), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=pi-watchdog-speed-history.json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/snapshots":
            qs = parse_qs(parsed.query)
            limit = requested_snapshot_limit(qs)
            snaps = load_snapshots()
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
            limit = requested_snapshot_limit(qs, SUMMARY_WINDOW)
            snaps = load_snapshots()
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
        if parsed.path == "/api/maintenance":
            return self._json(maintenance_status())
        if parsed.path == "/api/events":
            qs = parse_qs(parsed.query)
            limit = requested_snapshot_limit(qs, SUMMARY_WINDOW)
            return self._json(snapshot_events(limit))
        if parsed.path == "/api/alerts":
            return self._json(alert_status())
        if parsed.path == "/api/containers":
            return self._json(container_health())
        return self._json({"error": "not found"}, 404)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/speed/download":
            self.send_response(404)
            self.end_headers()
            return
        total = self._speed_bytes(parsed)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(total))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/speed/result":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length > 64 * 1024:
                return self._json({"error": "payload too large"}, 413)
            try:
                payload = json.loads(self.rfile.read(length).decode() if length else "{}")
            except json.JSONDecodeError:
                return self._json({"error": "invalid json"}, 400)
            return self._json(append_speed_result(payload, self.client_address[0]))
        if parsed.path != "/api/speed/upload":
            return self._json({"error": "not found"}, 404)
        try:
            remaining = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            remaining = 0
        if remaining > MAX_SPEED_BYTES:
            return self._json({"error": "upload too large"}, 413)
        received = 0
        started = monotonic()
        while remaining > 0:
            chunk = self.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            received += len(chunk)
            remaining -= len(chunk)
        elapsed = monotonic() - started
        return self._json({"bytes": received, "server_seconds": elapsed})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/speed/history":
            return self._json({"error": "not found"}, 404)
        clear_speed_history()
        return self._json({"ok": True})

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
