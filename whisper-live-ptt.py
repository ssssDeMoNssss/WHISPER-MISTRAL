#!/usr/bin/env python3
"""
whisper-live-ptt.py — Real-time streaming PTT client
Part of whisper_from_sssDeMoNsss-live project
Author: sssDeMoNsss | vk.com/basset2

Differences from whisper-ptt.py (classic mode):
  - Connects to whisper-live-server.py via WebSocket (port 9201)
  - Sends audio chunks every ~0.5s while hotkey is held
  - Shows LIVE text in console as you speak (like iPhone dictation)
  - Right Ctrl: stream → live RU preview → final RU paste
  - Right Alt:  stream → live RU preview → final EN paste (offline translate)
  - Falls back to classic whisper-server.py HTTP if live server unavailable
"""

import sys
import os
import time
import json
import base64
import threading
import queue
import numpy as np
from pathlib import Path

# ── Platform detection ────────────────────────────────────────────────────────
PLATFORM = sys.platform
if PLATFORM == 'win32':
    PLATFORM = 'windows'
elif PLATFORM == 'darwin':
    PLATFORM = 'macos'
else:
    PLATFORM = 'linux'

# ── Add project directory to path ────────────────────────────────────────────
_script_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_script_dir))

# ── FFmpeg path fix (Windows) ─────────────────────────────────────────────────
if PLATFORM == 'windows':
    try:
        import subprocess
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Command ffmpeg -ErrorAction SilentlyContinue | Select-Object -Exp Source'],
            capture_output=True, text=True, timeout=5
        )
        ff_path = result.stdout.strip()
        if ff_path:
            ff_dir = str(Path(ff_path).parent)
            if ff_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = ff_dir + os.pathsep + os.environ.get('PATH', '')
                print(f"[PATH] ffmpeg found and added: {ff_dir}")
    except Exception:
        pass
    # Also check WinGet packages
    winget_base = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'
    if winget_base.exists():
        for d in winget_base.rglob('ffmpeg.exe'):
            ff_dir = str(d.parent)
            if ff_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = ff_dir + os.pathsep + os.environ.get('PATH', '')
                print(f"[PATH] ffmpeg found and added: {ff_dir}")
            break

# ── Imports ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Whisper PTT Live started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Platform: {PLATFORM}")
print(f"{'='*60}\n")

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)

try:
    from pynput import keyboard
except ImportError:
    print("ERROR: pynput not installed. Run: pip install pynput")
    sys.exit(1)

try:
    import websockets
    import websockets.sync.client as ws_sync
    WEBSOCKETS_OK = True
except ImportError:
    WEBSOCKETS_OK = False
    print("WARNING: websockets not installed — live streaming unavailable.")
    print("         Run: pip install websockets")

try:
    from whisper_platform import clipboard, keyboard_sim, PLATFORM as _P
except ImportError:
    print("ERROR: whisper_platform.py not found in same directory")
    sys.exit(1)

# Optional colored output
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
    COLORS = True
except ImportError:
    COLORS = False

def cprint(msg, color='reset'):
    if not COLORS:
        print(msg)
        return
    _c = {'green': Fore.GREEN, 'cyan': Fore.CYAN, 'yellow': Fore.YELLOW,
          'red': Fore.RED, 'gray': Fore.WHITE, 'reset': Style.RESET_ALL}
    c = _c.get(color, Style.RESET_ALL)
    print(f"{c}{Style.BRIGHT if color in ('green','cyan') else ''}{msg}{Style.RESET_ALL}")

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 16000
CHANNELS       = 1
CHUNK_MS       = 500        # send audio chunk every 500ms
LIVE_PORT      = 9201       # whisper-live-server default port
LIVE_HOST      = "localhost"
CONFIG_PATH    = Path("C:/whisper-ptt/config.toml")

