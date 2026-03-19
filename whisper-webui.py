#!/usr/bin/env python3
"""
whisper-webui.py — Web Management Interface for whisper_from_sssDeMoNsss
(Veb-interfeys upravleniya proyektom whisper_from_sssDeMoNsss)

Runs on http://localhost:8765
No external dependencies — uses only Python standard library + already installed packages.

Author: sssDeMoNsss | vk.com/basset2
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

PORT        = 8765
LOG_DIR     = Path("C:/whisper-ptt/logs")          # единственная папка для всех логов
LOG_FILE    = LOG_DIR / "whisper-server.log"
PTT_LOG     = LOG_DIR / "whisper-ptt.log"
PTT_ENG_LOG = LOG_DIR / "whisper-ptt-eng.log"
WEBUI_LOG   = LOG_DIR / "whisper-webui.log"
CONFIG_DIRS = [
    Path("C:/whisper-ptt"),
    Path("C:/whisper-ptt-haos"),
    Path("C:/whisper-ptt-eng"),
    Path("C:/whisper-server"),
]
GPU_CONFIG  = Path("C:/whisper-server/gpu-config.json")
CORRECTIONS_FILE = Path("C:/whisper-ptt/corrections.json")

# ── Resolve WhisperServer port dynamically ─────────────────────────────────────
# Collects all candidate ports from config files, then probes each one with a
# real HTTP request to /health.  The first port that responds wins.
# This fixes the case where gpu-config.json has a stale port (e.g. 9000) while
# the server actually runs on a different port (e.g. 9200).
def _probe_port(port: int) -> bool:
    """Return True if whisper-server responds on this port."""
    try:
        import urllib.request as _ur
        r = _ur.urlopen(f"http://localhost:{port}/health", timeout=2)
        return r.status == 200
    except Exception:
        return False

def _collect_candidate_ports() -> list:
    """Gather all port numbers mentioned in config files, most-specific first."""
    import re as _re2
    candidates = []
    # 1. gpu-config.json (installer writes this)
    if GPU_CONFIG.exists():
        try:
            cfg = json.loads(GPU_CONFIG.read_text(encoding="utf-8"))
            p = int(cfg.get("port", 0))
            if 1024 <= p <= 65535:
                candidates.append(p)
        except Exception:
            pass
    # 2. config.toml [remote] url  (ptt client knows the real server port)
    for d in CONFIG_DIRS:
        toml_path = d / "config.toml"
        if toml_path.exists():
            try:
                raw = toml_path.read_text(encoding="utf-8", errors="replace")
                for m in _re2.finditer(r'url\s*=\s*"http://[^:]+:(\d+)"', raw):
                    p = int(m.group(1))
                    if 1024 <= p <= 65535 and p not in candidates:
                        candidates.append(p)
            except Exception:
                pass
    # 3. Fallback defaults
    for p in (9000, 9200, 9100, 9300):
        if p not in candidates:
            candidates.append(p)
    return candidates

def _resolve_server_port() -> int:
    for p in _collect_candidate_ports():
        if _probe_port(p):
            return p
    # Nothing responded — return first candidate so UI shows correct port at least
    cands = _collect_candidate_ports()
    return cands[0] if cands else 9000

_SERVER_PORT = _resolve_server_port()
SERVER_URL   = f"http://localhost:{_SERVER_PORT}"

# ── Statistics ────────────────────────────────────────────────────────────────
# JSON-файл со статистикой слов
PTT_LOG_FILE  = LOG_DIR / "whisper-ptt.log"        # алиас для совместимости
STATS_FILE    = LOG_DIR / "whisper-stats.json"

# Паттерн для поиска строк с результатом транскрипции в логе whisper-ptt.py.
# whisper-ptt.py выводит текст вида:  ✓ Текст: <transcribed text>
# Также поддерживаем строки из whisper-server.py: Transcribed ... : "текст"
import re as _re
_PTT_TEXT_RE     = _re.compile(r'✓\s*(?:Текст|Text|RU|EN)\s*[:\-]\s*(.+)', _re.IGNORECASE)
_SERVER_TEXT_RE  = _re.compile(r'Transcribed [\d.]+s audio in [\d.]+s:\s*"(.+)"')

# ── HTML Template ──────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Whisper PTT — Control Panel</title>
<style>
  :root {
    --bg:       #0f1117;
    --bg2:      #1a1d2e;
    --bg3:      #22263a;
    --accent:   #5b6af7;
    --accent2:  #7c8bff;
    --green:    #2ecc71;
    --red:      #e74c3c;
    --yellow:   #f39c12;
    --cyan:     #00d4ff;
    --text:     #e0e4f0;
    --text2:    #8a92b2;
    --border:   #2d3250;
    --radius:   10px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }
  a { color: var(--accent2); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* Layout */
  .wrapper { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .header  { display: flex; align-items: center; gap: 16px; padding: 20px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header .sub { color: var(--text2); font-size: 13px; }
  .logo { width: 40px; height: 40px; background: var(--accent); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
  @media (max-width: 768px) { .grid, .grid-3 { grid-template-columns: 1fr; } }

  /* Cards */
  .card { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
  .card h2 { font-size: 15px; font-weight: 600; margin-bottom: 16px; color: var(--text); display: flex; align-items: center; gap: 8px; }
  .card h2 .icon { font-size: 16px; }
  .card-full { grid-column: 1 / -1; }

  /* Status badge */
  .badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-green  { background: rgba(46,204,113,.15); color: var(--green); border: 1px solid rgba(46,204,113,.3); }
  .badge-red    { background: rgba(231,76,60,.15);  color: var(--red);   border: 1px solid rgba(231,76,60,.3); }
  .badge-yellow { background: rgba(243,156,18,.15); color: var(--yellow);border: 1px solid rgba(243,156,18,.3); }
  .badge-gray   { background: rgba(138,146,178,.1); color: var(--text2); border: 1px solid var(--border); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .dot-pulse { animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  /* Buttons */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; border: none; cursor: pointer; font-size: 13px; font-weight: 500; transition: all .15s; }
  .btn:disabled { opacity: .45; cursor: not-allowed; }
  .btn-primary  { background: var(--accent); color: #fff; }
  .btn-primary:hover:not(:disabled)  { background: var(--accent2); }
  .btn-green    { background: rgba(46,204,113,.2);  color: var(--green);  border: 1px solid rgba(46,204,113,.3); }
  .btn-green:hover:not(:disabled)    { background: rgba(46,204,113,.35); }
  .btn-red      { background: rgba(231,76,60,.2);   color: var(--red);    border: 1px solid rgba(231,76,60,.3); }
  .btn-red:hover:not(:disabled)      { background: rgba(231,76,60,.35); }
  .btn-yellow   { background: rgba(243,156,18,.2);  color: var(--yellow); border: 1px solid rgba(243,156,18,.3); }
  .btn-yellow:hover:not(:disabled)   { background: rgba(243,156,18,.35); }
  .btn-ghost    { background: transparent; color: var(--text2); border: 1px solid var(--border); }
  .btn-ghost:hover:not(:disabled)    { background: var(--bg3); color: var(--text); }
  .btn-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }

  /* Info rows */
  .info-row  { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); }
  .info-row:last-child { border-bottom: none; }
  .info-label { color: var(--text2); font-size: 12px; }
  .info-value { font-size: 13px; font-weight: 500; }
  .info-value.accent { color: var(--accent2); }
  .info-value.green  { color: var(--green); }
  .info-value.yellow { color: var(--yellow); }

  /* Log */
  .log-box { background: #0a0c14; border: 1px solid var(--border); border-radius: 8px; padding: 14px; font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; line-height: 1.6; max-height: 340px; overflow-y: auto; color: #b0b8d0; white-space: pre-wrap; word-break: break-all; }
  .log-line-ok   { color: #2ecc71; }
  .log-line-err  { color: #e74c3c; }
  .log-line-warn { color: #f39c12; }
  .log-line-info { color: #00d4ff; }

  /* Config editor */
  .config-select { background: var(--bg3); border: 1px solid var(--border); color: var(--text); padding: 7px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
  textarea.cfg { width: 100%; background: #0a0c14; border: 1px solid var(--border); color: #b0b8d0; padding: 14px; border-radius: 8px; font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; line-height: 1.6; resize: vertical; min-height: 260px; }
  textarea.cfg:focus { outline: none; border-color: var(--accent); }

  /* GPU cards */
  .gpu-card { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; padding: 14px; cursor: pointer; transition: all .15s; }
  .gpu-card:hover { border-color: var(--accent); }
  .gpu-card.selected { border-color: var(--accent); background: rgba(91,106,247,.12); }
  .gpu-card .gpu-name { font-weight: 600; margin-bottom: 4px; }
  .gpu-card .gpu-detail { font-size: 12px; color: var(--text2); }

  /* Spinner */
  .spin { display: inline-block; width: 14px; height: 14px; border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Toast */
  #toast-container { position: fixed; bottom: 24px; right: 24px; display: flex; flex-direction: column; gap: 8px; z-index: 9999; }
  .toast { background: var(--bg2); border: 1px solid var(--border); padding: 12px 18px; border-radius: 10px; font-size: 13px; box-shadow: 0 4px 20px rgba(0,0,0,.4); animation: slide-in .2s ease; max-width: 340px; }
  .toast.ok   { border-left: 3px solid var(--green);  }
  .toast.err  { border-left: 3px solid var(--red);    }
  .toast.info { border-left: 3px solid var(--accent); }
  @keyframes slide-in { from { transform: translateX(120%); opacity:0; } to { transform: translateX(0); opacity:1; } }

  /* Misc */
  .sep { height: 1px; background: var(--border); margin: 16px 0; }
  .mono { font-family: 'Cascadia Code','Consolas',monospace; }
  .small { font-size: 12px; color: var(--text2); margin-top: 4px; }
  select.model-sel { background: var(--bg3); border: 1px solid var(--border); color: var(--text); padding: 7px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; width: 100%; margin-top: 10px; }
  .refresh-btn { background: none; border: none; color: var(--text2); cursor: pointer; font-size: 16px; padding: 2px 6px; border-radius: 4px; }
  .refresh-btn:hover { color: var(--text); background: var(--bg3); }

  /* Stats */
  .stats-big { font-size: 48px; font-weight: 700; color: var(--accent2); line-height: 1; letter-spacing: -1px; }
  .stats-label { font-size: 12px; color: var(--text2); margin-top: 4px; }
  .stats-sub { font-size: 13px; color: var(--text2); margin-top: 8px; }
  .stats-sub span { color: var(--text); font-weight: 600; }
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div class="logo">🎤</div>
    <div>
      <h1>Whisper PTT — Control Panel</h1>
      <div class="sub">whisper_from_sssDeMoNsss &nbsp;|&nbsp; sssDeMoNsss &nbsp;|&nbsp; vk.com/basset2</div>
    </div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:10px">
      <span id="auto-refresh-badge" class="badge badge-green"><span class="dot dot-pulse"></span>auto-refresh</span>
      <button class="refresh-btn" onclick="refreshAll()" title="Refresh now">⟳</button>
    </div>
  </div>

  <!-- Row 1: Service + Health -->
  <div class="grid" style="margin-bottom:20px">

    <!-- Service Control -->
    <div class="card">
      <h2><span class="icon">⚙️</span> WhisperServer Service <button class="refresh-btn" onclick="refreshService()" style="margin-left:auto">⟳</button></h2>
      <div class="info-row">
        <span class="info-label">Status (status)</span>
        <span id="svc-status"><span class="badge badge-gray">Checking...</span></span>
      </div>
      <div class="info-row">
        <span class="info-label">Startup (avtozapusk)</span>
        <span id="svc-startup" class="info-value">—</span>
      </div>
      <div class="info-row">
        <span class="info-label">Service name</span>
        <span class="info-value mono">WhisperServer</span>
      </div>
      <div class="btn-row">
        <button class="btn btn-green"  onclick="svcAction('start')">▶ Start</button>
        <button class="btn btn-red"    onclick="svcAction('stop')">■ Stop</button>
        <button class="btn btn-yellow" onclick="svcAction('restart')">↺ Restart</button>
        <button class="btn btn-ghost"  onclick="svcAction('enable')">🔒 Enable auto</button>
        <button class="btn btn-ghost"  onclick="svcAction('disable')">🔓 Disable auto</button>
      </div>
    </div>

    <!-- Server Health -->
    <div class="card">
      <h2><span class="icon">💊</span> Server Health <button class="refresh-btn" onclick="refreshHealth()" style="margin-left:auto">⟳</button></h2>
      <div id="health-content">
        <div class="info-row"><span class="info-label">API server</span><span id="health-status"><span class="badge badge-gray">Checking...</span></span></div>
        <div class="info-row"><span class="info-label">Model (model)</span><span id="health-model" class="info-value">—</span></div>
        <div class="info-row"><span class="info-label">Device (ustroystvo)</span><span id="health-device" class="info-value">—</span></div>
        <div class="info-row"><span class="info-label">GPU (videokarta)</span><span id="health-gpu" class="info-value">—</span></div>
        <div class="info-row"><span class="info-label">Backend</span><span id="health-backend" class="info-value">—</span></div>
        <div class="info-row"><span class="info-label">Uptime</span><span id="health-uptime" class="info-value">—</span></div>
      </div>
      <div class="btn-row">
        <a id="btn-health" href="#" target="_blank" class="btn btn-ghost">🔗 /health</a>
        <a id="btn-models" href="#" target="_blank" class="btn btn-ghost">🔗 /models</a>
      </div>
    </div>
  </div>

  <!-- Row 2: Statistics -->
  <div class="card card-full" style="margin-bottom:20px">
    <h2><span class="icon">📊</span> Word Statistics (Statistika slov) <button class="refresh-btn" onclick="refreshStats()" style="margin-left:auto">⟳</button></h2>
    <div class="grid-3">
      <div style="text-align:center;padding:16px 0">
        <div class="stats-big" id="stat-total-words">—</div>
        <div class="stats-label">всего слов распознано (total words recognized)</div>
      </div>
      <div style="text-align:center;padding:16px 0">
        <div class="stats-big" id="stat-sessions" style="color:var(--green)">—</div>
        <div class="stats-label">транскрипций выполнено (transcriptions done)</div>
      </div>
      <div style="text-align:center;padding:16px 0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px">
        <div class="stats-sub">Обновлено (updated): <span id="stat-updated">—</span></div>
        <button class="btn btn-ghost" style="font-size:12px" onclick="resetStats()">🗑 Reset stats</button>
      </div>
    </div>
  </div>

  <!-- Row 2.5: Recent Transcriptions -->
  <div class="card" style="margin-bottom:20px">
    <h2 style="display:flex;align-items:center;gap:8px">
      <span class="icon">💬</span>
      Recent Transcriptions
      <span style="font-size:12px;font-weight:400;color:var(--text2);margin-left:4px">— results from console</span>
      <button class="refresh-btn" onclick="refreshRecent()" style="margin-left:auto">⟳</button>
    </h2>
    <div id="recent-content">
      <div style="color:var(--text2);font-size:13px;font-family:monospace">Loading...</div>
    </div>
  </div>

  <!-- Row 3: GPU Switcher -->
  <div class="card" style="margin-bottom:20px">
    <h2><span class="icon">🎮</span> GPU & Model Selector <button class="refresh-btn" onclick="refreshGPU()" style="margin-left:auto">⟳</button></h2>
    <div id="gpu-content">
      <div style="color:var(--text2);font-size:13px">Loading GPU info (zagruzka GPU informatsii)...</div>
    </div>
  </div>

  <!-- Row 3: Config + Log -->
  <div class="grid" style="margin-bottom:20px">

    <!-- Config Editor -->
    <div class="card">
      <h2><span class="icon">📝</span> Config Editor (Redaktor konfiguratsii)</h2>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <select class="config-select" id="cfg-select" onchange="loadConfig()">
          <option value="">Select config.toml...</option>
        </select>
      </div>
      <textarea class="cfg" id="cfg-text" placeholder="Select a config.toml above to edit (Vyberte config.toml vysshe dlya redaktirovaniya)..."></textarea>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="saveConfig()">💾 Save (Sohranit)</button>
        <button class="btn btn-ghost"   onclick="loadConfig()">↩ Reload (Perezagruzit)</button>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════════ -->
    <!-- CORRECTIONS DICTIONARY ─────────────────────────────────────────── -->
    <!-- ═══════════════════════════════════════════════════════════════════ -->
    <div class="card" id="corrections-card" style="border:1.5px solid #f59e0b">
      <h2 style="display:flex;align-items:center;gap:10px">
        <span class="icon">✏️</span>
        <span>Corrections Dictionary <span style="font-size:13px;color:var(--text2);font-weight:400">(Slovar zamen)</span></span>
        <span id="corr-count-badge" style="margin-left:6px;background:#f59e0b;color:#000;border-radius:12px;padding:2px 10px;font-size:12px;font-weight:700">0</span>
        <button class="refresh-btn" onclick="loadCorrections()" style="margin-left:auto">⟳</button>
      </h2>

      <p style="color:var(--text2);font-size:13px;margin:0 0 14px">
        Whisper иногда путает слова — настрой замены прямо здесь. Применяются к каждой транскрипции автоматически.<br>
        <b style="color:#f59e0b">Простая замена</b> — точное слово. <b style="color:#a78bfa">Regex</b> — сложные паттерны.
      </p>

      <!-- ── Add form ─────────────────────────────────────────────────── -->
      <div id="corr-add-panel" style="background:var(--card2,#161b22);border-radius:10px;padding:16px;margin-bottom:16px;border:1px solid #30363d">
        <div style="font-size:13px;font-weight:700;color:#f59e0b;margin-bottom:12px;letter-spacing:.5px">＋ НОВАЯ ЗАМЕНА</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label style="font-size:11px;color:var(--text2);display:block;margin-bottom:4px">ПАТТЕРН (что заменять)</label>
            <input id="corr-in-pattern" placeholder="докер" style="width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:14px">
          </div>
          <div>
            <label style="font-size:11px;color:var(--text2);display:block;margin-bottom:4px">ЗАМЕНА (на что)</label>
            <input id="corr-in-replacement" placeholder="Docker" style="width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:14px">
          </div>
        </div>
        <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label style="font-size:11px;color:var(--text2);display:block;margin-bottom:4px">ОПИСАНИЕ (опционально)</label>
            <input id="corr-in-desc" placeholder="Технология контейнеризации" style="width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:14px">
          </div>
          <div style="display:flex;flex-direction:column;justify-content:flex-end">
            <label style="font-size:11px;color:var(--text2);display:block;margin-bottom:4px">РЕЖИМ</label>
            <select id="corr-in-regex" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:13px;cursor:pointer">
              <option value="false">📝 Простая замена</option>
              <option value="true">⚡ Regex</option>
            </select>
          </div>
        </div>

        <!-- Test field -->
        <div style="margin-bottom:10px">
          <label style="font-size:11px;color:var(--text2);display:block;margin-bottom:4px">🧪 ТЕСТ (введи текст — увидишь результат)</label>
          <div style="display:flex;gap:8px">
            <input id="corr-in-test" placeholder="Напиши докер и я покажу замену..." style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 10px;font-size:13px" oninput="liveTestCorrection()">
            <div id="corr-test-result" style="flex:1;background:#0d1117;border:1px dashed #30363d;border-radius:6px;color:#58a6ff;padding:8px 10px;font-size:13px;min-height:36px;display:flex;align-items:center">
              <span style="color:#484f58;font-style:italic">результат появится здесь...</span>
            </div>
          </div>
        </div>

        <button onclick="addCorrection()" style="background:#f59e0b;color:#000;border:none;border-radius:7px;padding:9px 22px;font-size:14px;font-weight:700;cursor:pointer;letter-spacing:.3px">
          ＋ Добавить замену
        </button>
        <span id="corr-add-msg" style="margin-left:12px;font-size:13px"></span>
      </div>

      <!-- ── Search ───────────────────────────────────────────────────── -->
      <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
        <input id="corr-search" placeholder="🔍 Поиск по паттерну или описанию..." oninput="renderCorrections()"
               style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;padding:8px 12px;font-size:13px">
        <span id="corr-filter-active" style="font-size:12px;color:var(--text2)"></span>
      </div>

      <!-- ── Table ────────────────────────────────────────────────────── -->
      <div id="corr-table-wrap" style="overflow-x:auto">
        <table id="corr-table" style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid #21262d">
              <th style="text-align:left;padding:6px 8px;color:var(--text2);font-weight:600;width:28px"></th>
              <th style="text-align:left;padding:6px 8px;color:var(--text2);font-weight:600">ПАТТЕРН</th>
              <th style="text-align:left;padding:6px 8px;color:var(--text2);font-weight:600">ЗАМЕНА</th>
              <th style="text-align:left;padding:6px 8px;color:var(--text2);font-weight:600">ОПИСАНИЕ</th>
              <th style="text-align:center;padding:6px 8px;color:var(--text2);font-weight:600">РЕЖИМ</th>
              <th style="text-align:center;padding:6px 8px;color:var(--text2);font-weight:600">ВКЛ</th>
              <th style="text-align:center;padding:6px 8px;color:var(--text2);font-weight:600">ДЕЙСТВИЯ</th>
            </tr>
          </thead>
          <tbody id="corr-tbody">
            <tr><td colspan="7" style="text-align:center;color:var(--text2);padding:24px">Загрузка...</td></tr>
          </tbody>
        </table>
      </div>
      <div id="corr-empty" style="display:none;text-align:center;padding:32px;color:var(--text2)">
        <div style="font-size:36px;margin-bottom:8px">✏️</div>
        <div>Словарь пустой — добавь первую замену выше!</div>
      </div>
    </div><!-- /corrections-card -->

    <!-- ── Diagnostics ──────────────────────────────────────────────────── -->
    <div class="card" id="diag-card" style="border:1.5px solid #5b6af7;margin-bottom:20px">
      <h2><span class="icon">🩺</span> Диагностика системы
        <span style="font-size:12px;font-weight:400;color:var(--text2);margin-left:8px">(System Diagnostics)</span>
        <button class="refresh-btn" id="diag-run-btn" onclick="runDiagnose()" style="margin-left:auto" title="Запустить диагностику">▶ Run</button>
      </h2>
      <div id="diag-info" style="color:var(--text2);font-size:13px;margin-bottom:12px">
        Нажмите <b>▶ Run</b> — за ~10 секунд проверяются все компоненты:<br>
        микрофон, GPU, FFmpeg, пакеты, сервер, модель, буфер обмена, место на диске.
      </div>
      <div id="diag-progress" style="display:none;padding:12px 0;color:var(--yellow)">
        <span class="dot dot-pulse" style="background:var(--yellow);margin-right:8px"></span>Диагностика запущена, подождите ~10 сек...
      </div>
      <div id="diag-results" style="display:none">
        <div id="diag-summary" style="font-weight:700;font-size:15px;margin-bottom:14px"></div>
        <div id="diag-items" style="display:flex;flex-direction:column;gap:5px"></div>
        <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-ghost" style="font-size:12px" onclick="runDiagnose()">↺ Повторить</button>
          <button class="btn btn-ghost" style="font-size:12px" id="diag-log-btn" onclick="openDiagLog()">📄 Открыть лог</button>
        </div>
      </div>
    </div>


    <!-- Live Log -->
    <div class="card">
      <h2><span class="icon">📋</span> Live Log
        <button class="refresh-btn" onclick="refreshLog()" style="margin-left:auto">⟳</button>
        <button class="refresh-btn" onclick="clearLog()" title="Clear display">✕</button>
      </h2>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <label style="font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="checkbox" id="auto-scroll" checked> Auto-scroll
        </label>
        <span style="font-size:12px;color:var(--text2)" id="log-lines">0 lines</span>
      </div>
      <div class="log-box" id="log-box">Loading log (zagruzka loga)...</div>
    </div>
  </div>

  <!-- Row 4: Installed versions -->
  <div class="card card-full" style="margin-bottom:20px">
    <h2><span class="icon">📦</span> Installed Versions (Ustanovlennyye versii)</h2>
    <div id="versions-content" class="grid-3" style="margin-top:4px">
      Loading...
    </div>
  </div>

  <!-- Row 5: Quick actions -->
  <div class="card card-full">
    <h2><span class="icon">⚡</span> Quick Actions (Bystryye deystviya)</h2>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="openExternal('http://homeassistant.local:8123')">🏠 Open Home Assistant</button>
      <button class="btn btn-ghost" onclick="openServerHealth()">💊 Server Health JSON</button>
      <button class="btn btn-ghost" onclick="openExternal('C:/whisper-ptt/logs/whisper-server.log')">📋 Open Log File</button>
      <button class="btn btn-ghost" onclick="runSwitchGPU()">🎮 Switch GPU (PowerShell)</button>
      <button class="btn btn-ghost" onclick="runManager()">⚙️ Open Manager BAT</button>
    </div>
  </div>
</div>

<div id="toast-container"></div>

<script>
const API = '';  // same origin

// ── Toast notifications ───────────────────────────────────────────────────────
function toast(msg, type='info', dur=3000) {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transform='translateX(120%)'; t.style.transition='all .3s'; setTimeout(()=>t.remove(), 300); }, dur);
}

// ── API call helper ───────────────────────────────────────────────────────────
async function api(path, method='GET', body=null) {
  try {
    const opts = { method, headers: {'Content-Type':'application/json'} };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    return await r.json();
  } catch(e) {
    return { error: e.message };
  }
}

// ── Service control ───────────────────────────────────────────────────────────
async function svcAction(action) {
  toast(`${action}ing service... (${action}...)`, 'info');
  const r = await api(`/api/service/${action}`, 'POST');
  if (r.ok) {
    toast(r.message || `${action} OK`, 'ok');
    setTimeout(refreshService, 1500);
  } else {
    toast(r.error || 'Error', 'err', 5000);
  }
}

async function refreshService() {
  const r = await api('/api/service/status');
  if (r.error) { return; }
  const el = document.getElementById('svc-status');
  if (r.running) {
    el.innerHTML = '<span class="badge badge-green"><span class="dot dot-pulse"></span>RUNNING</span>';
  } else if (r.status === 'stopped') {
    el.innerHTML = '<span class="badge badge-red"><span class="dot"></span>STOPPED</span>';
  } else if (r.status === 'not_installed') {
    el.innerHTML = '<span class="badge badge-gray"><span class="dot"></span>NOT INSTALLED</span>';
  } else {
    el.innerHTML = `<span class="badge badge-yellow"><span class="dot"></span>${r.status.toUpperCase()}</span>`;
  }
  document.getElementById('svc-startup').textContent = r.startup || '—';
  document.getElementById('svc-startup').className = 'info-value ' + (r.startup === 'Automatic' ? 'green' : '');
}

// ── Health ────────────────────────────────────────────────────────────────────
async function refreshHealth() {
  const r = await api('/api/health');
  if (r.error || !r.status) {
    document.getElementById('health-status').innerHTML = '<span class="badge badge-red">OFFLINE</span>';
    ['health-model','health-device','health-gpu','health-backend','health-uptime'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    return;
  }
  document.getElementById('health-status').innerHTML = '<span class="badge badge-green"><span class="dot dot-pulse"></span>ONLINE</span>';
  document.getElementById('health-model').textContent   = r.model || '—';
  document.getElementById('health-model').className     = 'info-value accent';
  document.getElementById('health-device').textContent  = r.device || '—';
  document.getElementById('health-device').className    = 'info-value ' + (r.device==='cuda'?'green':'yellow');
  const gpu = r.gpu || {};
  document.getElementById('health-gpu').textContent = gpu.available ? `${gpu.name} (${gpu.vram_gb} GB)` : 'CPU mode';
  document.getElementById('health-gpu').className   = 'info-value ' + (gpu.available?'green':'yellow');
  document.getElementById('health-backend').textContent = r.backend || '—';
  const up = r.uptime_sec || 0;
  const h = Math.floor(up/3600), m = Math.floor((up%3600)/60), s = up%60;
  document.getElementById('health-uptime').textContent = `${h}h ${m}m ${s}s`;
}

// ── GPU Selector ──────────────────────────────────────────────────────────────
let gpuData = [];
async function refreshGPU() {
  const r = await api('/api/gpus');
  const el = document.getElementById('gpu-content');
  if (r.error || !r.gpus || r.gpus.length === 0) {
    el.innerHTML = '<div style="color:var(--text2);font-size:13px">No CUDA GPUs detected (CUDA GPU ne obnaruzhen). CPU mode active.</div>';
    return;
  }
  gpuData = r.gpus;
  const cur = r.current_gpu !== undefined ? r.current_gpu : 0;
  const curModel = r.current_model || 'large-v2';

  let html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-bottom:16px">';
  r.gpus.forEach(g => {
    const sel = g.index === cur ? ' selected' : '';
    html += `<div class="gpu-card${sel}" onclick="selectGPU(${g.index})" id="gpu-card-${g.index}">
      <div class="gpu-name">GPU ${g.index}: ${g.name}</div>
      <div class="gpu-detail">VRAM: ${g.vram_gb} GB &nbsp;|&nbsp; Optimal: ${g.optimal_model}</div>
    </div>`;
  });
  html += '</div>';

  html += `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <span style="font-size:13px;color:var(--text2)">Model (model):</span>
    <select class="model-sel" id="model-sel" style="width:auto;min-width:200px">
      <option value="tiny"     ${curModel==='tiny'    ?'selected':''}>tiny     — BASIC (~0.5 sec)</option>
      <option value="base"     ${curModel==='base'    ?'selected':''}>base     — GOOD  (~1 sec)</option>
      <option value="small"    ${curModel==='small'   ?'selected':''}>small    — GREAT (~1-2 sec)</option>
      <option value="medium"   ${curModel==='medium'  ?'selected':''}>medium   — HIGH  (~2-3 sec)</option>
      <option value="large-v2" ${curModel==='large-v2'?'selected':''}>large-v2 — MAXIMUM (~2-4 sec)</option>
      <option value="large-v3" ${curModel==='large-v3'?'selected':''}>large-v3 — MAXIMUM+ (~2-4 sec)</option>
    </select>
    <button class="btn btn-primary" onclick="applyGPU()">Apply & Restart (Primenit i Perezapustit)</button>
    <span style="font-size:12px;color:var(--text2)" id="gpu-apply-hint">Select GPU and model, then click Apply.</span>
  </div>`;
  el.innerHTML = html;
}

let selectedGPU = -1;
function selectGPU(idx) {
  selectedGPU = idx;
  document.querySelectorAll('.gpu-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`gpu-card-${idx}`);
  if (card) card.classList.add('selected');
}

async function applyGPU() {
  const gpuIdx = selectedGPU >= 0 ? selectedGPU : 0;
  const model  = document.getElementById('model-sel')?.value || 'large-v2';
  const hint   = document.getElementById('gpu-apply-hint');
  if (hint) hint.innerHTML = '<span class="spin"></span> Applying... (primenyayem...)';
  const r = await api('/api/service/apply-gpu', 'POST', { gpu_index: gpuIdx, model });
  if (r.ok) {
    toast(`Модель [${model}] применена. Сервер перезапускается...`, 'ok', 4000);
    if (hint) hint.innerHTML = `<span class="spin"></span> Ожидаем загрузку модели [${model}]...`;

    // Polling: проверяем health каждые 3 сек до 60 сек пока сервер не поднимется
    let elapsed = 0;
    const pollInterval = 3000;
    const maxWait = 60000;
    const poll = setInterval(async () => {
      elapsed += pollInterval;
      const h = await api('/api/health');
      const online = h && !h.error && h.status === 'ok' && h.model_loaded === true;
      if (hint) {
        hint.innerHTML = online
          ? `✅ Модель [${h.model || model}] загружена (${elapsed/1000}с)`
          : `<span class="spin"></span> Ожидаем сервер... ${elapsed/1000}с / 60с`;
      }
      refreshService();
      refreshHealth();
      if (online || elapsed >= maxWait) {
        clearInterval(poll);
        if (online) {
          toast(`✅ Сервер готов: модель [${h.model || model}] загружена за ${elapsed/1000}с`, 'ok', 5000);
        } else {
          toast('⚠️ Сервер не ответил за 60с — проверьте статус вручную', 'err', 6000);
          if (hint) hint.textContent = 'Timeout — check server status manually';
        }
      }
    }, pollInterval);
  } else {
    toast(r.error || 'Failed to apply', 'err', 5000);
    if (hint) hint.textContent = r.error || 'Error';
  }
}

// ── Log ───────────────────────────────────────────────────────────────────────
function colorLogLine(line) {
  if (/\[OK\]|✓|loaded|ready|started|success/i.test(line))   return `<span class="log-line-ok">${esc(line)}</span>`;
  if (/error|ERROR|failed|FAILED|exception|Exception/i.test(line)) return `<span class="log-line-err">${esc(line)}</span>`;
  if (/warning|warn|\[!\]|⚠/i.test(line))   return `<span class="log-line-warn">${esc(line)}</span>`;
  if (/INFO|info|Loading|Transcrib/i.test(line)) return `<span class="log-line-info">${esc(line)}</span>`;
  return esc(line);
}
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function refreshLog() {
  const r = await api('/api/log');
  const box = document.getElementById('log-box');
  if (r.error) { box.textContent = r.error; return; }
  const lines = (r.lines || []);
  document.getElementById('log-lines').textContent = `${lines.length} lines`;
  box.innerHTML = lines.map(colorLogLine).join('\n');
  if (document.getElementById('auto-scroll')?.checked) {
    box.scrollTop = box.scrollHeight;
  }
}

function clearLog() {
  document.getElementById('log-box').innerHTML = '';
  document.getElementById('log-lines').textContent = '0 lines';
}

// ── Config editor ─────────────────────────────────────────────────────────────
async function initConfigSelect() {
  const r = await api('/api/configs');
  const sel = document.getElementById('cfg-select');
  if (r.configs) {
    sel.innerHTML = '<option value="">Select config.toml...</option>';
    r.configs.forEach(c => {
      sel.innerHTML += `<option value="${c.path}">${c.label}</option>`;
    });
  }
}

async function loadConfig() {
  const path = document.getElementById('cfg-select').value;
  if (!path) { document.getElementById('cfg-text').value = ''; return; }
  const r = await api(`/api/config?path=${encodeURIComponent(path)}`);
  document.getElementById('cfg-text').value = r.content || r.error || '';
}

async function saveConfig() {
  const path    = document.getElementById('cfg-select').value;
  const content = document.getElementById('cfg-text').value;
  if (!path) { toast('Select a config file first (Vyberte fayl konfiguratsii)', 'err'); return; }
  const r = await api('/api/config', 'POST', { path, content });
  if (r.ok) { toast('Config saved (config sohranyon) ✓', 'ok'); }
  else       { toast(r.error || 'Save failed', 'err', 5000); }
}

// ── Installed versions ────────────────────────────────────────────────────────
async function refreshVersions() {
  const r = await api('/api/versions');
  const el = document.getElementById('versions-content');
  if (!r.versions) { el.innerHTML = 'Error loading versions'; return; }
  el.className = 'grid-3';
  el.innerHTML = r.versions.map(v => `
    <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:14px">
      <div style="font-weight:600;margin-bottom:6px">${v.name}</div>
      <div style="font-size:12px;color:var(--text2);margin-bottom:8px">${v.path}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${v.installed ? '<span class="badge badge-green">installed</span>' : '<span class="badge badge-gray">not found</span>'}
        ${v.service   ? '<span class="badge badge-green">service ✓</span>' : ''}
        ${v.remote    ? '<span class="badge badge-yellow">remote mode</span>' : ''}
      </div>
      ${v.model ? `<div style="margin-top:8px;font-size:12px;color:var(--text2)">model: <span style="color:var(--accent2)">${v.model}</span> &nbsp; device: <span style="color:var(--text)">${v.device}</span></div>` : ''}
    </div>
  `).join('');
}

// ── Quick actions ─────────────────────────────────────────────────────────────
function openExternal(url) { window.open(url, '_blank'); }
async function runSwitchGPU() {
  const r = await api('/api/run-script', 'POST', { script: 'switch-gpu' });
  toast(r.message || r.error || 'Launched', r.ok ? 'ok' : 'err');
}
async function runManager() {
  const r = await api('/api/run-script', 'POST', { script: 'manager' });
  toast(r.message || r.error || 'Launched', r.ok ? 'ok' : 'err');
}

// ── Statistics ────────────────────────────────────────────────────────────────
async function refreshStats() {
  const r = await api('/api/stats');
  if (r.error) return;
  const fmt = n => n.toLocaleString('ru-RU');
  document.getElementById('stat-total-words').textContent = fmt(r.total_words  || 0);
  document.getElementById('stat-sessions').textContent    = fmt(r.total_sessions || 0);
  document.getElementById('stat-updated').textContent     = r.last_updated || '—';
}

async function resetStats() {
  if (!confirm('Сбросить статистику? (Reset statistics?)')) return;
  const r = await api('/api/stats/reset', 'POST');
  if (r.ok) {
    toast('Statistics reset ✓', 'ok');
    refreshStats();
  } else {
    toast(r.error || 'Error', 'err');
  }
}

async function refreshRecent() {
  const r = await api('/api/results');
  const el = document.getElementById('recent-content');
  if (!el) return;

  const entries = (r && r.results) ? r.results : [];
  if (!entries.length) {
    el.innerHTML = `<div style="background:#0d1117;border-radius:6px;padding:14px 16px;font-family:monospace;font-size:13px;color:#6e7681">
      No transcriptions yet — press Right Ctrl or Right Alt to start.
    </div>`;
    return;
  }

  // ── Рендер одной event-строки (системное событие смены модели / перезапуска)
  function renderEvent(e) {
    const ts  = e.time || '';
    const ev  = e.event || '';
    const msg = escHtml(e.message || '');
    const elapsed = e.elapsed > 0 ? ` <span class="rc-elapsed">(${e.elapsed}с)</span>` : '';

    if (ev === 'restart_begin') {
      return [
        `<span class="rc-sep">── ── ── ── ── ── ── ── ── ── ── ── ── ── ──</span>`,
        `<span class="rc-time">${ts}</span> <span class="rc-ev-warn">🔄 ПЕРЕЗАПУСК СЕРВЕРА</span>`,
        `<span class="rc-ev-warn-body">   ${msg}</span>`,
      ];
    }
    if (ev === 'restart_waiting') {
      return [
        `<span class="rc-time">${ts}</span> <span class="rc-ev-wait">   ⏳ ${msg}${elapsed}</span>`,
      ];
    }
    if (ev === 'model_changed') {
      const arrow = e.old_model && e.new_model
        ? `<span class="rc-ev-old">[${escHtml(e.old_model)}]</span> → <span class="rc-ev-new">[${escHtml(e.new_model)}]</span>`
        : escHtml(e.new_model || '');
      return [
        `<span class="rc-time">${ts}</span> <span class="rc-ev-ok">✅ МОДЕЛЬ ИЗМЕНЕНА</span>${elapsed}`,
        `<span class="rc-ev-ok-body">   ${arrow} на ${escHtml(e.device || '').toUpperCase()}</span>`,
        `<span class="rc-sep">── ── ── ── ── ── ── ── ── ── ── ── ── ── ──</span>`,
        '',
      ];
    }
    if (ev === 'server_restarted') {
      return [
        `<span class="rc-time">${ts}</span> <span class="rc-ev-ok">✅ СЕРВЕР ПЕРЕЗАПУЩЕН</span>${elapsed}`,
        `<span class="rc-ev-ok-body">   Модель: <span class="rc-ev-new">[${escHtml(e.new_model || '')}]</span> на ${escHtml(e.device || '').toUpperCase()} — готов к работе</span>`,
        `<span class="rc-sep">── ── ── ── ── ── ── ── ── ── ── ── ── ── ──</span>`,
        '',
      ];
    }
    if (ev === 'server_ready') {
      return [
        `<span class="rc-time">${ts}</span> <span class="rc-ev-ok">✅ СЕРВЕР ПОДКЛЮЧЁН</span>`,
        `<span class="rc-ev-ok-body">   Модель: <span class="rc-ev-new">[${escHtml(e.new_model || '')}]</span> на ${escHtml(e.device || '').toUpperCase()}</span>`,
        '',
      ];
    }
    // fallback — любое неизвестное событие
    return [
      `<span class="rc-time">${ts}</span> <span class="rc-ev-info">ℹ ${msg}</span>`,
    ];
  }

  // ── Рендер одной транскрипции
  function renderTranscription(e) {
    const ts    = e.time || '';
    const model = (e.model && e.device) ? `[${e.device}|${e.model}]` : (e.source === 'local' ? '[local]' : '');
    const speed = e.proc_sec > 0 ? ` ${e.proc_sec}s` : '';
    const hasEN = e.en && e.en.trim().length > 0;
    const hasRU = e.ru && e.ru.trim().length > 0;
    const out   = [];

    if (hasEN && hasRU) {
      out.push(`<span class="rc-time">${ts}</span> <span class="rc-translate">🌐 RU → EN</span>`);
      if (speed || model) out.push(`<span class="rc-meta">   ✓ Remote ${model}${speed}</span>`);
      out.push(`<span class="rc-tree">   ┌─</span> <span class="rc-ru">RU: ${escHtml(e.ru)}</span>`);
      out.push(`<span class="rc-tree">   └─</span> <span class="rc-en">EN: ${escHtml(e.en)}</span>`);
    } else if (hasRU) {
      if (speed || model) out.push(`<span class="rc-time">${ts}</span> <span class="rc-meta">✓ Remote ${model}${speed}</span>`);
      out.push(`<span class="rc-ok">✓</span> <span class="rc-label">RU:</span> <span class="rc-ru">${escHtml(e.ru)}</span>`);
    } else if (hasEN) {
      out.push(`<span class="rc-ok">✓</span> <span class="rc-label">EN:</span> <span class="rc-en">${escHtml(e.en)}</span>`);
    }
    out.push('');
    return out;
  }

  // ── Собираем все строки
  const lines = [];
  for (const e of entries) {
    if (e.type === 'event') {
      lines.push(...renderEvent(e));
    } else {
      lines.push(...renderTranscription(e));
    }
  }

  el.innerHTML = `
    <style>
      .rc-term { background:#0d1117; border-radius:6px; padding:12px 16px;
                 font-family:'Consolas','Courier New',monospace; font-size:12.5px;
                 line-height:1.7; max-height:400px; overflow-y:auto;
                 color:#c9d1d9; word-break:break-word; }
      .rc-time        { color:#484f58; font-size:11px; }
      .rc-meta        { color:#8b949e; }
      .rc-translate   { color:#d29922; font-weight:600; }
      .rc-ok          { color:#3fb950; }
      .rc-label       { color:#3fb950; font-weight:600; }
      .rc-ru          { color:#7ee787; }
      .rc-en          { color:#79c0ff; }
      .rc-tree        { color:#484f58; }
      .rc-sep         { color:#21262d; font-size:11px; display:block; margin:4px 0; }
      .rc-elapsed     { color:#484f58; font-size:11px; }
      .rc-ev-warn      { color:#f0883e; font-weight:700; letter-spacing:.4px; }
      .rc-ev-warn-body { color:#e3b341; display:block; }
      .rc-ev-wait      { color:#8b949e; font-style:italic; }
      .rc-ev-ok        { color:#3fb950; font-weight:700; letter-spacing:.4px; }
      .rc-ev-ok-body   { color:#7ee787; display:block; }
      .rc-ev-old       { color:#f85149; }
      .rc-ev-new       { color:#3fb950; font-weight:600; }
      .rc-ev-info      { color:#58a6ff; }
    </style>
    <div class="rc-term" id="rc-term-box">${lines.join('<br>')}</div>`;
  // Прокрутка вниз после рендера — НЕ через innerHTML/script (ломает внешний <script> блок)
  setTimeout(() => {
    const box = document.getElementById('rc-term-box');
    if (box) box.scrollTop = box.scrollHeight;
  }, 0);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Auto-refresh loop ─────────────────────────────────────────────────────────
function refreshAll() {
  refreshService();
  refreshHealth();
  refreshGPU();
  refreshLog();
  refreshVersions();
  refreshStats();
  refreshRecent();
}

// ── Server port (resolved from backend /api/server-port) ─────────────────────
let serverPort = 9000;
async function initServerPort() {
  try {
    const r = await api('/api/server-port');
    if (r && r.port) {
      serverPort = r.port;
      // Update health/models links once port is known
      const btnH = document.getElementById('btn-health');
      const btnM = document.getElementById('btn-models');
      if (btnH) btnH.href = 'http://localhost:' + serverPort + '/health';
      if (btnM) btnM.href = 'http://localhost:' + serverPort + '/models';
    }
  } catch(e) {}
}
function openServerHealth() {
  window.open('http://localhost:' + serverPort + '/health', '_blank');
}

async function init() {
  await initServerPort();
  await initConfigSelect();
  refreshAll();
  loadCorrections();
  setInterval(() => { refreshService(); refreshHealth(); refreshLog(); refreshStats(); refreshRecent(); }, 5000);
  setInterval(() => { refreshGPU(); refreshVersions(); }, 30000);
}

// ═══════════════════════════════════════════════════════════════════════════
// CORRECTIONS DICTIONARY — JS
// ═══════════════════════════════════════════════════════════════════════════

let _correctionsData = [];

async function loadCorrections() {
  try {
    const r = await fetch('/api/corrections').then(r => r.json());
    _correctionsData = r.corrections || [];
    document.getElementById('corr-count-badge').textContent = _correctionsData.length;
    renderCorrections();
  } catch(e) {
    document.getElementById('corr-tbody').innerHTML =
      `<tr><td colspan="7" style="text-align:center;color:#f85149;padding:20px">Ошибка загрузки: ${e.message}</td></tr>`;
  }
}

function renderCorrections() {
  const q = (document.getElementById('corr-search').value || '').toLowerCase();
  const filtered = q
    ? _correctionsData.filter(c =>
        (c.pattern||'').toLowerCase().includes(q) ||
        (c.replacement||'').toLowerCase().includes(q) ||
        (c.description||'').toLowerCase().includes(q))
    : _correctionsData;

  const filterEl = document.getElementById('corr-filter-active');
  filterEl.textContent = q ? `Найдено: ${filtered.length} из ${_correctionsData.length}` : '';

  const tbody = document.getElementById('corr-tbody');
  const emptyEl = document.getElementById('corr-empty');

  if (filtered.length === 0) {
    tbody.innerHTML = '';
    emptyEl.style.display = 'block';
    return;
  }
  emptyEl.style.display = 'none';

  tbody.innerHTML = filtered.map(c => {
    const regexBadge = c.regex
      ? `<span style="background:#7c3aed;color:#fff;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700">⚡regex</span>`
      : `<span style="background:#1f6feb;color:#fff;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700">📝простая</span>`;
    const toggleColor = c.enabled ? '#22c55e' : '#6b7280';
    const toggleIcon  = c.enabled ? '●' : '○';
    return `
    <tr id="corr-row-${c.id}" style="border-bottom:1px solid #21262d;transition:background .15s"
        onmouseover="this.style.background='#161b22'" onmouseout="this.style.background=''">
      <td style="padding:8px 4px 8px 8px;color:#6b7280;font-size:11px">${c.id}</td>
      <td style="padding:8px">
        <span id="corr-pat-disp-${c.id}" style="font-family:monospace;background:#0d1117;border-radius:4px;padding:3px 8px;color:#f59e0b;font-size:13px">${esc(c.pattern)}</span>
        <input id="corr-pat-edit-${c.id}" value="${esc(c.pattern)}" style="display:none;font-family:monospace;background:#0d1117;border:1px solid #f59e0b;border-radius:4px;padding:3px 8px;color:#f59e0b;font-size:13px;width:160px">
      </td>
      <td style="padding:8px">
        <span id="corr-rep-disp-${c.id}" style="font-family:monospace;background:#0d1117;border-radius:4px;padding:3px 8px;color:#58a6ff;font-size:13px">${esc(c.replacement)}</span>
        <input id="corr-rep-edit-${c.id}" value="${esc(c.replacement)}" style="display:none;font-family:monospace;background:#0d1117;border:1px solid #58a6ff;border-radius:4px;padding:3px 8px;color:#58a6ff;font-size:13px;width:160px">
      </td>
      <td style="padding:8px;color:var(--text2);font-size:12px;max-width:180px">
        <span id="corr-desc-disp-${c.id}">${esc(c.description||'—')}</span>
        <input id="corr-desc-edit-${c.id}" value="${esc(c.description||'')}" style="display:none;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:3px 8px;color:#e6edf3;font-size:12px;width:140px">
      </td>
      <td style="padding:8px;text-align:center">${regexBadge}</td>
      <td style="padding:8px;text-align:center">
        <button onclick="toggleCorrection(${c.id}, ${!c.enabled})"
                style="background:none;border:none;cursor:pointer;font-size:20px;color:${toggleColor};line-height:1"
                title="${c.enabled ? 'Выключить' : 'Включить'}">${toggleIcon}</button>
      </td>
      <td style="padding:8px;text-align:center;white-space:nowrap">
        <button id="corr-edit-btn-${c.id}" onclick="startEditCorrection(${c.id})"
                style="background:#1f6feb;color:#fff;border:none;border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer;margin-right:4px">✏️</button>
        <button id="corr-save-btn-${c.id}" onclick="saveEditCorrection(${c.id})" style="display:none;background:#22c55e;color:#000;border:none;border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer;margin-right:4px">💾</button>
        <button id="corr-cancel-btn-${c.id}" onclick="cancelEditCorrection(${c.id})" style="display:none;background:#6b7280;color:#fff;border:none;border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer;margin-right:4px">✕</button>
        <button onclick="deleteCorrection(${c.id})"
                style="background:#f85149;color:#fff;border:none;border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer"
                title="Удалить">🗑</button>
      </td>
    </tr>`;
  }).join('');
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Inline edit helpers
function startEditCorrection(id) {
  ['pat','rep','desc'].forEach(f => {
    document.getElementById(`corr-${f}-disp-${id}`).style.display = 'none';
    document.getElementById(`corr-${f}-edit-${id}`).style.display = 'inline-block';
  });
  document.getElementById(`corr-edit-btn-${id}`).style.display   = 'none';
  document.getElementById(`corr-save-btn-${id}`).style.display   = 'inline-block';
  document.getElementById(`corr-cancel-btn-${id}`).style.display = 'inline-block';
}
function cancelEditCorrection(id) {
  renderCorrections();
}
async function saveEditCorrection(id) {
  const pattern     = document.getElementById(`corr-pat-edit-${id}`).value.trim();
  const replacement = document.getElementById(`corr-rep-edit-${id}`).value.trim();
  const description = document.getElementById(`corr-desc-edit-${id}`).value.trim();
  if (!pattern) { alert('Паттерн не может быть пустым'); return; }
  const r = await apiFetch('/api/corrections/update', {id, pattern, replacement, description});
  if (r.ok) { await loadCorrections(); } else { alert('Ошибка: ' + (r.error||'unknown')); }
}

async function toggleCorrection(id, enabled) {
  await apiFetch('/api/corrections/update', {id, enabled});
  await loadCorrections();
}

async function deleteCorrection(id) {
  if (!confirm('Удалить эту замену?')) return;
  const r = await apiFetch('/api/corrections/delete', {id});
  if (r.ok) { await loadCorrections(); } else { alert('Ошибка: ' + (r.error||'unknown')); }
}

async function addCorrection() {
  const pattern     = document.getElementById('corr-in-pattern').value.trim();
  const replacement = document.getElementById('corr-in-replacement').value.trim();
  const description = document.getElementById('corr-in-desc').value.trim();
  const regex       = document.getElementById('corr-in-regex').value === 'true';
  const msg         = document.getElementById('corr-add-msg');
  if (!pattern) { msg.textContent = '⚠️ Паттерн обязателен'; msg.style.color='#f85149'; return; }
  const r = await apiFetch('/api/corrections/add', {pattern, replacement, description, regex, enabled: true});
  if (r.ok) {
    msg.textContent = '✓ Добавлено!'; msg.style.color = '#22c55e';
    document.getElementById('corr-in-pattern').value = '';
    document.getElementById('corr-in-replacement').value = '';
    document.getElementById('corr-in-desc').value = '';
    document.getElementById('corr-in-test').value = '';
    document.getElementById('corr-test-result').innerHTML = '<span style="color:#484f58;font-style:italic">результат появится здесь...</span>';
    await loadCorrections();
    setTimeout(() => { msg.textContent = ''; }, 3000);
  } else {
    msg.textContent = '✗ ' + (r.error || 'Ошибка');
    msg.style.color = '#f85149';
  }
}

let _liveTestTimer = null;
function liveTestCorrection() {
  clearTimeout(_liveTestTimer);
  _liveTestTimer = setTimeout(async () => {
    const pattern     = document.getElementById('corr-in-pattern').value.trim();
    const replacement = document.getElementById('corr-in-replacement').value.trim();
    const regex       = document.getElementById('corr-in-regex').value === 'true';
    const text        = document.getElementById('corr-in-test').value;
    const el          = document.getElementById('corr-test-result');
    if (!pattern || !text) {
      el.innerHTML = '<span style="color:#484f58;font-style:italic">результат появится здесь...</span>';
      return;
    }
    const r = await apiFetch('/api/corrections/test', {pattern, replacement, regex, text});
    if (r.ok) {
      if (r.changed) {
        el.innerHTML = `<span style="color:#22c55e;font-weight:600">✓ ${esc(r.result)}</span>`;
      } else {
        el.innerHTML = `<span style="color:#f59e0b">≈ без изменений: ${esc(r.result)}</span>`;
      }
    } else {
      el.innerHTML = `<span style="color:#f85149">⚠️ ${esc(r.error)}</span>`;
    }
  }, 250);
}

async function apiFetch(url, body) {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    return await r.json();
  } catch(e) { return {error: e.message}; }
}


// ── Diagnostics ──────────────────────────────────────────────────────────────
let _diagLogPath = '';

async function runDiagnose() {
  const btn      = document.getElementById('diag-run-btn');
  const progress = document.getElementById('diag-progress');
  const results  = document.getElementById('diag-results');
  const info     = document.getElementById('diag-info');

  btn.disabled = true;
  btn.textContent = '⏳';
  progress.style.display = 'block';
  results.style.display  = 'none';
  info.style.display     = 'none';

  const r = await fetch('/api/diagnose').then(x => x.json()).catch(e => ({error: e.message}));

  progress.style.display = 'none';
  btn.disabled    = false;
  btn.textContent = '▶ Run';

  if (r.error) {
    info.style.display   = 'block';
    info.innerHTML = `<span style="color:var(--red)">⚠️ Ошибка: ${esc(r.error)}</span>`;
    return;
  }

  _diagLogPath = r.log_path || '';

  // Summary badge
  const sumEl   = document.getElementById('diag-summary');
  const allOk   = r.ok === true;
  const color   = allOk ? 'var(--green)' : 'var(--red)';
  const icon    = allOk ? '✅' : '❌';
  sumEl.innerHTML = `<span style="color:${color}">${icon} ${esc(r.summary)}</span>`;

  // Items
  const itemsEl = document.getElementById('diag-items');
  itemsEl.innerHTML = (r.items || []).map(item => {
    const ok     = item.status === 'ok';
    const badge  = ok
      ? `<span style="color:var(--green);font-family:monospace;font-size:12px">[  OK  ]</span>`
      : `<span style="color:var(--red);font-family:monospace;font-size:12px">[ FAIL ]</span>`;
    const advice = item.advice
      ? `<div style="color:var(--yellow);font-size:11px;margin-top:2px;padding-left:72px">→ ${esc(item.advice)}</div>`
      : '';
    return `<div style="background:var(--bg3);border-radius:6px;padding:6px 10px;border-left:3px solid ${ok ? 'var(--green)' : 'var(--red)'}">
      <span style="display:inline-flex;align-items:center;gap:8px">${badge}<span style="font-size:13px">${esc(item.label)}</span></span>
      ${advice}
    </div>`;
  }).join('');

  results.style.display = 'block';
}

function openDiagLog() {
  if (_diagLogPath) {
    alert('Лог сохранён:\n' + _diagLogPath + '\n\nОткройте его в любом текстовом редакторе.');
  }
}


init();
</script>
</body>
</html>
"""