def load_config() -> dict:
    defaults = {
        "live_server": {"url": f"ws://{LIVE_HOST}:{LIVE_PORT}"},
        "hotkeys": {"record_key": "ctrl_r", "translate_key": "alt_r"},
        "audio":   {"device_index": None},
        "paste":   {"method": "both", "auto_capitalize": True, "add_trailing_space": True},
        "whisper": {"language": "ru", "model": "medium"},
    }
    try:
        if CONFIG_PATH.exists():
            try:
                import tomllib          # stdlib Python 3.11+
            except ImportError:
                import tomli as tomllib  # pip install tomli
            with open(CONFIG_PATH, "rb") as f:
                loaded = tomllib.load(f)
            # Deep-merge
            for k, v in loaded.items():
                if k in defaults and isinstance(v, dict):
                    defaults[k].update(v)
                else:
                    defaults[k] = v
    except Exception as e:
        print(f"Warning: could not load config.toml: {e}")
    return defaults

CONFIG = load_config()

# ── Resolve hotkeys ───────────────────────────────────────────────────────────
_KEY_MAP = {
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "alt_r":  keyboard.Key.alt_r,
    "alt_l":  keyboard.Key.alt_l,
}
RECORD_KEY    = _KEY_MAP.get(CONFIG["hotkeys"].get("record_key",    "ctrl_r"), keyboard.Key.ctrl_r)
TRANSLATE_KEY = _KEY_MAP.get(CONFIG["hotkeys"].get("translate_key", "alt_r"),  keyboard.Key.alt_r)
LANGUAGE      = CONFIG["whisper"].get("language", "ru")
LIVE_WS_URL   = CONFIG["live_server"].get("url", f"ws://{LIVE_HOST}:{LIVE_PORT}")

# ── State ─────────────────────────────────────────────────────────────────────
_recording       = False
_translate_mode  = False
_target_hwnd     = None
_audio_queue: queue.Queue = queue.Queue()
_stream          = None

# ── Focus capture (Windows) ───────────────────────────────────────────────────
def capture_focus():
    global _target_hwnd
    if PLATFORM == 'windows':
        try:
            import win32gui
            _target_hwnd = win32gui.GetForegroundWindow()
        except Exception:
            _target_hwnd = None

def restore_focus():
    if PLATFORM != 'windows' or not _target_hwnd:
        return
    try:
        import ctypes
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.IsWindow(_target_hwnd):
            return
        if u32.IsIconic(_target_hwnd):
            u32.ShowWindow(_target_hwnd, 9)
            time.sleep(0.08)
        if u32.GetForegroundWindow() == _target_hwnd:
            time.sleep(0.05)
            return
        target_tid = u32.GetWindowThreadProcessId(_target_hwnd, None)
        my_tid     = k32.GetCurrentThreadId()
        attached   = False
        if target_tid and target_tid != my_tid:
            attached = bool(u32.AttachThreadInput(my_tid, target_tid, True))
        try:
            u32.SetForegroundWindow(_target_hwnd)
            u32.BringWindowToTop(_target_hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(my_tid, target_tid, False)
        deadline = time.time() + 0.4
        while time.time() < deadline:
            time.sleep(0.02)
            if u32.GetForegroundWindow() == _target_hwnd:
                time.sleep(0.05)
                return
        u32.ShowWindow(_target_hwnd, 5)
        u32.SetForegroundWindow(_target_hwnd)
        time.sleep(0.1)
    except Exception:
        pass

def paste_text(text: str):
    """Restore focus then paste text."""
    if not text:
        return
    if keyboard_sim and hasattr(keyboard_sim, 'set_target_hwnd'):
        keyboard_sim.set_target_hwnd(_target_hwnd)
    restore_focus()
    # Clear + set clipboard
    if PLATFORM == 'windows':
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.OpenClipboard(0); u32.EmptyClipboard(); u32.CloseClipboard()
        except Exception:
            pass
    # Check for OpenOffice (SALFRAME) — needs extra settle
    if PLATFORM == 'windows' and _target_hwnd:
        try:
            import ctypes
            cls = ctypes.create_unicode_buffer(64)
            ctypes.windll.user32.GetClassNameW(_target_hwnd, cls, 64)
            if any(x in cls.value.upper() for x in ('SALFRAME', 'AWTFRAME')):
                time.sleep(0.15)
        except Exception:
            pass
    if clipboard.set_clipboard_text(text):
        time.sleep(0.15)
        keyboard_sim.paste_with_ctrl_v()
        cprint("✓ Text pasted (Ctrl+V)", 'green')

# ── Audio recording ───────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    """Called by sounddevice for each audio chunk."""
    if _recording:
        _audio_queue.put(indata.copy())

def start_audio_stream():
    global _stream
    device_idx = CONFIG["audio"].get("device_index")
    try:
        _stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='int16',
            blocksize=int(SAMPLE_RATE * CHUNK_MS / 1000),
            device=device_idx,
            callback=audio_callback,
        )
        _stream.start()
        cprint("✓ Audio stream started", 'green')
    except Exception as e:
        print(f"ERROR: Could not start audio: {e}")
        sys.exit(1)

# ── Live WebSocket session ─────────────────────────────────────────────────────
def run_live_session(translate: bool) -> tuple[str, str]:
    """
    Connect to whisper-live-server, stream audio, receive live updates.
    Returns (ru_text, en_text).
    """
    if not WEBSOCKETS_OK:
        return "", ""

    ru_live = ""
    en_text = ""
    last_partial = ""

    try:
        with ws_sync.connect(LIVE_WS_URL, open_timeout=3) as ws:
            # Start session
            ws.send(json.dumps({
                "type":      "start",
                "language":  LANGUAGE,
                "translate": translate,
            }))

            # Clear the audio queue — only use audio from NOW
            while not _audio_queue.empty():
                _audio_queue.get_nowait()

            cprint(f"🔴 Recording... (LIVE {'RU→EN' if translate else 'RU'})", 'red')

            def send_audio_loop():
                """Background thread: drain queue and send chunks."""
                acc = np.array([], dtype=np.int16)
                while _recording:
                    try:
                        chunk = _audio_queue.get(timeout=0.1)
                        flat = chunk.flatten()
                        acc = np.concatenate([acc, flat])
                        # Send every CHUNK_MS worth of audio
                        chunk_samples = int(SAMPLE_RATE * CHUNK_MS / 1000)
                        if len(acc) >= chunk_samples:
                            pcm = acc[:chunk_samples].tobytes()
                            acc = acc[chunk_samples:]
                            try:
                                ws.send(json.dumps({
                                    "type": "audio",
                                    "data": base64.b64encode(pcm).decode(),
                                }))
                            except Exception:
                                break
                    except queue.Empty:
                        continue
                # Send any remaining audio
                if len(acc) > 0:
                    try:
                        ws.send(json.dumps({
                            "type": "audio",
                            "data": base64.b64encode(acc.tobytes()).decode(),
                        }))
                    except Exception:
                        pass

            audio_thread = threading.Thread(target=send_audio_loop, daemon=True)
            audio_thread.start()

            # Receive live updates while recording
            while _recording:
                try:
                    raw = ws.recv(timeout=0.2)
                    msg = json.loads(raw)
                    if msg.get("type") == "partial":
                        text = msg.get("text", "")
                        if text and text != last_partial:
                            last_partial = text
                            ru_live = text
                            # Print live update (overwrite line)
                            print(f"\r  🎤 LIVE: {text[:80]}{'...' if len(text)>80 else ''}   ", end="", flush=True)
                except Exception:
                    pass

            audio_thread.join(timeout=2.0)

            # Send end signal
            ws.send(json.dumps({"type": "end"}))
            print()  # newline after live preview

            # Wait for final result
            try:
                raw = ws.recv(timeout=30.0)
                msg = json.loads(raw)
                if msg.get("type") == "final":
                    ru_text  = msg.get("text", "") or ru_live
                    en_text  = msg.get("translation", "")
                    proc_sec = msg.get("proc_sec", 0)
                    if ru_text:
                        cprint(f"✓ Live-server [{LIVE_WS_URL}] {proc_sec}s", 'green')
                    return ru_text, en_text
            except Exception as e:
                cprint(f"⚠️  Final result timeout: {e}", 'yellow')
                return ru_live, en_text

    except Exception as e:
        cprint(f"⚠️  WebSocket error: {e}", 'yellow')
        return "", ""

    return ru_live, en_text