# ── Statistics helpers ────────────────────────────────────────────────────────

def _load_stats() -> dict:
    """Load stats JSON from disk. Returns empty stats if file missing.

    Handles key aliasing: whisper-ptt.py writes 'total_transcriptions',
    webui uses 'total_sessions' internally — both refer to the same counter.
    """
    default = {
        "total_words": 0,
        "total_sessions": 0,
        "last_updated": "",
    }
    if not STATS_FILE.exists():
        return default
    try:
        data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
        # Alias: ptt writes total_transcriptions, webui calls it total_sessions
        if "total_transcriptions" in data and "total_sessions" not in data:
            data["total_sessions"] = data["total_transcriptions"]
        elif "total_transcriptions" in data:
            # Take the larger of the two (avoids going backwards on merge)
            data["total_sessions"] = max(data["total_sessions"], data["total_transcriptions"])
        for k, v in default.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return default


def _save_stats(stats: dict):
    """Save stats JSON to disk (C:/whisper-ptt/logs/whisper-stats.json)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stats["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _count_words(text: str) -> int:
    """Count words in a string (splits by whitespace)."""
    return len(text.strip().split()) if text.strip() else 0


def update_stats_from_log() -> dict:
    """
    Parse whisper-ptt.log starting from last known position,
    count new words from transcription lines, persist to JSON.
    Returns the updated stats dict.
    """
    stats = _load_stats()

    # Ищем лог-файлы: сначала PTT лог, потом серверный лог
    log_candidates = [PTT_LOG_FILE, LOG_FILE]
    # Также смотрим логи всех установленных версий
    # All logs are now in C:/whisper-ptt/logs — add them if not already present
    for name in ("whisper-ptt.log", "whisper-ptt-eng.log", "whisper-server.log"):
        p = LOG_DIR / name
        if p not in log_candidates:
            log_candidates.append(p)

    new_words    = 0
    new_sessions = 0

    for log_path in log_candidates:
        if not log_path.exists():
            continue
        try:
            size = log_path.stat().st_size
            pos_key = f"log_pos_{log_path.stem}"
            last_pos = stats.get(pos_key, 0)

            # Если файл был пересоздан (размер меньше позиции) — читаем с начала
            if size < last_pos:
                last_pos = 0

            if size <= last_pos:
                continue  # Ничего нового

            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                for line in f:
                    # Ищем строки с результатом транскрипции PTT
                    m = _PTT_TEXT_RE.search(line)
                    if not m:
                        m = _SERVER_TEXT_RE.search(line)
                    if m:
                        text = m.group(1).strip().rstrip('"').rstrip("'")
                        new_words += _count_words(text)
                        new_sessions += 1
                stats[pos_key] = f.tell()
        except Exception:
            pass

    if new_words > 0 or new_sessions > 0:
        stats["total_words"]    += new_words
        stats["total_sessions"] += new_sessions
        _save_stats(stats)

    return stats


def get_results(n: int = 30) -> dict:
    """Read last N entries from whisper-results.jsonl written by whisper-ptt.py."""
    results_file = LOG_DIR / "whisper-results.jsonl"
    entries = []
    try:
        if results_file.exists():
            lines = results_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines[-n:]):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return {"results": entries, "count": len(entries)}


def get_stats() -> dict:
    """Return stats for API.
    whisper-ptt.py writes directly to STATS_FILE on every transcription,
    so we just read that file. update_stats_from_log is a fallback for
    installations where the file doesn't exist yet.
    """
    # If STATS_FILE exists and was written by whisper-ptt.py, use it directly
    if STATS_FILE.exists():
        try:
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            words = data.get("total_words", 0)
            # PTT writes total_transcriptions; webui uses total_sessions
            sessions = data.get("total_transcriptions", data.get("total_sessions", 0))
            updated = data.get("last_time", data.get("last_updated", "—"))
            return {
                "total_words":    words,
                "total_sessions": sessions,
                "last_updated":   updated,
            }
        except Exception:
            pass
    # Fallback: parse log file
    stats = update_stats_from_log()
    return {
        "total_words":    stats["total_words"],
        "total_sessions": stats["total_sessions"],
        "last_updated":   stats.get("last_updated", "—"),
    }


def reset_stats() -> dict:
    """Reset all stats to zero."""
    empty = {
        "total_words": 0,
        "total_sessions": 0,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "log_position": 0,
    }
    _save_stats(empty)
    return {"ok": True, "message": "Statistics reset (statistika sbroshena)"}


# ── Backend helpers ────────────────────────────────────────────────────────────

def run_ps(cmd: str, timeout: int = 15) -> tuple[bool, str]:
    """Run a PowerShell command, return (success, output)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _scm_control_service(service_name: str, action: str) -> tuple[bool, str]:
    """Control a Windows service using the SCM API directly via ctypes.

    Works from ANY context — service, interactive, Session 0.
    PowerShell Start-Service / Stop-Service fail from service context because
    they rely on WMI which is restricted in Session 0.

    action: "stop" | "start" | "status"
    Returns (success, message).
    """
    import ctypes
    import ctypes.wintypes

    # Win32 constants
    SC_MANAGER_ALL_ACCESS   = 0xF003F
    SERVICE_ALL_ACCESS       = 0xF01FF
    SERVICE_STOP             = 0x0020
    SERVICE_START            = 0x0010
    SERVICE_QUERY_STATUS     = 0x0004
    SERVICE_CONTROL_STOP     = 0x00000001
    SERVICE_STOPPED          = 0x00000001
    SERVICE_RUNNING          = 0x00000004
    SERVICE_START_PENDING    = 0x00000002
    SERVICE_STOP_PENDING     = 0x00000003

    advapi = ctypes.windll.advapi32

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [
            ("dwServiceType",             ctypes.wintypes.DWORD),
            ("dwCurrentState",            ctypes.wintypes.DWORD),
            ("dwControlsAccepted",        ctypes.wintypes.DWORD),
            ("dwWin32ExitCode",           ctypes.wintypes.DWORD),
            ("dwServiceSpecificExitCode", ctypes.wintypes.DWORD),
            ("dwCheckPoint",              ctypes.wintypes.DWORD),
            ("dwWaitHint",                ctypes.wintypes.DWORD),
        ]

    scm = advapi.OpenSCManagerW(None, None, SC_MANAGER_ALL_ACCESS)
    if not scm:
        err = ctypes.get_last_error()
        return False, f"OpenSCManager failed (error {err}) — run WebUI as Administrator"

    svc = advapi.OpenServiceW(scm, service_name, SERVICE_ALL_ACCESS)
    if not svc:
        err = ctypes.get_last_error()
        advapi.CloseServiceHandle(scm)
        return False, f"OpenService({service_name}) failed (error {err})"

    try:
        status = SERVICE_STATUS()

        if action == "status":
            advapi.QueryServiceStatus(svc, ctypes.byref(status))
            state_map = {
                SERVICE_STOPPED:      "Stopped",
                SERVICE_RUNNING:      "Running",
                SERVICE_START_PENDING:"StartPending",
                SERVICE_STOP_PENDING: "StopPending",
            }
            state = state_map.get(status.dwCurrentState, str(status.dwCurrentState))
            return True, state

        elif action == "stop":
            advapi.QueryServiceStatus(svc, ctypes.byref(status))
            if status.dwCurrentState == SERVICE_STOPPED:
                return True, "already stopped"
            ok = advapi.ControlService(svc, SERVICE_CONTROL_STOP, ctypes.byref(status))
            if not ok:
                err = ctypes.get_last_error()
                return False, f"ControlService(STOP) failed (error {err})"
            # Wait for stopped state
            for _ in range(30):
                time.sleep(1)
                advapi.QueryServiceStatus(svc, ctypes.byref(status))
                if status.dwCurrentState == SERVICE_STOPPED:
                    return True, "stopped"
            return False, "stop timeout"

        elif action == "start":
            advapi.QueryServiceStatus(svc, ctypes.byref(status))
            if status.dwCurrentState == SERVICE_RUNNING:
                return True, "already running"
            ok = advapi.StartServiceW(svc, 0, None)
            if not ok:
                err = ctypes.get_last_error()
                return False, f"StartService failed (error {err})"
            # Wait for running state
            for _ in range(30):
                time.sleep(1)
                advapi.QueryServiceStatus(svc, ctypes.byref(status))
                if status.dwCurrentState == SERVICE_RUNNING:
                    return True, "started"
                if status.dwCurrentState == SERVICE_STOPPED:
                    return False, "service stopped unexpectedly after start"
            return False, "start timeout"

        return False, f"unknown action: {action}"

    finally:
        advapi.CloseServiceHandle(svc)
        advapi.CloseServiceHandle(scm)