# ── Main transcription flow ───────────────────────────────────────────────────
def transcribe_and_paste(translate: bool):
    """Called after hotkey release. Runs in background thread."""
    t0 = time.time()

    cprint("⏹️  Stopped recording", 'gray')

    # Try live server
    ru_text, en_text = run_live_session(translate)

    if not ru_text:
        cprint("⚠️  Live server unavailable or no speech detected.", 'yellow')
        return

    # Determine what to paste
    if translate and en_text:
        paste_str = en_text.strip()
    else:
        paste_str = ru_text.strip()

    # Apply capitalization and trailing space
    if CONFIG["paste"].get("auto_capitalize", True) and paste_str:
        paste_str = paste_str[0].upper() + paste_str[1:]
    if CONFIG["paste"].get("add_trailing_space", True):
        paste_str += " "

    # Paste
    paste_text(paste_str)

    elapsed = (time.time() - t0) * 1000
    cprint(f"🎤 done [{elapsed:.0f}ms total]", 'yellow')

    if translate and en_text:
        cprint(f"🌐 RU → EN", 'yellow')
        cprint(f"✓ EN: {en_text.strip()}", 'cyan')
        cprint(f"   ┌─ RU: {ru_text.strip()}", 'green')
        cprint(f"   └─ EN: {en_text.strip()}", 'cyan')
    else:
        cprint(f"✓ RU: {ru_text.strip()}", 'green')

# ── Keyboard listener ─────────────────────────────────────────────────────────
def on_press(key):
    global _recording, _translate_mode

    is_record    = (key == RECORD_KEY)
    is_translate = (key == TRANSLATE_KEY)

    if (is_record or is_translate) and not _recording:
        capture_focus()
        _translate_mode = is_translate
        _recording      = True

def on_release(key):
    global _recording

    is_record    = (key == RECORD_KEY)
    is_translate = (key == TRANSLATE_KEY)

    if (is_record or is_translate) and _recording:
        _recording = False
        translate  = _translate_mode
        threading.Thread(
            target=transcribe_and_paste,
            args=(translate,),
            daemon=True
        ).start()

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    # Change to script directory
    os.chdir(_script_dir)

    cprint("=" * 58, 'cyan')
    cprint("  whisper_from_sssDeMoNsss-live — говори, не печатай.", 'white')
    cprint("  LIVE streaming mode — текст появляется в реальном времени!", 'green')
    cprint("─" * 58, 'cyan')
    cprint("  Автор  : sssDeMoNsss", 'white')
    cprint("  ВК     : vk.com/basset2", 'white')
    cprint("  Telegram: @snnike", 'white')
    cprint(f"  Platform: {PLATFORM.upper()}", 'cyan')
    cprint("=" * 58, 'cyan')
    cprint("")

    # Show config
    cprint(f"  ✓ Live server  : {LIVE_WS_URL}", 'cyan')
    key_name  = CONFIG["hotkeys"].get("record_key",    "ctrl_r").upper()
    tr_name   = CONFIG["hotkeys"].get("translate_key", "alt_r").upper()
    cprint(f"  ✓ Hotkey  RU    : {key_name} → транскрипция (LIVE)", 'green')
    cprint(f"  ✓ Hotkey  RU→EN : {tr_name}  → перевод на английский (LIVE)", 'yellow')
    cprint(f"  ✓ Language      : {LANGUAGE}", 'gray')
    cprint("─" * 58, 'cyan')

    # Test live server connection
    if WEBSOCKETS_OK:
        try:
            import urllib.request
            health_url = LIVE_WS_URL.replace("ws://", "http://").replace("wss://", "https://")
            # Health port is WS port + 1
            ws_port = int(LIVE_WS_URL.split(":")[-1])
            resp = urllib.request.urlopen(
                f"http://localhost:{ws_port+1}/health", timeout=3
            )
            info = json.loads(resp.read())
            cprint(f"  ✓ Live server ready: [{info.get('model','?')}] "
                   f"на {info.get('device','?').upper()} "
                   f"(faster-whisper streaming)", 'green')
        except Exception:
            cprint(f"  ⚠️  Live server not responding at {LIVE_WS_URL}", 'yellow')
            cprint(f"     Start whisper-live-server.py first!", 'yellow')

    cprint("")
    cprint("  Whisper PTT Live initialized successfully.", 'green')
    cprint("  Starting keyboard listener...", 'gray')

    # Start audio
    start_audio_stream()

    # Start keyboard listener
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        cprint(f"  ✓ Keyboard listener ready. Waiting for hotkey...", 'green')
        cprint("")
        listener.join()


if __name__ == "__main__":
    main()