def get_service_status() -> dict:
    ok, out = run_ps(
        "Get-Service WhisperServer -ErrorAction SilentlyContinue | "
        "Select-Object Status,StartType | ConvertTo-Json"
    )
    if not ok or not out:
        return {"status": "not_installed", "running": False, "startup": "—"}
    try:
        d = json.loads(out)
        status  = str(d.get("Status", "")).lower()
        # Status: 4=Running, 1=Stopped, 2=StartPending, 3=StopPending
        status_map = {"4": "running", "1": "stopped", "2": "start_pending", "3": "stop_pending"}
        status = status_map.get(str(d.get("Status","")), status)
        # StartType: 0=Boot, 1=System, 2=Automatic, 3=Manual, 4=Disabled
        start_type_map = {"0": "Boot", "1": "System", "2": "Automatic",
                          "3": "Manual", "4": "Disabled"}
        raw_start = str(d.get("StartType", ""))
        startup = start_type_map.get(raw_start, raw_start or "—")
        return {"status": status, "running": status == "running", "startup": startup}
    except Exception:
        return {"status": "unknown", "running": False, "startup": "—"}


def get_health() -> dict:
    """Query /health, re-probing the port on each call in case the server moved."""
    global _SERVER_PORT, SERVER_URL
    try:
        # Fast path: try the currently known URL
        resp = urllib.request.urlopen(f"{SERVER_URL}/health", timeout=3)
        return json.loads(resp.read().decode())
    except Exception:
        pass
    # Slow path: server may have restarted on a different port — re-probe
    new_port = _resolve_server_port()
    if new_port != _SERVER_PORT:
        _SERVER_PORT = new_port
        SERVER_URL   = f"http://localhost:{_SERVER_PORT}"
        try:
            resp = urllib.request.urlopen(f"{SERVER_URL}/health", timeout=3)
            return json.loads(resp.read().decode())
        except Exception:
            pass
    return {"error": "offline"}


def get_gpus() -> dict:
    try:
        import torch
        gpus = []
        for i in range(torch.cuda.device_count()):
            name   = torch.cuda.get_device_name(i)
            vram_mb = torch.cuda.get_device_properties(i).total_memory // 1024 // 1024
            vram_gb = round(vram_mb / 1024, 1)
            if   vram_mb >= 9000: opt = "large-v3"
            elif vram_mb >= 6000: opt = "large-v2"
            elif vram_mb >= 3000: opt = "medium"
            elif vram_mb >= 1300: opt = "small"
            else:                 opt = "base"
            gpus.append({"index": i, "name": name, "vram_gb": vram_gb, "optimal_model": opt})

        cur_gpu = 0; cur_model = "large-v2"
        if GPU_CONFIG.exists():
            try:
                cfg = json.loads(GPU_CONFIG.read_text())
                cur_gpu   = cfg.get("gpu_index", 0)
                cur_model = cfg.get("model", "large-v2")
            except Exception:
                pass
        return {"gpus": gpus, "current_gpu": cur_gpu, "current_model": cur_model}
    except ImportError:
        return {"gpus": [], "error": "torch not installed"}
    except Exception as e:
        return {"gpus": [], "error": str(e)}


def get_log(tail: int = 150) -> dict:
    """Read from all available log files and merge, newest lines last."""
    # All possible log locations, priority order
    # All logs live in one place: C:/whisper-ptt/logs/
    log_candidates = [
        LOG_DIR / "whisper-ptt.log",
        LOG_DIR / "whisper-server.log",
        LOG_DIR / "whisper-webui.log",
        LOG_DIR / "whisper-ptt-eng.log",
    ]

    all_lines = []
    found_any = False

    for log_path in log_candidates:
        if not log_path.exists():
            continue
        found_any = True
        try:
            raw = log_path.read_text(encoding="utf-8", errors="replace")
            file_lines = raw.splitlines()
            # Prefix each line with short source tag so user knows which log
            tag = log_path.stem[:12].ljust(12)
            all_lines.extend(f"[{tag}] {ln}" for ln in file_lines[-tail:])
        except Exception as e:
            all_lines.append(f"[ERROR reading {log_path.name}]: {e}")

    if not found_any:
        return {"lines": [
            f"No log files found. Checked:",
            *[f"  {p}" for p in log_candidates],
            "",
            "whisper-ptt.log will appear after first transcription.",
        ]}

    return {"lines": all_lines[-tail:]}


def get_configs() -> dict:
    configs = []
    for d in CONFIG_DIRS:
        cfg = d / "config.toml"
        if cfg.exists():
            configs.append({"path": str(cfg), "label": str(cfg)})
    return {"configs": configs}


def read_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    try:
        return {"content": p.read_text(encoding="utf-8")}
    except Exception as e:
        return {"error": str(e)}


def write_config(path: str, content: str) -> dict:
    p = Path(path)
    if not any(str(p).startswith(str(d)) for d in CONFIG_DIRS):
        return {"error": "Path not allowed (put ne razreshen)"}
    try:
        p.write_text(content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


def get_versions() -> dict:
    versions = []
    defs = [
        ("whisper PTT RU-ENG",   Path("C:/whisper-ptt"),      "whisper-ptt.py"),
        ("whisper PTT ENG-RU",   Path("C:/whisper-ptt-eng"),  "whisper-ptt-eng.py"),
        ("whisper PTT HAOS",     Path("C:/whisper-ptt-haos"), "whisper-ptt.py"),
        ("whisper-server",       Path("C:/whisper-server"),   "whisper-server.py"),
    ]
    for name, d, script in defs:
        installed = (d / script).exists()
        model = ""; device = ""; remote = False
        cfg_path = d / "config.toml"
        if cfg_path.exists():
            try:
                content = cfg_path.read_text(encoding="utf-8", errors="replace")
                import re
                m = re.search(r'model\s*=\s*"([^"]+)"', content)
                if m: model = m.group(1)
                dv = re.search(r'device\s*=\s*"([^"]+)"', content)
                if dv: device = dv.group(1)
                remote = bool(re.search(r'enabled\s*=\s*true', content))
            except Exception:
                pass
        # Check if has service — always use the real service name "WhisperServer"
        ok, out = run_ps("Get-Service WhisperServer -ErrorAction SilentlyContinue | Select-Object Status | ConvertTo-Json")
        has_service = ok and out and "Status" in out
        versions.append({
            "name": name, "path": str(d),
            "installed": installed, "service": has_service,
            "remote": remote, "model": model, "device": device
        })
    return {"versions": versions}


def _kill_whisper_server_process() -> tuple[bool, str]:
    """Kill the whisper-server.py python process.
    NSSM will restart it automatically.
    Works from any Windows context including Session 0 services.
    """
    import subprocess as _sub
    # wmic is the most reliable way to kill by command line from service context
    try:
        r = _sub.run(
            ["wmic", "process", "where",
             "CommandLine like '%whisper-server.py%'",
             "call", "terminate"],
            capture_output=True, text=True, timeout=10
        )
        if "ReturnValue = 0" in r.stdout or "successful" in r.stdout.lower():
            return True, "killed via wmic"
    except Exception:
        pass
    # Fallback: taskkill by window title or image
    try:
        _sub.run(
            ["taskkill", "/F", "/IM", "python.exe", "/FI",
             f"COMMANDLINE eq *whisper-server*"],
            capture_output=True, timeout=10
        )
        return True, "killed via taskkill"
    except Exception:
        pass
    # Fallback: kill by port
    ok, out = run_ps(
        f"$p=(Get-NetTCPConnection -LocalPort {_SERVER_PORT} "
        f"-ErrorAction SilentlyContinue).OwningProcess | Select -First 1;"
        f"if($p){{Stop-Process -Id $p -Force -ErrorAction SilentlyContinue;'ok'}}else{{'notfound'}}",
        timeout=10
    )
    if ok and "ok" in out:
        return True, f"killed PID via port {_SERVER_PORT}"
    return False, "could not find/kill process"


def service_action(action: str) -> dict:
    """Control WhisperServer.
    Stop/Restart: kill the python process (NSSM restarts automatically).
    Start: sc.exe start (NSSM not running yet).
    Enable/Disable autostart: sc.exe config.
    """
    if action == "start":
        # sc.exe works for starting a stopped service from service context
        import subprocess as _sub
        try:
            r = _sub.run(["sc.exe", "start", "WhisperServer"],
                         capture_output=True, text=True, timeout=20)
            ok = r.returncode == 0 or "START_PENDING" in r.stdout or "RUNNING" in r.stdout
        except Exception as e:
            ok, r = False, type("R", (), {"stdout": str(e), "stderr": ""})()
        if not ok:
            # Also try PowerShell
            ok2, out2 = run_ps("Start-Service WhisperServer -ErrorAction SilentlyContinue",
                               timeout=20)
            if ok2:
                ok = True
        return {"ok": ok, "message": "Сервис запускается (starting)" if ok else
                f"Не удалось запустить. Попробуй: sc.exe start WhisperServer"}

    elif action == "stop":
        # Kill process — NSSM will NOT restart if we also disable it first
        # Just kill: service stays stopped (NSSM has restart delay)
        ok, msg = _kill_whisper_server_process()
        # Also tell NSSM to stop so it doesn't restart
        run_ps("sc.exe stop WhisperServer", timeout=15)
        return {"ok": True, "message": "Сервис остановлен (stopped — process killed)"}

    elif action == "restart":
        # Call /shutdown — server process exits cleanly
        shutdown_ok = False
        try:
            urllib.request.urlopen(f"{SERVER_URL}/shutdown", timeout=5)
            shutdown_ok = True
        except Exception as e:
            if "reset" in str(e).lower() or "10054" in str(e) or "RemoteDisconnected" in str(e):
                shutdown_ok = True   # connection reset = сервер вышел нормально
            else:
                _kill_whisper_server_process()  # Fallback: убиваем процесс
                shutdown_ok = True
        # Ждём авторестарт от NSSM (3 сек), потом проверяем и при необходимости запускаем
        if shutdown_ok:
            try:
                time.sleep(3.0)
                chk = subprocess.run(
                    ["sc.exe", "query", "WhisperServer"],
                    capture_output=True, text=True, timeout=5
                )
                already_running = "RUNNING" in chk.stdout or "START_PENDING" in chk.stdout
                if not already_running:
                    subprocess.run(["sc.exe", "start", "WhisperServer"],
                                   capture_output=True, text=True, timeout=15)
            except Exception:
                pass
        return {"ok": True, "message": "Сервис перезапускается (restarting)"}

    elif action == "enable":
        import subprocess as _sub
        try:
            r = _sub.run(["sc.exe", "config", "WhisperServer", "start=", "auto"],
                         capture_output=True, text=True, timeout=10)
            ok = r.returncode == 0
        except Exception:
            ok = False
        return {"ok": ok, "message": "Автозапуск включён" if ok else
                "Не удалось — попробуй: sc.exe config WhisperServer start= auto"}

    elif action == "disable":
        import subprocess as _sub
        try:
            r = _sub.run(["sc.exe", "config", "WhisperServer", "start=", "disabled"],
                         capture_output=True, text=True, timeout=10)
            ok = r.returncode == 0
        except Exception:
            ok = False
        return {"ok": ok, "message": "Автозапуск отключён" if ok else
                "Не удалось — попробуй: sc.exe config WhisperServer start= disabled"}

    elif action == "status":
        return get_service_status()

    return {"error": f"Unknown action: {action}"}


def apply_gpu(gpu_index: int, model: str) -> dict:
    """Apply GPU index + model to WhisperServer and restart it.

    Clean approach: write gpu-config.json, then restart the service.
    whisper-server.py reads gpu-config.json at startup — no NSSM changes needed.
    This works regardless of whether WebUI runs as a service or interactively.
    """
    # Fix #19: validate model against known whitelist to prevent arbitrary string
    # injection into gpu-config.json and config.toml files
    ALLOWED_MODELS = {"tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"}
    if model not in ALLOWED_MODELS:
        return {"error": f"Unknown model: {model}. Allowed: {sorted(ALLOWED_MODELS)}"}

    # Fix #20: compute_type logic — float16 for ALL GPU models (cuda),
    # int8 only on CPU. Using int8 on cuda for small/medium loses quality unnecessarily.
    compute = "float16" if gpu_index >= 0 else "int8"

    # ── Write gpu-config.json — whisper-server.py reads this at next start ────
    cfg = {
        "gpu_index":    gpu_index,
        "model":        model,
        "device":       "cuda",
        "compute_type": compute,
        "port":         _SERVER_PORT,
        "language":     "ru",
    }
    try:
        GPU_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        GPU_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        return {"error": f"Could not save gpu-config.json: {e}"}

    # ── Also update config.toml files for PTT clients ─────────────────────────
    for ptt_dir in CONFIG_DIRS:
        toml_path = ptt_dir / "config.toml"
        if toml_path.exists():
            try:
                import re as _re
                raw = toml_path.read_text(encoding="utf-8", errors="replace")
                raw = _re.sub(r'model\s*=\s*"[^"]*"', f'model = "{model}"', raw, count=1)
                raw = _re.sub(r'compute_type\s*=\s*"[^"]*"', f'compute_type = "{compute}"', raw, count=1)
                toml_path.write_text(raw, encoding="utf-8")
            except Exception:
                pass

    # ── Call /shutdown on the server — it exits cleanly, NSSM restarts it ───
    # This requires NO special permissions — just HTTP to localhost.
    # The server process calls os._exit(0), NSSM sees the exit and restarts.
    # On restart whisper-server.py reads gpu-config.json → loads new model.
    shutdown_ok = False
    shutdown_msg = ""
    try:
        resp = urllib.request.urlopen(
            f"{SERVER_URL}/shutdown", timeout=5
        )
        data = json.loads(resp.read().decode())
        shutdown_ok = data.get("ok", False)
        shutdown_msg = data.get("message", "")
    except Exception as e:
        # ConnectionResetError is expected — server closed connection while exiting
        if "reset" in str(e).lower() or "10054" in str(e) or "RemoteDisconnected" in str(e):
            shutdown_ok = True
            shutdown_msg = "server exited (connection reset — normal)"
        else:
            shutdown_msg = str(e)

    if shutdown_ok:
        # ── Запуск сервиса после shutdown ────────────────────────────────────
        # Стратегия: ждём 3 сек — если NSSM настроен с AppRestartDelay=3000,
        # он сам поднимет сервис. Если через 3 сек сервис всё ещё остановлен —
        # запускаем принудительно через sc.exe start.
        # Это работает и с NSSM, и без него (pure sc.exe service).
        try:
            time.sleep(3.0)
            # Проверяем статус сервиса
            chk = subprocess.run(
                ["sc.exe", "query", "WhisperServer"],
                capture_output=True, text=True, timeout=5
            )
            already_running = "RUNNING" in chk.stdout or "START_PENDING" in chk.stdout
            if not already_running:
                # NSSM не поднял — запускаем принудительно
                subprocess.run(
                    ["sc.exe", "start", "WhisperServer"],
                    capture_output=True, text=True, timeout=10
                )
        except Exception:
            pass

        return {
            "ok": True,
            "message": (
                f"✓ GPU {gpu_index}, модель [{model}] ({compute}) сохранена. "
                f"Сервер перезапускается — новая модель загрузится за ~30 сек. "
                f"(Server restarting with [{model}])"
            )
        }
    else:
        return {
            "ok": False,
            "error": (
                f"gpu-config.json обновлён (модель [{model}]), "
                f"но не удалось вызвать /shutdown: {shutdown_msg}. "
                f"Перезапусти сервис вручную: Restart-Service WhisperServer"
            )
        }



# ── Corrections dictionary ─────────────────────────────────────────────────────

def _load_corrections_raw() -> dict:
    """Загрузить corrections.json целиком. Возвращает dict с ключом 'corrections'."""
    candidates = [
        CORRECTIONS_FILE,
        Path("C:/whisper-ptt-eng/corrections.json"),
        Path(__file__).parent.parent / "whisper-ptt" / "corrections.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {"_version": 1, "corrections": []}


def _save_corrections(data: dict, ptt_dir: str = "C:/whisper-ptt") -> bool:
    """Сохранить corrections.json для конкретной PTT-директории."""
    try:
        path = Path(ptt_dir) / "corrections.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def get_corrections() -> dict:
    """Вернуть весь словарь замен для WebUI."""
    data = _load_corrections_raw()
    corrections = data.get("corrections", [])
    # Добавляем id если отсутствует (для старых файлов)
    for i, c in enumerate(corrections):
        if "id" not in c:
            c["id"] = i + 1
    return {"corrections": corrections, "total": len(corrections)}


def add_correction(pattern: str, replacement: str,
                   is_regex: bool = False, description: str = "",
                   enabled: bool = True) -> dict:
    """Добавить новую запись в словарь."""
    pattern = pattern.strip()
    replacement = replacement.strip()
    if not pattern:
        return {"error": "Pattern cannot be empty"}
    # Validate regex if needed
    if is_regex:
        try:
            import re as _re
            _re.compile(pattern)
        except Exception as e:
            return {"error": f"Invalid regex: {e}"}
    data = _load_corrections_raw()
    corrections = data.get("corrections", [])
    new_id = max((c.get("id", 0) for c in corrections), default=0) + 1
    corrections.append({
        "id": new_id,
        "pattern": pattern,
        "replacement": replacement,
        "regex": is_regex,
        "enabled": enabled,
        "description": description,
    })
    data["corrections"] = corrections
    ok = _save_corrections(data)
    return {"ok": ok, "id": new_id} if ok else {"error": "Failed to save"}


def update_correction(entry_id: int, **kwargs) -> dict:
    """Обновить запись по id."""
    data = _load_corrections_raw()
    corrections = data.get("corrections", [])
    for c in corrections:
        if c.get("id") == entry_id:
            for k, v in kwargs.items():
                if k in ("pattern", "replacement", "regex", "enabled", "description"):
                    c[k] = v
            break
    else:
        return {"error": f"Entry {entry_id} not found"}
    data["corrections"] = corrections
    ok = _save_corrections(data)
    return {"ok": ok} if ok else {"error": "Failed to save"}


def delete_correction(entry_id: int) -> dict:
    """Удалить запись по id."""
    data = _load_corrections_raw()
    before = len(data.get("corrections", []))
    data["corrections"] = [c for c in data.get("corrections", [])
                           if c.get("id") != entry_id]
    if len(data["corrections"]) == before:
        return {"error": f"Entry {entry_id} not found"}
    ok = _save_corrections(data)
    return {"ok": ok} if ok else {"error": "Failed to save"}


def test_correction(pattern: str, replacement: str,
                    is_regex: bool, test_text: str) -> dict:
    """Протестировать замену на примере текста."""
    import re as _re
    try:
        if is_regex:
            result = _re.sub(pattern, replacement, test_text, flags=_re.IGNORECASE)
        else:
            result = _re.sub(_re.escape(pattern), replacement, test_text,
                             flags=_re.IGNORECASE)
        changed = result != test_text
        return {"ok": True, "result": result, "changed": changed}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def run_diagnose() -> dict:
    """Run whisper-ptt.py --diagnose in a subprocess and return structured results.

    Tries to find whisper-ptt.py in all known install locations.
    Returns:
      {ok, items: [{label, status, advice}], summary, log_path, raw}
    """
    # Locate whisper-ptt.py
    candidates = [
        Path("C:/whisper-ptt/whisper-ptt.py"),
        Path("C:/whisper-ptt-eng/whisper-ptt-eng.py"),
        Path(__file__).parent / "whisper-ptt.py",
    ]
    script_path = next((p for p in candidates if p.exists()), None)

    # Find Python
    python_exe = sys.executable
    for p in [
        Path(os.environ.get("LOCALAPPDATA","")) / "Programs/Python/Python313/python.exe",
        Path(os.environ.get("LOCALAPPDATA","")) / "Programs/Python/Python312/python.exe",
        Path(os.environ.get("LOCALAPPDATA","")) / "Programs/Python/Python311/python.exe",
        Path(os.environ.get("LOCALAPPDATA","")) / "Programs/Python/Python310/python.exe",
    ]:
        if p.exists():
            python_exe = str(p)
            break

    if script_path is None:
        return {
            "ok": False,
            "items": [{"label": "whisper-ptt.py", "status": "fail",
                       "advice": "Script not found in C:\\whisper-ptt\\"}],
            "summary": "Diagnostic script not found",
            "log_path": "", "raw": ""
        }

    try:
        proc = subprocess.run(
            [python_exe, str(script_path), "--diagnose"],
            capture_output=True, text=True, timeout=60,
            cwd=str(script_path.parent),
            encoding="utf-8", errors="replace"
        )
        raw = (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return {"ok": False, "items": [], "summary": "Timeout after 60s", "log_path": "", "raw": "TIMEOUT"}
    except Exception as e:
        return {"ok": False, "items": [], "summary": str(e), "log_path": "", "raw": str(e)}

    # Parse output lines: [  OK  ] label  or  [ FAIL ] label
    import re as _re
    items = []
    advice = ""
    for line in raw.splitlines():
        # Arrow lines are advice for the previous FAIL
        if line.strip().startswith("→ "):
            if items:
                items[-1]["advice"] = line.strip()[2:].strip()
            continue
        # Strip ANSI escape codes
        clean = _re.sub(r'\[[0-9;]*m', '', line)
        m_ok   = _re.search(r'\[\s*OK\s*\]\s+(.+)', clean)
        m_fail = _re.search(r'\[\s*FAIL\s*\]\s+(.+)', clean)
        if m_ok:
            items.append({"label": m_ok.group(1).strip(), "status": "ok", "advice": ""})
        elif m_fail:
            items.append({"label": m_fail.group(1).strip(), "status": "fail", "advice": ""})

    total_ok   = sum(1 for i in items if i["status"] == "ok")
    total_fail = sum(1 for i in items if i["status"] == "fail")
    all_ok     = proc.returncode == 0 and total_fail == 0

    # Path to saved report
    log_path = str(script_path.parent / "logs" / "whisper-diagnose.log")

    return {
        "ok":       all_ok,
        "items":    items,
        "summary":  f"{total_ok} OK / {total_fail} FAIL",
        "log_path": log_path,
        "raw":      raw,
    }


def run_script(script: str) -> dict:
    scripts = {
        "switch-gpu": ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                       str(Path("C:/whisper-server/switch-whisper-gpu.ps1"))],
        "manager":    [str(Path("C:/whisper-server/whisper-manager.bat"))],
    }
    if script not in scripts:
        return {"error": f"Unknown script: {script}"}
    try:
        subprocess.Popen(scripts[script], creationflags=subprocess.CREATE_NEW_CONSOLE)
        return {"ok": True, "message": f"Launched: {script}"}
    except Exception as e:
        return {"error": str(e)}


# ── Threaded HTTP Server (each request in its own thread) ────────────────────
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each HTTP request in a separate thread.
    Prevents long-running PowerShell commands (Stop-Service, Restart-Service)
    from blocking the server and causing browser "Failed to fetch" errors.
    """
    daemon_threads = True  # threads die when main process exits

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Silence request logs

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Browser closed connection — normal, not an error

    def send_html(self, html: str):
        try:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Browser closed connection — normal, not an error

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            try: return json.loads(self.rfile.read(length))
            except Exception: pass
        return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self.send_html(HTML)
        elif path == "/api/service/status":
            self.send_json(get_service_status())
        elif path == "/api/health":
            self.send_json(get_health())
        elif path == "/api/gpus":
            self.send_json(get_gpus())
        elif path == "/api/log":
            self.send_json(get_log())
        elif path == "/api/configs":
            self.send_json(get_configs())
        elif path == "/api/config":
            p = params.get("path", [""])[0]
            self.send_json(read_config(p))
        elif path == "/api/versions":
            self.send_json(get_versions())
        elif path == "/api/stats":
            self.send_json(get_stats())
        elif path == "/api/results":
            self.send_json(get_results())
        elif path == "/api/server-port":
            self.send_json({"port": _SERVER_PORT, "url": SERVER_URL})
        # ── Corrections API ──────────────────────────────────────────────────
        elif path == "/api/corrections":
            self.send_json(get_corrections())
        elif path == "/api/diagnose":
            self.send_json(run_diagnose())
        elif path == "/api/corrections/test":
            p = params
            result = test_correction(
                p.get("pattern", [""])[0],
                p.get("replacement", [""])[0],
                p.get("regex", ["false"])[0].lower() == "true",
                p.get("text", [""])[0],
            )
            self.send_json(result)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self.read_body()

        if path.startswith("/api/service/") and path != "/api/service/apply-gpu":
            action = path.split("/")[-1]
            self.send_json(service_action(action))
        elif path == "/api/service/apply-gpu":
            gpu_idx = int(body.get("gpu_index", 0))
            model   = body.get("model", "large-v2")
            self.send_json(apply_gpu(gpu_idx, model))
        elif path == "/api/config":
            self.send_json(write_config(body.get("path",""), body.get("content","")))
        elif path == "/api/run-script":
            self.send_json(run_script(body.get("script","")))
        elif path == "/api/stats/reset":
            self.send_json(reset_stats())
        # ── Corrections API ──────────────────────────────────────────────────
        elif path == "/api/corrections/add":
            self.send_json(add_correction(
                body.get("pattern", ""),
                body.get("replacement", ""),
                bool(body.get("regex", False)),
                body.get("description", ""),
                bool(body.get("enabled", True)),
            ))
        elif path == "/api/corrections/update":
            entry_id = int(body.get("id", 0))
            kwargs = {k: v for k, v in body.items() if k != "id"}
            if "regex" in kwargs:
                kwargs["regex"] = bool(kwargs["regex"])
            if "enabled" in kwargs:
                kwargs["enabled"] = bool(kwargs["enabled"])
            self.send_json(update_correction(entry_id, **kwargs))
        elif path == "/api/corrections/delete":
            self.send_json(delete_correction(int(body.get("id", 0))))
        elif path == "/api/corrections/test":
            self.send_json(test_correction(
                body.get("pattern", ""),
                body.get("replacement", ""),
                bool(body.get("regex", False)),
                body.get("text", ""),
            ))
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    print("=" * 58)
    print("  whisper-webui — whisper_from_sssDeMoNsss")
    print(f"  Web UI  : http://localhost:{PORT}")
    print(f"  Network : http://127.0.0.1:{PORT}")
    print("=" * 58)
    print(f"  Open in browser: http://localhost:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 58)

    # Auto-open browser (skip if running as a Windows service or with --no-browser)
    _skip_browser = ("--no-browser" in sys.argv
                     or not hasattr(sys.stdout, 'isatty')
                     or not sys.stdout.isatty())
    if not _skip_browser:
        def open_browser():
            time.sleep(1.5)
            try:
                import webbrowser
                webbrowser.open(f"http://localhost:{PORT}")
            except Exception:
                pass
        threading.Thread(target=open_browser, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web UI...")
        server.shutdown()


if __name__ == "__main__":
    main()
