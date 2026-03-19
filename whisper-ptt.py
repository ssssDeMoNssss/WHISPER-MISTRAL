#!/usr/bin/env python3
"""
Whisper Push-to-Talk Voice Typing
Replicates Windows Win+H functionality with local Whisper transcription
Supports both Linux and Windows platforms
"""

import os
import sys
import signal

# ── Windows console encoding fix ─────────────────────────────────────────────
# Forces Python to use UTF-8 for stdout/stderr so Russian text displays correctly.
# chcp 65001 is handled in whisper-ptt-launcher.bat — NOT here, because calling
# subprocess inside the Python process breaks pynput global keyboard hooks.
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONUTF8', '1')
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────────────────

# ── FFmpeg PATH fix ──────────────────────────────────────────────────────────
# openai-whisper calls ffmpeg via subprocess during transcription.
# If ffmpeg is not in process PATH → [WinError 2] "The system cannot find the file".
# We search all known locations including WinGet versioned install paths.
def _find_and_add_ffmpeg():
    import os as _os

    _search = [
        r'C:\ffmpeg\bin',
        r'C:\ProgramData\chocolatey\bin',
        r'C:\tools\ffmpeg\bin',
        r'C:\Program Files\ffmpeg\bin',
        r'C:\Program Files (x86)\ffmpeg\bin',
    ]

    # WinGet installs ffmpeg to a versioned subdirectory — search dynamically
    _localappdata = _os.environ.get('LOCALAPPDATA', '')
    _winget_base = _os.path.join(_localappdata, 'Microsoft', 'WinGet', 'Packages')
    if _os.path.isdir(_winget_base):
        try:
            for _entry in _os.listdir(_winget_base):
                if _entry.lower().startswith('gyan.ffmpeg'):
                    _pkg_dir = _os.path.join(_winget_base, _entry)
                    for _root, _dirs, _files in _os.walk(_pkg_dir):
                        if 'ffmpeg.exe' in _files:
                            _search.insert(0, _root)
                            break
        except Exception:
            pass

    _current = _os.environ.get('PATH', '')
    for _fp in _search:
        if _os.path.isfile(_os.path.join(_fp, 'ffmpeg.exe')) and _fp not in _current:
            _os.environ['PATH'] = _fp + _os.pathsep + _current
            print(f"[PATH] ffmpeg found and added: {_fp}")
            return

_find_and_add_ffmpeg()
del _find_and_add_ffmpeg
# ────────────────────────────────────────────────────────────────────────────

# Suppress ONNX runtime warnings about GPU discovery
os.environ['ORT_LOGGING_LEVEL'] = '3'  # Only show errors
import wave
import tempfile
import threading
import time
import subprocess
import re
import json
from pathlib import Path
from typing import Optional

# ── Colorama for colored console output ──────────────────────────────────────
try:
    from colorama import init as colorama_init, Fore, Style, Back
    colorama_init(autoreset=True)
    _C = {
        'red':    Fore.RED + Style.BRIGHT,
        'green':  Fore.GREEN + Style.BRIGHT,
        'yellow': Fore.YELLOW + Style.BRIGHT,
        'cyan':   Fore.CYAN + Style.BRIGHT,
        'blue':   Fore.BLUE + Style.BRIGHT,
        'magenta':Fore.MAGENTA + Style.BRIGHT,
        'white':  Fore.WHITE + Style.BRIGHT,
        'gray':   Fore.WHITE,
        'reset':  Style.RESET_ALL,
    }
    COLORS = True
except ImportError:
    _C = {k: '' for k in ['red','green','yellow','cyan','blue','magenta','white','gray','reset']}
    COLORS = False

def cprint(msg, color='reset'):
    print(f"{_C.get(color,'')}{msg}{_C['reset']}")

# Import platform-specific modules
try:
    from whisper_platform import PLATFORM, clipboard, keyboard_sim, notifications, autostart
except ImportError as e:
    print(f"ERROR: Failed to import platform modules: {e}")
    sys.exit(1)

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # fallback for Python < 3.11
    except ImportError:
        print("ERROR: Please install tomli: pip install tomli")
        sys.exit(1)

try:
    import sounddevice as sd
    import numpy as np
    import whisper
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: Missing required package: {e}")
    print("Please ensure all packages are installed in your virtualenv:")
    print("  pip install openai-whisper sounddevice numpy pynput")
    sys.exit(1)


# Try to import optional dependencies
try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("WARNING: pystray not available. Tray indicator disabled.")
    print("  Install with: pip install pystray pillow")


class Config:
    """Configuration manager for Whisper PTT"""
    
    def __init__(self, config_path: Optional[Path] = None):
        # Config search order:
        # 1. Script directory (C:\whisper-ptt\config.toml)  <-- приоритет
        # 2. Platform-specific user directory (APPDATA / .config) <-- fallback
        script_dir_config = Path(__file__).parent / "config.toml"

        if PLATFORM == 'windows':
            user_config = Path(os.environ.get('APPDATA', Path.home())) / "whisper-ptt" / "config.toml"
        else:
            user_config = Path.home() / ".config" / "whisper-ptt" / "config.toml"

        # Prefer config.toml next to the script
        if script_dir_config.exists():
            self.DEFAULT_CONFIG_PATH = script_dir_config
        else:
            self.DEFAULT_CONFIG_PATH = user_config
        
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = self._load_config()
        
    def _load_config(self) -> dict:
        """Load configuration from TOML file"""
        if not self.config_path.exists():
            print(f"WARNING: Config file not found at {self.config_path}")
            print("Using default configuration.")
            return self._get_defaults()

        try:
            # Read as text to normalize line endings (tomllib chokes on \r from CRLF files)
            raw = self.config_path.read_text(encoding='utf-8', errors='replace')
            raw = raw.replace('\r\n', '\n').replace('\r', '\n')
            config = tomllib.loads(raw)
            print(f"✓ Loaded configuration from {self.config_path}")
            return config
        except Exception as e:
            print(f"ERROR: Failed to load config: {e}")
            print("Using default configuration.")
            return self._get_defaults()
    
    def _get_defaults(self) -> dict:
        """Return default configuration"""
        return {
            'hotkey': {'key': 'ctrl_r'},
            'whisper': {
                'model': 'base.en',
                'language': 'en',
                'device': 'cpu',
                'compute_type': 'int8',
                'vad_filter': True,
                'vad_min_silence_duration_ms': 500
            },
            'audio': {
                'sample_rate': 16000,
                'channels': 1,
                'device_index': None,
                'device_name': None
            },
            'paste': {
                'method': 'both',
                'add_trailing_space': True,
                'auto_capitalize': True
            },
            'notifications': {
                'enabled': True,
                'show_recording': False,
                'show_transcribing': True,
                'show_result': False
            },
            'tray': {
                'enabled': True
            }
        }
    
    def get(self, *keys, default=None):
        """Get nested config value"""
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key, default)
            else:
                return default
        return value if value is not None else default


class NotificationManager:
    """Handle desktop notifications (platform-abstracted)"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        # Use platform-specific notification manager
        self._notifier = notifications.NotificationManager(enabled=enabled)
    
    def notify(self, title: str, message: str, urgency: str = "normal"):
        """Send desktop notification"""
        self._notifier.notify(title, message, urgency)


class TrayIndicator:
    """System tray indicator for PTT status with transcription history."""

    MAX_HISTORY = 20  # максимум записей в истории трея

    def __init__(self):
        self.icon  = None
        self.state = "idle"  # idle, recording, transcribing
        self._ptt_ref = None  # ссылка на WhisperPTT для повторной вставки
        self._history: list[str] = []  # последние MAX_HISTORY транскрипций

    # ── Public API ────────────────────────────────────────────────────────────

    def set_ptt(self, ptt_instance):
        """Сохраняем ссылку на WhisperPTT для повторной вставки из истории."""
        self._ptt_ref = ptt_instance

    def add_to_history(self, text: str):
        """Добавить транскрипцию в историю трея (вызывается после каждой вставки)."""
        if not text or not text.strip():
            return
        clean = text.strip()
        # Дедупликация — не добавляем если последняя запись та же
        if self._history and self._history[-1] == clean:
            return
        self._history.append(clean)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

    def create_icon(self) -> 'Icon':
        """Create tray icon."""
        if not TRAY_AVAILABLE:
            return None
        image = self._create_image("gray")
        self.icon = Icon("whisper-ptt", image, "Whisper PTT",
                         self._build_menu())
        return self.icon

    def update_state(self, state: str):
        """Update tray icon color and menu."""
        if not self.icon:
            return
        self.state = state
        color_map = {
            'idle': 'gray',
            'recording': 'red',
            'transcribing': 'yellow'
        }
        self.icon.icon = self._create_image(color_map.get(state, 'gray'))
        self.icon.menu = self._build_menu()

    def refresh_menu(self):
        """Обновить меню без смены состояния (после добавления в историю)."""
        if self.icon:
            self.icon.menu = self._build_menu()

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_menu(self):
        """Собрать меню трея с текущим статусом и историей."""
        status_text = f'Status: {self.state.capitalize()}'

        items = [
            MenuItem('Whisper PTT', lambda: None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(status_text, lambda: None, enabled=False),
            Menu.SEPARATOR,
        ]

        # ── История транскрипций ──────────────────────────────────────────────
        if self._history:
            history_items = []
            # Показываем в обратном порядке — последняя сверху
            for text in reversed(self._history):
                label = text[:60] + ('…' if len(text) > 60 else '')
                # Замыкание: копируем text в default-аргумент чтобы не захватить loop var
                def make_paste(t):
                    def _paste_action(icon, item):
                        if self._ptt_ref:
                            import threading
                            threading.Thread(
                                target=self._paste_history_item,
                                args=(t,), daemon=True
                            ).start()
                    return _paste_action
                history_items.append(MenuItem(label, make_paste(text)))

            # Добавляем подменю "История"
            items.append(MenuItem(
                f'📋 История ({len(self._history)})',
                Menu(*history_items)
            ))
            items.append(MenuItem('🗑 Очистить историю', self._clear_history))
            items.append(Menu.SEPARATOR)

        items.append(MenuItem('Quit', self._quit))
        return Menu(*items)

    def _paste_history_item(self, text: str):
        """Повторно вставить текст из истории в активное окно."""
        if not self._ptt_ref:
            return
        try:
            import time
            ptt = self._ptt_ref
            # Небольшая задержка чтобы трей-меню успело закрыться
            time.sleep(0.3)
            paste_text = text
            if ptt.config.get('paste', 'add_trailing_space', default=True):
                paste_text = paste_text + ' '
            ptt._paste_text(paste_text)
            cprint(f"📋 History re-paste: {text[:60]}", 'cyan')
        except Exception as e:
            cprint(f"⚠️  History paste error: {e}", 'yellow')

    def _clear_history(self, icon=None, item=None):
        """Очистить историю транскрипций."""
        self._history.clear()
        self.refresh_menu()
        cprint("🗑 Tray history cleared", 'gray')

    def _create_image(self, color: str):
        """Create icon image with specified color."""
        size = 64
        image = Image.new('RGB', (size, size), 'white')
        dc = ImageDraw.Draw(image)
        dc.ellipse([8, 8, size-8, size-8], fill=color, outline='black', width=2)
        return image

    def _quit(self, icon=None, item=None):
        """Quit the application."""
        if self.icon:
            self.icon.stop()
        os._exit(0)

    def run(self):
        """Run tray icon (blocking)."""
        if self.icon:
            self.icon.run()





class RemoteTranscriber:
    """
    Sends audio to a remote whisper-server HTTP endpoint for transcription.
    Falls back to local model if remote is unavailable or times out.

    After MAX_TRANSCRIBE_FAILURES consecutive transcription failures the remote
    is disabled for the entire session — no more connection attempts, no more
    timeout delays. Restart the program to re-enable.
    """

    MAX_TRANSCRIBE_FAILURES = 3   # disable remote after this many consecutive timeouts
    MAX_SERVER_ERRORS = 1         # disable immediately on HTTP 4xx/5xx (server is broken)
    _BACKOFF = [10, 20, 30]       # seconds between health-check retries (fast reconnect after model change)

    def __init__(self, url: str, timeout: int = 30, language: str = "ru"):
        self.url                = url.rstrip("/")
        self.timeout            = timeout
        self.language           = language
        self._available: Optional[bool] = None
        self._last_check        = 0.0
        self._health_fail_count = 0   # consecutive /health failures
        self._transcribe_fails  = 0   # consecutive /transcribe failures
        self._session_disabled  = False  # True = skip remote for rest of session
        self._last_known_model  = None   # last model reported by /health (model_loaded=True)
        self._was_available     = None   # track transitions online↔offline
        self._loading_model     = None   # model being loaded (model_loaded=False)
        self._loading_msg_shown = False  # avoid repeating "loading..." every 5 sec
        self._loading_start     = 0.0   # when loading started (for elapsed time)
        self._loading_dots      = 0     # dot counter for progress animation
        self._transcribing      = False  # True while a transcription request is in flight
        self._consecutive_fails = 0      # consecutive health check failures (require 2 before offline)

    def _check_health(self) -> bool:
        """Return False immediately if session-disabled.
        Otherwise check /health and require model_loaded=true.

        Key improvements vs naive implementation:
        - While a transcription is in flight (_transcribing=True), skip the
          health check entirely — the server is busy and may not respond to
          /health within timeout, causing a false "offline" warning.
        - Require 2 consecutive failures before marking server offline.
          A single timeout during heavy load should not trigger the warning.
        - Health check timeout increased to 10s (server may be loading model
          or busy with a long transcription).
        """
        if self._session_disabled:
            return False

        # Skip health check while transcription is in flight — server is busy
        # and /health may time out even though transcription will succeed.
        if getattr(self, '_transcribing', False):
            return self._available if self._available is not None else True

        import urllib.request
        now = time.time()
        cooldown = self._BACKOFF[min(self._health_fail_count, len(self._BACKOFF)) - 1] \
            if self._health_fail_count > 0 else 30
        if now - self._last_check < cooldown and self._available is not None:
            return self._available
        try:
            req = urllib.request.urlopen(f"{self.url}/health", timeout=10)  # was 5s
            if req.status == 200:
                body = json.loads(req.read().decode("utf-8"))
                model_loaded = bool(body.get("model_loaded", False))
                server_model = body.get("model", "?")
                device       = body.get("device", "?")
                backend      = body.get("backend", "?")
                self._available = model_loaded

                if model_loaded:
                    # Reset loading state
                    self._loading_model     = None
                    self._loading_msg_shown = False
                    self._loading_dots      = 0

                    # Transition: was offline/loading → now ready
                    if self._was_available is not True:
                        if self._last_known_model is None:
                            # First time we see the server → normal startup, no fanfare
                            cprint(
                                f"✓ Удалённый сервер готов: [{server_model}] "
                                f"на {device.upper()} ({backend})",
                                'green'
                            )
                            self._write_event(
                                event_type="server_ready",
                                message=f"✅ Сервер подключён: [{server_model}] на {device.upper()} ({backend})",
                                new_model=server_model,
                                device=device,
                            )
                        elif self._last_known_model != server_model:
                            # Model actually changed
                            cprint(
                                f"🔄 Модель изменена: [{self._last_known_model}] → [{server_model}] "
                                f"на {device.upper()} — переключаемся на сервер",
                                'yellow'
                            )
                            elapsed_r = int(time.time() - getattr(self, '_restart_start', time.time()))
                            self._write_event(
                                event_type="model_changed",
                                message=f"✅ Модель изменена: [{self._last_known_model}] → [{server_model}] на {device.upper()}",
                                old_model=self._last_known_model or "",
                                new_model=server_model,
                                device=device,
                                elapsed_sec=elapsed_r,
                            )
                        else:
                            # Same model came back (restart without model change)
                            cprint(
                                f"✓ Сервер перезапущен: [{server_model}] на {device.upper()} "
                                f"— готов к работе",
                                'green'
                            )
                            elapsed_r = int(time.time() - getattr(self, '_restart_start', time.time()))
                            self._write_event(
                                event_type="server_restarted",
                                message=f"✅ Сервер перезапущен: [{server_model}] на {device.upper()} — готов к работе",
                                new_model=server_model,
                                device=device,
                                elapsed_sec=elapsed_r,
                            )
                        cprint(
                            f"  (Remote ready: [{server_model}] on {device.upper()}, "
                            f"using server for transcription)",
                            'cyan'
                        )
                    elif self._last_known_model not in (None, server_model):
                        # Server was online, model changed while we weren't looking
                        cprint(
                            f"🔄 Модель сервера изменилась: "
                            f"[{self._last_known_model}] → [{server_model}] "
                            f"на {device.upper()}",
                            'yellow'
                        )

                    self._last_known_model = server_model

                else:
                    # model_loaded=False — server is starting/reloading
                    is_model_change = (
                        self._last_known_model is not None and
                        self._last_known_model != server_model
                    )

                    if is_model_change:
                        # Show "loading new model" message once, then dots
                        if not self._loading_msg_shown or self._loading_model != server_model:
                            self._loading_model     = server_model
                            self._loading_msg_shown = True
                            self._loading_start     = now
                            self._loading_dots      = 0
                            cprint(
                                f"⏳ Загружается новая модель [{server_model}]...",
                                'yellow'
                            )
                            cprint(
                                f"  (Loading model [{server_model}] — please wait)",
                                'cyan'
                            )
                        else:
                            # Animate dots to show progress without spamming
                            elapsed = int(now - self._loading_start)
                            self._loading_dots = (self._loading_dots + 1) % 4
                            dots = "." * (self._loading_dots + 1)
                            print(
                                f"\r  ⏳ [{server_model}] загружается{dots} {elapsed}с",
                                end="", flush=True
                            )
                    # If model_loaded=False but model NOT changed — normal startup, stay quiet
                    # (avoid false "restarting" messages on every health check)

            else:
                self._available = False
        except Exception:
            self._available = False

        self._last_check = now

        # Track consecutive failures — require 2 before triggering offline
        if not self._available:
            self._consecutive_fails = getattr(self, '_consecutive_fails', 0) + 1
            self._health_fail_count += 1
        else:
            self._consecutive_fails = 0

        # Log transition: was available → now not (only after 2 consecutive fails)
        if (not self._available
                and self._was_available is True
                and self._consecutive_fails >= 2):
            if self._last_known_model is not None:
                # Сервер был рабочим с известной моделью — скорее всего идёт смена модели
                cprint(
                    f"\n🔄 Сервер [{self._last_known_model}] перезапускается — возможно смена модели...",
                    'yellow'
                )
                cprint(
                    f"   Ожидаем подключения... (Waiting for server to come back...)",
                    'cyan'
                )
                self._restart_start = time.time()
                self._restart_dots  = 0
                self._write_event(
                    event_type="restart_begin",
                    message=f"Сервер [{self._last_known_model}] перезапускается — ожидаем загрузку новой модели...",
                    old_model=self._last_known_model or "",
                )
            else:
                cprint(
                    f"\n⚠️  Сервер недоступен — временно используем локальную модель. "
                    f"(Remote offline — using local model temporarily)",
                    'yellow'
                )
            self._loading_msg_shown = False
            self._loading_dots      = 0

        # Only update _was_available after confirming 2 consecutive failures
        if self._available or self._consecutive_fails >= 2:
            self._was_available = self._available

        # While server is offline but was previously known — animate dots so user
        # sees activity in console during model reload / service restart
        if (not self._available
                and self._was_available is False
                and self._last_known_model is not None
                and self._consecutive_fails > 2):
            elapsed = int(time.time() - getattr(self, '_restart_start', time.time()))
            self._restart_dots = (getattr(self, '_restart_dots', 0) + 1) % 4
            dots = '.' * (self._restart_dots + 1)
            print(
                f"\r   ⏳ Ожидаем сервер{dots} {elapsed}с  ",
                end='', flush=True
            )
            # Пишем в лог каждые ~30 сек (не спамить)
            last_log = getattr(self, '_restart_last_log_sec', -30)
            if elapsed - last_log >= 30:
                self._restart_last_log_sec = elapsed
                self._write_event(
                    event_type="restart_waiting",
                    message=f"Ожидаем запуск сервера... {elapsed}с",
                    old_model=self._last_known_model or "",
                    elapsed_sec=elapsed,
                )

        return self._available

    def transcribe(self, audio_data: np.ndarray, sample_rate: int,
                   translate: bool = False) -> Optional[str]:
        """Send audio to remote server.
        Returns transcribed text or None if remote failed / disabled.
        """
        import urllib.request
        import io
        import wave

        if self._session_disabled:
            return None

        if not self._check_health():
            return None

        # Convert numpy array to WAV bytes in memory
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # int16
                wf.setframerate(sample_rate)
                if audio_data.dtype != np.int16:
                    audio_data = (audio_data * 32767).clip(-32768, 32767).astype(np.int16)
                wf.writeframes(audio_data.tobytes())
            wav_bytes = buf.getvalue()
        except Exception as e:
            cprint(f"⚠️  Failed to encode audio for remote: {e}", "yellow")
            return None

        # POST to /transcribe
        try:
            lang = "en" if translate else self.language
            req = urllib.request.Request(
                f"{self.url}/transcribe",
                data=wav_bytes,
                method="POST",
                headers={
                    "Content-Type":   "audio/wav",
                    "Content-Length": str(len(wav_bytes)),
                    "X-Language":     lang,
                }
            )
            self._transcribing = True
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                result = json.loads(resp.read().decode("utf-8"))
            finally:
                self._transcribing = False
            text = result.get("text", "").strip()
            proc = result.get("processing_sec", "?")
            # NOTE: caller prints the result AFTER paste so console output
            # does not interfere with focus restore between transcription and paste.
            self._last_remote_log = (
                f"✓ Remote [{result.get('device','?')}|{result.get('model','?')}] "
                f"{proc}s: {text}"
            )
            # Successful transcription — reset all failure counters
            self._transcribe_fails  = 0
            self._health_fail_count = 0
            return text
        except Exception as e:
            self._transcribe_fails += 1
            self._available  = False
            self._last_check = time.time()
            err_str = str(e)
            # HTTP 4xx/5xx = server definitively broken — disable immediately
            is_server_error = ("HTTP Error" in err_str and
                               any(f" {c}" in err_str for c in
                                   ("400","403","404","500","501","502","503","504")))
            limit = self.MAX_SERVER_ERRORS if is_server_error else self.MAX_TRANSCRIBE_FAILURES
            if self._transcribe_fails >= limit:
                self._session_disabled = True
                reason = "HTTP server error" if is_server_error else f"{self._transcribe_fails} timeouts"
                cprint(
                    f"⚠️  Remote disabled for this session ({reason}: {e}). "
                    f"Using local GPU only. Restart to re-enable.",
                    "yellow"
                )
            else:
                cprint(
                    f"⚠️  Remote transcription failed: {e} — falling back to local "
                    f"({self._transcribe_fails}/{self.MAX_TRANSCRIBE_FAILURES} before session disable)",
                    "yellow"
                )
            return None

class WhisperPTT:
    """Main Push-to-Talk handler"""
    
    def __init__(self, config: Config):
        self.config = config
        self.notifier = NotificationManager(
            enabled=config.get('notifications', 'enabled', default=True)
        )
        
        # Audio recording state
        self.is_recording = False
        self.audio_data = []
        self.sample_rate = config.get('audio', 'sample_rate', default=16000)
        self.channels = config.get('audio', 'channels', default=1)
        self.audio_device = self._get_audio_device()
        
        # Whisper model (lazy loaded)
        self.model = None
        
        # Tray indicator
        self.tray = None
        if config.get('tray', 'enabled', default=True) and TRAY_AVAILABLE:
            self.tray = TrayIndicator()
            self.tray.set_ptt(self)  # передаём ссылку для повторной вставки из истории
        
        # Hotkey setup
        self.hotkey = self._parse_hotkey(config.get('hotkey', 'key', default='ctrl_r'))
        self.translate_hotkey = self._parse_hotkey(
            config.get('hotkey', 'translate_key', default='alt_r')
        )
        # Flag: True = record for translation (RU→EN), False = record for transcription only
        self._translate_mode = False

        # Remote transcription (optional — see [remote] in config.toml)
        self._remote: Optional[RemoteTranscriber] = None
        remote_enabled = config.get('remote', 'enabled', default=False)
        remote_url     = config.get('remote', 'url', default='')
        if remote_enabled and remote_url:
            remote_timeout  = config.get('remote', 'timeout',  default=30)
            remote_language = config.get('whisper', 'language', default='ru')
            self._remote = RemoteTranscriber(
                url=remote_url,
                timeout=remote_timeout,
                language=remote_language,
            )
            cprint(f"  ✓ Remote server  : {remote_url}", 'cyan')
        else:
            cprint(f"  ℹ️  Remote mode    : disabled (local GPU)", 'gray')
        
        key    = config.get('hotkey', 'key', default='ctrl_r').upper()
        tr_key = config.get('hotkey', 'translate_key', default='alt_r').upper()
        model  = config.get('whisper', 'model', default='medium')
        lang   = config.get('whisper', 'language', default='ru')
        dev    = config.get('whisper', 'device', default='auto')
        # Resolve actual GPU name for banner
        _gpu_display = dev
        try:
            import torch as _t
            _resolved_dev = dev
            if dev == 'auto':
                if _t.cuda.is_available(): _resolved_dev = 'cuda'
                elif hasattr(_t.backends,'mps') and _t.backends.mps.is_available(): _resolved_dev = 'mps'
                else: _resolved_dev = 'cpu'
            if _resolved_dev == 'cuda' and _t.cuda.is_available():
                _gpu_name  = _t.cuda.get_device_name(0)
                _gpu_vram  = round(_t.cuda.get_device_properties(0).total_memory / 1024**3, 1)
                _gpu_count = _t.cuda.device_count()
                if _gpu_count > 1:
                    _gpu_display = f"CUDA ({_gpu_count} GPUs) — primary: {_gpu_name} {_gpu_vram}GB"
                else:
                    _gpu_display = f"CUDA — {_gpu_name} {_gpu_vram}GB"
            elif _resolved_dev == 'mps':
                _gpu_display = "MPS (Apple Silicon)"
            elif _resolved_dev == 'cpu':
                _gpu_display = "CPU"
        except Exception:
            _gpu_display = dev
        cprint(f"  ✓ Hotkey  RU    : {key} → транскрипция", 'green')
        cprint(f"  ✓ Hotkey  RU→EN : {tr_key} → перевод на английский", 'yellow')
        # Show model info clearly — server model vs local fallback
        if remote_enabled and remote_url:
            # Try to read server model from gpu-config.json (no network needed)
            _server_model = "?"
            try:
                import json as _json
                _gcfg = Path("C:/whisper-server/gpu-config.json")
                if _gcfg.exists():
                    _server_model = _json.loads(_gcfg.read_text(encoding="utf-8")).get("model", "?")
            except Exception:
                pass
            if _server_model != "?":
                cprint(f"  ✓ Model (сервер): {_server_model}  |  Language: {lang}", 'cyan')
            else:
                cprint(f"  ✓ Model (сервер): из gpu-config.json  |  Language: {lang}", 'cyan')
            cprint(f"    (локальный fallback если сервер недоступен: {model})", 'gray')
        else:
            cprint(f"  ✓ Model         : {model}  |  Language: {lang}", 'gray')
        cprint(f"  ✓ GPU           : {_gpu_display}", 'cyan')
        cprint("─" * 58, 'cyan')
    

    def _write_result(self, ru_text: str = "", en_text: str = "",
                       proc_sec: float = 0.0, source: str = "remote",
                       model: str = "", device: str = ""):
        """Append one transcription result to results.jsonl for WebUI display.

        Each line is a self-contained JSON object (JSON Lines format).
        WebUI reads the last N lines to show Recent Transcriptions.
        """
        try:
            results_file = Path(__file__).parent / "logs" / "whisper-results.jsonl"
            results_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "time":     time.strftime("%H:%M:%S"),
                "date":     time.strftime("%Y-%m-%d"),
                "ru":       ru_text.strip()[:500] if ru_text else "",
                "en":       en_text.strip()[:500] if en_text else "",
                "proc_sec": round(proc_sec, 2),
                "source":   source,
                "model":    model,
                "device":   device,
            }
            with open(results_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Keep file from growing too large — trim to last 200 lines
            try:
                lines = results_file.read_text(encoding="utf-8").splitlines()
                if len(lines) > 200:
                    results_file.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")
            except Exception:
                pass
        except Exception:
            pass

    def _write_event(self, event_type: str, message: str,
                     old_model: str = "", new_model: str = "",
                     device: str = "", elapsed_sec: int = 0):
        """Записать системное событие (смена модели, перезапуск) в results.jsonl.

        WebUI отображает их в Recent Transcriptions как системные лог-строки.
        Поле type='event' отличает их от обычных транскрипций.
        """
        try:
            results_file = Path(__file__).parent / "logs" / "whisper-results.jsonl"
            results_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "time":      time.strftime("%H:%M:%S"),
                "date":      time.strftime("%Y-%m-%d"),
                "type":      "event",
                "event":     event_type,   # restart_begin | restart_waiting | model_changed | server_ready | server_restarted
                "message":   message,
                "old_model": old_model,
                "new_model": new_model,
                "device":    device,
                "elapsed":   elapsed_sec,
            }
            with open(results_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Trim to 200 lines
            try:
                lines = results_file.read_text(encoding="utf-8").splitlines()
                if len(lines) > 200:
                    results_file.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")
            except Exception:
                pass
        except Exception:
            pass

    def _update_stats(self, text: str, is_translation: bool = False, processing_sec: float = 0.0, source: str = "local"):
        """Write per-transcription stats to stats.json for the web UI."""
        try:
            stats_file = Path(__file__).parent / "logs" / "whisper-stats.json"
            # Load existing
            stats = {}
            if stats_file.exists():
                try:
                    raw = stats_file.read_text(encoding="utf-8")
                    stats = json.loads(raw)
                except Exception:
                    stats = {}
            # Update counters
            clean = text.strip()
            words = len(clean.split()) if clean else 0
            chars = len(clean)
            stats["total_transcriptions"] = stats.get("total_transcriptions", 0) + 1
            stats["total_words"]          = stats.get("total_words", 0) + words
            stats["total_chars"]          = stats.get("total_chars", 0) + chars
            stats["total_translations"]   = stats.get("total_translations", 0) + (1 if is_translation else 0)
            stats["total_processing_sec"] = round(stats.get("total_processing_sec", 0.0) + processing_sec, 2)
            stats["last_text"]            = clean[:120]
            stats["last_time"]            = time.strftime("%Y-%m-%d %H:%M:%S")
            stats["last_source"]          = source  # "local" or "remote"
            # History (last 20)
            history = stats.get("history", [])
            history.append({
                "time":       stats["last_time"],
                "words":      words,
                "chars":      chars,
                "translated": is_translation,
                "source":     source,
                "proc_sec":   round(processing_sec, 2),
                "text":       clean[:80],
            })
            stats["history"] = history[-20:]
            stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # Stats are non-critical — never crash on stats failure

    def _parse_hotkey(self, key_str: str):
        """Parse hotkey string to pynput Key"""
        key_map = {
            'ctrl_r':  keyboard.Key.ctrl_r,
            'ctrl_l':  keyboard.Key.ctrl_l,
            'alt_r':   keyboard.Key.alt_r,
            'alt_l':   keyboard.Key.alt_l,
            'shift_r': keyboard.Key.shift_r,
            'shift_l': keyboard.Key.shift_l,
        }
        return key_map.get(key_str, keyboard.Key.ctrl_r)

    def _is_translate_key(self, key) -> bool:
        """
        Check if the pressed key is the translate hotkey.
        On Windows, Right Alt (AltGr) sends ctrl_l+alt_r simultaneously.
        We match on alt_r regardless of ctrl_l modifier.
        """
        if key == self.translate_hotkey:
            return True
        # AltGr workaround: pynput may report Key.alt_gr instead of Key.alt_r
        try:
            if hasattr(keyboard.Key, 'alt_gr') and key == keyboard.Key.alt_gr:
                if self.translate_hotkey == keyboard.Key.alt_r:
                    return True
        except Exception:
            pass
        return False
    
    def _get_audio_device(self):
        """Get audio device index from config or auto-detect"""
        device_index = self.config.get('audio', 'device_index', default=None)
        device_name = self.config.get('audio', 'device_name', default=None)
        
        try:
            if device_index is not None:
                return int(device_index)
            
            devices = sd.query_devices()
            
            if device_name:
                # Try to find device by name
                for i, device in enumerate(devices):
                    if device['max_input_channels'] > 0:
                        if device_name.lower() in device['name'].lower():
                            print(f"✓ Using audio device: {device['name']} (index {i})")
                            return i
            
            # Auto-select: prefer RDP audio device, then first input device
            input_devices = []
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append((i, device))
            
            if not input_devices:
                print("⚠️  No audio input devices found. Using default device.")
                return None
            
            # Look for RDP/Remote audio device
            for i, device in input_devices:
                if 'RDP' in device['name'].upper() or 'REMOTE' in device['name'].upper():
                    print(f"✓ Auto-selected RDP audio device: {device['name']} (index {i})")
                    return i
            
            # Use first input device
            selected = input_devices[0]
            print(f"✓ Using default audio device: {selected[1]['name']} (index {selected[0]})")
            return selected[0]
        except Exception as e:
            print(f"⚠️  Warning: Could not enumerate audio devices: {e}")
            print("   Using default audio device.")
            return None
    
    def _load_corrections_dict(self):
        """Load corrections dictionary from C:/whisper-ptt/corrections.json.

        Кешируется по mtime — не перечитываем при каждой транскрипции.
        Поддерживает два режима:
          - простая замена:  {"pattern": "докер", "replacement": "Docker", "regex": false}
          - regex-замена:    {"pattern": "(?i)g\\.?p\\.?t", "replacement": "GPT", "regex": true}
        """
        corrections_file = Path(__file__).parent / "corrections.json"

        # Кеш: (mtime, список) — не читаем файл при каждой транскрипции
        cache = getattr(self, '_corrections_cache', None)
        try:
            mtime = corrections_file.stat().st_mtime if corrections_file.exists() else 0
        except OSError:
            mtime = 0

        if cache is not None and cache[0] == mtime:
            return cache[1]

        corrections = []
        if corrections_file.exists():
            try:
                with open(corrections_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for entry in data.get('corrections', []):
                    pattern     = entry.get('pattern', '').strip()
                    replacement = entry.get('replacement', '').strip()
                    is_regex    = entry.get('regex', False)
                    enabled     = entry.get('enabled', True)
                    if pattern and enabled:
                        corrections.append((pattern, replacement, is_regex))
            except Exception as e:
                print(f"⚠️  Warning: Could not load corrections.json: {e}")

        self._corrections_cache = (mtime, corrections)
        return corrections

    def _fix_common_errors(self, text: str) -> str:
        """Apply user corrections dictionary to transcribed text."""
        corrections = self._load_corrections_dict()
        for pattern, replacement, is_regex in corrections:
            try:
                if is_regex:
                    text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                else:
                    text = re.sub(re.escape(pattern), replacement, text, flags=re.IGNORECASE)
            except re.error as e:
                print(f"⚠️  Warning: Invalid pattern '{pattern}': {e}")
        return text
    
    def _load_model(self, force_local: bool = False):
        """Lazy load Whisper model with automatic OOM fallback.
        force_local=True skips the remote-available check (used when remote failed mid-session).
        """
        if self.model is not None:
            return

        # Skip local model loading if remote is available and healthy.
        # When force_local=True we skip this check — remote already failed.
        if not force_local and self._remote is not None and self._remote._check_health():
            cprint("  ℹ️  Remote server available — skipping local model load", 'cyan')
            return

        cprint("Loading Whisper model (first run may download model)...", 'yellow')
        if self.tray:
            self.tray.update_state('transcribing')

        import torch as _torch

        # ── Resolve device ───────────────────────────────────────────────────
        device_cfg = self.config.get('whisper', 'device', default='auto')
        if device_cfg == 'auto':
            if _torch.cuda.is_available():
                device_cfg = 'cuda'
            elif hasattr(_torch.backends, 'mps') and _torch.backends.mps.is_available():
                device_cfg = 'mps'
            else:
                device_cfg = 'cpu'
        elif device_cfg == 'cuda' and not _torch.cuda.is_available():
            cprint("⚠️  CUDA not available, falling back to CPU", 'yellow')
            device_cfg = 'cpu'
        elif device_cfg == 'mps':
            if not (hasattr(_torch.backends, 'mps') and _torch.backends.mps.is_available()):
                cprint("⚠️  MPS not available, falling back to CPU", 'yellow')
                device_cfg = 'cpu'

        model_name = self.config.get('whisper', 'model', default='base')
        if model_name.endswith('.en'):
            model_name = model_name[:-3]

        # ── Fallback chain for CUDA OOM ──────────────────────────────────────
        # Order: configured model → smaller models → CPU (same model)
        _model_chain = ['large-v2', 'large-v1', 'medium', 'small', 'base', 'tiny']

        # When falling back to local after remote failure, the remote server
        # process is STILL RUNNING and holding GPU VRAM (e.g. large-v2 = ~5-6 GB).
        # Trying to load large-v2 locally will always OOM.
        # Skip straight to medium (fits in remaining ~2-3 GB VRAM).
        _SAFE_LOCAL_MODEL = 'medium'  # guaranteed to coexist with the server process
        if force_local and self._remote is not None:
            if model_name in ('large-v3', 'large-v2', 'large-v1'):
                cprint(
                    f"  ℹ️  Remote server holds GPU VRAM — skipping '{model_name}' locally, "
                    f"using '{_SAFE_LOCAL_MODEL}' to avoid OOM.",
                    'cyan'
                )
                model_name = _SAFE_LOCAL_MODEL

        def _is_oom(exc: Exception) -> bool:
            """Detect CUDA / MPS out-of-memory errors."""
            msg = str(exc).lower()
            return (
                isinstance(exc, _torch.cuda.OutOfMemoryError)
                or 'out of memory' in msg
                or 'cuda out of memory' in msg
                or 'oom' in msg
            )

        def _try_load(m_name: str, dev: str) -> bool:
            """Try loading model on device. Returns True on success."""
            cprint(f"  Device: {dev.upper()}  |  Model: {m_name}", 'cyan')
            try:
                # Free any leftover GPU allocations before each attempt
                if dev == 'cuda':
                    _torch.cuda.empty_cache()
                self.model = whisper.load_model(m_name, device=dev)
                cprint(f"✓ Model loaded: {m_name} on {dev.upper()}", 'green')
                return True
            except Exception as exc:
                if _is_oom(exc):
                    cprint(f"⚠️  OOM on {dev.upper()} with model '{m_name}': not enough free VRAM", 'yellow')
                else:
                    cprint(f"⚠️  Failed to load '{m_name}' on {dev.upper()}: {exc}", 'yellow')
                self.model = None
                return False

        loaded = False

        # 1. Try the configured model on the configured device
        if _try_load(model_name, device_cfg):
            loaded = True

        # 2. If GPU OOM — try progressively smaller models on GPU
        if not loaded and device_cfg in ('cuda', 'mps'):
            cprint("🔄 Trying smaller models on GPU...", 'yellow')
            # Build list of models smaller than the configured one
            try:
                start_idx = _model_chain.index(model_name) + 1
            except ValueError:
                start_idx = 0
            for fallback_model in _model_chain[start_idx:]:
                if _try_load(fallback_model, device_cfg):
                    cprint(
                        f"ℹ️  Loaded '{fallback_model}' instead of '{model_name}' "
                        f"due to insufficient VRAM.\n"
                        f"   To make this permanent, set model = \"{fallback_model}\" in config.toml",
                        'yellow'
                    )
                    loaded = True
                    # Auto-save the working model to config.toml so next launch is instant
                    try:
                        cfg_path = self.config.config_path
                        raw = cfg_path.read_text(encoding='utf-8')
                        import re as _re
                        raw2 = _re.sub(r'(model\s*=\s*")[^"]*(")', rf'\g<1>{fallback_model}\g<2>', raw, count=1)
                        if raw2 != raw:
                            cfg_path.write_text(raw2, encoding='utf-8')
                            cprint(f'  ✓ Auto-updated config.toml: model = "{fallback_model}"', 'cyan')
                    except Exception:
                        pass
                    break

        # 3. Last resort — fall back to CPU with the original model name
        if not loaded:
            cprint(f"🔄 GPU unavailable — falling back to CPU with model '{model_name}'...", 'yellow')
            if _try_load(model_name, 'cpu'):
                cprint(
                    f"ℹ️  Running on CPU. For faster inference set device = \"cpu\" in config.toml",
                    'yellow'
                )
                loaded = True

        if not loaded:
            error_msg = (
                f"Could not load any Whisper model. "
                f"GPU is out of memory and CPU fallback also failed. "
                f"Try setting model = \"base\" or model = \"small\" in config.toml."
            )
            cprint(f"ERROR: {error_msg}", 'red')
            self.notifier.notify("Whisper PTT Error", error_msg, urgency="critical")
            sys.exit(1)

        if self.tray:
            self.tray.update_state('idle')
    
    def start_recording(self):
        """Start recording audio"""
        if self.is_recording:
            return

        # Save the currently focused window BEFORE starting to record.
        # Model loading can take 5-30 seconds on first run — by the time
        # transcription finishes, focus may have moved to the console window.
        # We restore focus here so Ctrl+V lands in the right place.
        #
        # Note: _target_hwnd is first set in on_press() (hotkey callback),
        # which runs in the pynput thread at the exact moment the user presses
        # the key — the most reliable time to capture foreground window.
        # start_recording() only sets it as fallback if on_press didn't.
        if PLATFORM == 'windows' and not getattr(self, '_target_hwnd', None):
            try:
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    self._target_hwnd = hwnd
            except Exception:
                pass

        self.is_recording = True
        self.audio_data = []

        cprint("🔴 Recording...", 'red')
        if self.tray:
            self.tray.update_state('recording')
        
        if self.config.get('notifications', 'show_recording', default=False):
            self.notifier.notify("Whisper PTT", "Recording started")
        
        # Start audio stream
        try:
            stream_kwargs = {
                'samplerate': self.sample_rate,
                'channels': self.channels,
                'dtype': 'int16',
                'callback': self._audio_callback
            }
            
            # Add device if specified
            if self.audio_device is not None:
                stream_kwargs['device'] = self.audio_device
            
            self.stream = sd.InputStream(**stream_kwargs)
            self.stream.start()
        except Exception as e:
            error_msg = f"Failed to start recording: {e}"
            print(f"ERROR: {error_msg}")
            self.notifier.notify("Whisper PTT Error", error_msg, urgency="critical")
            self.is_recording = False
            if self.tray:
                self.tray.update_state('idle')
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio recording"""
        if status:
            print(f"Audio status: {status}")
        self.audio_data.append(indata.copy())
    
    def stop_recording(self):
        """Stop recording and transcribe"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        try:
            self.stream.stop()
            self.stream.close()
        except:
            pass
        
        cprint("⏹️  Stopped recording", 'gray')
        
        # Check if we have audio data
        if not self.audio_data:
            cprint("No audio recorded.", 'gray')
            if self.tray:
                self.tray.update_state('idle')
            return
        
        # Process in background thread
        translate = self._translate_mode
        self._translate_mode = False
        threading.Thread(target=self._transcribe_and_paste, args=(translate,), daemon=True).start()
    
    def _transcribe_and_paste(self, translate_mode: bool = False):
        """Transcribe audio and paste result. If translate_mode=True, also translate RU→EN.

        IMPORTANT: No console output (cprint) or tray updates before _paste_text().
        Any write to the PTT console window — even a single line — causes Windows
        to temporarily give that window focus, making _restore_focus() fail silently.
        All status output is deferred until after the paste completes.

        AUTO-RECOVERY: аудио сохраняется сразу при входе в метод.
        Если удалённый сервер не ответил — аудио НЕ теряется и автоматически
        отправляется на локальную модель без участия пользователя.
        """
        try:
            # ── Сохраняем аудио сразу — до любых сетевых запросов ────────────
            # Это гарантирует что аудио не потеряется при любом сбое сервера.
            _audio_snapshot = list(self.audio_data)  # копия на случай очистки

            # Only notify (silent) before paste — no console output
            if self.config.get('notifications', 'show_transcribing', default=True):
                self.notifier.notify("Whisper PTT", "Transcribing...")
            
            # ── Try remote server first (esli nastroyen udalyonny server) ──
            if self._remote is not None:
                try:
                    audio_concat = np.concatenate(self.audio_data, axis=0)
                    if audio_concat.ndim > 1:
                        audio_concat = audio_concat.flatten()

                    if translate_mode:
                        # Translation mode: two silent requests first, paste, then print.
                        # NO console output before paste — even 🌐 cprint steals focus.
                        ru_text = self._remote.transcribe(
                            audio_concat, self.sample_rate, translate=False
                        )
                        en_text = self._remote.transcribe(
                            audio_concat, self.sample_rate, translate=True
                        )
                        if en_text is not None:
                            en_text = self._fix_common_errors(en_text)
                            ru_display = ru_text.strip() if ru_text else "—"
                            en_display = en_text.strip()
                            paste_text = en_display
                            if self.config.get('paste', 'auto_capitalize', default=True) and paste_text:
                                paste_text = paste_text[0].upper() + paste_text[1:]
                            if self.config.get('paste', 'add_trailing_space', default=True):
                                paste_text += " "
                            # Paste silently — zero console output before this line
                            self._paste_text(paste_text)
                            # All output happens after successful paste
                            cprint("🎤 Transcribing... done", 'yellow')
                            cprint(f"🌐 RU → EN", 'yellow')
                            cprint(f"✓ EN: {en_display}", 'cyan')
                            cprint(f"   ┌─ RU: {ru_display}", 'green')
                            cprint(f"   └─ EN: {en_display}", 'cyan')
                            # Extract model/device/proc_sec from remote log
                            _rm = getattr(self._remote, '_last_remote_log', '')
                            _model = _rm.split('|')[1].split(']')[0].strip() if '|' in _rm else ''
                            _dev   = _rm.split('[')[1].split('|')[0].strip() if '[' in _rm else ''
                            _ps    = float(_rm.split(']')[1].split('s:')[0].strip()) if ']' in _rm and 's:' in _rm else 0.0
                            self._write_result(ru_text=ru_display, en_text=en_display,
                                               proc_sec=_ps,
                                               source="remote", model=_model, device=_dev)
                            self._update_stats(en_display, is_translation=True, processing_sec=_ps, source="remote")
                            if self.tray:
                                self.tray.update_state('idle')
                            return
                        # en_text failed — fall through to local with saved audio
                    else:
                        # Normal transcription mode: single request
                        remote_text = self._remote.transcribe(
                            audio_concat, self.sample_rate, translate=False
                        )
                        if remote_text is not None:
                            remote_text = self._fix_common_errors(remote_text)
                            if self.config.get('paste', 'auto_capitalize', default=True) and remote_text:
                                remote_text = remote_text[0].upper() + remote_text[1:]
                            if self.config.get('paste', 'add_trailing_space', default=True):
                                remote_text += " "
                            # Print AFTER paste so console output doesn't steal focus
                            if hasattr(self._remote, '_last_remote_log'):
                                cprint(self._remote._last_remote_log, 'green')
                            self._paste_text(remote_text)
                            cprint("🎤 Transcribing... done", 'yellow')
                            cprint(f"✓ RU: {remote_text.strip()}", 'green')
                            _rm2 = getattr(self._remote, '_last_remote_log', '')
                            _m2  = _rm2.split('|')[1].split(']')[0].strip() if '|' in _rm2 else ''
                            _d2  = _rm2.split('[')[1].split('|')[0].strip() if '[' in _rm2 else ''
                            _ps2 = float(_rm2.split(']')[1].split('s:')[0].strip()) if ']' in _rm2 and 's:' in _rm2 else 0.0
                            self._write_result(ru_text=remote_text.strip(), en_text="",
                                               proc_sec=_ps2, source="remote", model=_m2, device=_d2)
                            if self.tray:
                                self.tray.update_state('idle')
                            self._update_stats(remote_text.strip(), is_translation=False, source="remote")
                            return
                        # Remote returned None — fall through to local with saved audio
                except Exception as _re:
                    cprint(f"⚠️  Remote path error: {_re} — auto-recovering to local model", 'yellow')
                    self.notifier.notify("Whisper PTT", "⚠️ Сервер недоступен — использую локальную модель")

                # ── AUTO-RECOVERY: восстанавливаем аудио из снапшота ─────────
                # Если self.audio_data был очищен или изменён пока шёл сетевой
                # запрос — восстанавливаем из снапшота сделанного в начале метода.
                if not self.audio_data and _audio_snapshot:
                    self.audio_data = _audio_snapshot
                    cprint("♻️  Audio recovered from snapshot — switching to local model", 'yellow')
            # ── END remote attempt ──────────────────────────────────────────

            # Ensure model is loaded.
            # force_local=True — remote already failed this session, don't re-check health
            # (server may still respond 200 to /health but fail on /transcribe).
            remote_failed = self._remote is not None and not self._remote._available
            self._load_model(force_local=remote_failed)
            
            # Concatenate audio data
            audio_array = np.concatenate(self.audio_data, axis=0)
            
            # Flatten if stereo (though we record mono)
            if audio_array.ndim > 1:
                audio_array = audio_array.flatten()
            
            # Calculate audio level diagnostics
            duration = len(audio_array) / self.sample_rate
            max_amplitude = np.max(np.abs(audio_array))
            rms = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
            volume_percent = (max_amplitude / 32767.0) * 100
            rms_percent = (rms / 32767.0) * 100
            
            # Calculate dynamic range (difference between peak and RMS)
            dynamic_range_db = 20 * np.log10(max_amplitude / rms) if rms > 0 else 0
            
            # Check for clipping/distortion
            clipping_detected = max_amplitude >= 32700  # Near max
            high_dynamic_range = dynamic_range_db > 40  # Normal speech is ~20-30 dB
            
            # Show diagnostics only if enabled
            show_diagnostics = self.config.get('logging', 'show_audio_diagnostics', default=False)
            verbose = self.config.get('logging', 'verbose', default=False)
            
            if show_diagnostics or verbose:
                print(f"Audio diagnostics:")
                print(f"  Duration: {duration:.2f}s")
                print(f"  Max amplitude: {max_amplitude} / 32767 ({volume_percent:.1f}%)")
                print(f"  RMS level: {rms:.2f} ({rms_percent:.2f}%)")
                print(f"  Dynamic range: {dynamic_range_db:.1f} dB")
            
            if clipping_detected and high_dynamic_range:
                if verbose:
                    print(f"  ⚠️  CLIPPING DETECTED: Max amplitude at ceiling with low RMS!")
                    print(f"      This indicates audio distortion/clipping - transcription will be poor")
                    print(f"      Solution: Reduce microphone gain/volume in Windows/RDP settings")
            
            # Process audio based on whether it's clipped or too quiet (same logic as test_combined.py)
            if clipping_detected:
                # Audio is already clipped - REDUCE gain and apply aggressive compression
                if verbose:
                    print(f"  🔧 Recovering clipped audio (reducing gain)...")
                # Reduce gain significantly to get away from clipping
                reduction_factor = 0.3  # Reduce to 30% to get well below clipping
                audio_array_float = audio_array.astype(np.float32) * reduction_factor
                
                # Apply aggressive compression to smooth out peaks
                threshold = 10000  # Start compressing above this
                compression_ratio = 0.2  # Compress peaks by 80%
                mask = np.abs(audio_array_float) > threshold
                audio_array_float[mask] = np.sign(audio_array_float[mask]) * (
                    threshold + (np.abs(audio_array_float[mask]) - threshold) * compression_ratio
                )
                
                # Now normalize RMS to target level
                current_rms = np.sqrt(np.mean(audio_array_float**2))
                target_rms = 12000  # Target RMS level (about 37% of max)
                if current_rms > 0:
                    rms_gain = min(target_rms / current_rms, 2.0)  # Max 2x
                    audio_array_float = audio_array_float * rms_gain
                
                audio_array = np.clip(audio_array_float, -32767, 32767).astype(np.int16)
                if verbose:
                    new_max = np.max(np.abs(audio_array))
                    new_rms = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
                    print(f"      Max: {max_amplitude} → {new_max} ({new_max/32767*100:.1f}%)")
                    print(f"      RMS: {rms:.2f} → {new_rms:.2f} ({new_rms/32767*100:.2f}%)")
            elif rms > 0 and rms < 5000:
                # Audio is too quiet - normalize based on RMS
                target_rms = 20000  # Target RMS level (about 60% of max) for better transcription
                gain = min(target_rms / rms, 5.0)  # Max 5x to avoid over-amplification
                audio_array_float = audio_array.astype(np.float32) * gain
                # Soft clipping: compress peaks above threshold
                threshold = 25000  # Start compressing above this
                compression_ratio = 0.3  # Compress peaks by 70%
                mask = np.abs(audio_array_float) > threshold
                audio_array_float[mask] = np.sign(audio_array_float[mask]) * (
                    threshold + (np.abs(audio_array_float[mask]) - threshold) * compression_ratio
                )
                audio_array = np.clip(audio_array_float, -32767, 32767).astype(np.int16)
                if verbose:
                    new_max = np.max(np.abs(audio_array))
                    new_rms = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
                    print(f"  🔊 Normalized audio (RMS-based, gain: {gain:.2f}x)")
                    print(f"      Max: {max_amplitude} → {new_max} ({new_max/32767*100:.1f}%)")
                    print(f"      RMS: {rms:.2f} → {new_rms:.2f} ({new_rms/32767*100:.2f}%)")
            
            # Save to temporary WAV file (with normalized audio if processing was applied)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                self._last_tmp_path = tmp_path  # keep ref for translation step
                
                with wave.open(tmp_path, 'wb') as wf:
                    wf.setnchannels(self.channels)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(audio_array.astype(np.int16).tobytes())
            
            if verbose:
                file_size = os.path.getsize(tmp_path)
                print(f"  Audio file size: {file_size / 1024:.1f} KB")

            # --- ИСПРАВЛЕНО: читаем язык из config.toml вместо захардкоженного "en" ---
            language = self.config.get('whisper', 'language', default='en')
            print(f"  Language: {language}")

            # Transcribe using openai-whisper
            transcribe_start = time.time()
            
            result = self.model.transcribe(
                tmp_path,
                language=language,          # Язык из config.toml (например "ru")
                task="transcribe",
                temperature=0.0,            # Deterministic
                beam_size=3,                # Small beam for better accuracy
                best_of=2,                  # Try 2 candidates, pick best
                condition_on_previous_text=True,  # Use context for better accuracy
                fp16=False                  # Use FP32 (more compatible)
            )
            
            transcribe_end = time.time()
            transcribe_duration = transcribe_end - transcribe_start
            realtime_factor = duration / transcribe_duration if transcribe_duration > 0 else 0
            
            # Show transcription diagnostics only if enabled
            show_transcription_diagnostics = self.config.get('logging', 'show_transcription_diagnostics', default=False)
            verbose = self.config.get('logging', 'verbose', default=False)
            
            if show_transcription_diagnostics or verbose:
                print(f"Transcription diagnostics:")
                print(f"  Time: {transcribe_duration:.2f}s")
                print(f"  Realtime factor: {realtime_factor:.2f}x ({'faster' if realtime_factor > 1 else 'slower'} than real-time)")
            
            # Extract text from result dict
            text = result["text"].strip()
            
            if verbose:
                print(f"  Transcription length: {len(text)} characters")
            
            # Post-process: fix common transcription errors
            text = self._fix_common_errors(text)
            
            # Clean up temp file (keep if translate_mode — deleted after translation)
            if not translate_mode:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            
            if not text:
                cprint("No speech detected.", 'gray')
                if self.tray:
                    self.tray.update_state('idle')
                return
            
            # Post-process text
            text = text.strip()
            if self.config.get('paste', 'auto_capitalize', default=True):
                if text:
                    text = text[0].upper() + text[1:]
            
            if self.config.get('paste', 'add_trailing_space', default=True):
                text = text + ' '
            
            _proc_sec = time.time() - transcribe_start if 'transcribe_start' in locals() else 0.0
            self._update_stats(text.strip(), is_translation=False,
                               processing_sec=_proc_sec, source="local")

            # ── Translation mode: RU → EN ────────────────────────────────────
            # Note: no cprint/tray before paste — console output steals focus
            if translate_mode:
                try:
                    # Whisper has built-in translation to English via task="translate"
                    translate_result = self.model.transcribe(
                        tmp_path if os.path.exists(tmp_path) else self._last_tmp_path,
                        language=language,
                        task="translate",    # ← Whisper translates to English natively
                        temperature=0.0,
                        beam_size=3,
                        best_of=2,
                        condition_on_previous_text=False,
                        fp16=False
                    )
                    en_text = translate_result["text"].strip()
                    if en_text:
                        if self.config.get('paste', 'auto_capitalize', default=True):
                            en_text = en_text[0].upper() + en_text[1:]
                        if self.config.get('paste', 'add_trailing_space', default=True):
                            en_text = en_text + ' '
                    # Paste FIRST — notification must come AFTER paste.
                    # show_result notification pops a toast window which grabs
                    # foreground focus and breaks subsequent SetForegroundWindow.
                    self._paste_text(en_text)
                    if self.config.get('notifications', 'show_result', default=False):
                        self.notifier.notify("Whisper PTT", f"EN: {en_text}")
                    cprint("🎤 Transcribing... done", 'yellow')
                    cprint(f"✓ EN: {en_text.strip()}", 'cyan')
                    cprint(f"   ┌─ RU: {text.strip()}", 'green')
                    cprint(f"   └─ EN: {en_text.strip()}", 'cyan')
                    self._write_result(ru_text=text.strip(), en_text=en_text.strip(),
                                       proc_sec=0.0, source="local", model=getattr(self, '_model_name', ''), device="local")
                except Exception as te:
                    print(f"ERROR: Translation failed: {te}")
                    print(f"Falling back to RU transcription")
                    if self.config.get('notifications', 'show_result', default=False):
                        self.notifier.notify("Whisper PTT", f"RU: {text}")
                    self._paste_text(text)
            else:
                # ── Normal transcription mode ────────────────────────────────
                if self.config.get('notifications', 'show_result', default=False):
                    self.notifier.notify("Whisper PTT", f"RU: {text}")
                self._paste_text(text)
                cprint("🎤 Transcribing... done", 'yellow')
                cprint(f"✓ RU: {text.strip()}", 'green')
                self._write_result(ru_text=text.strip(), en_text="",
                                   proc_sec=0.0, source="local", model=getattr(self, '_model_name', ''), device="local")
            
        except Exception as e:
            error_msg = f"Transcription error: {e}"
            print(f"ERROR: {error_msg}")
            self.notifier.notify("Whisper PTT Error", error_msg, urgency="critical")
        finally:
            # Clean up temp file if translation mode (delayed deletion)
            if translate_mode:
                try:
                    if hasattr(self, '_last_tmp_path') and os.path.exists(self._last_tmp_path):
                        os.unlink(self._last_tmp_path)
                except:
                    pass
            if self.tray:
                self.tray.update_state('idle')
    
    def _restore_focus(self):
        """Restore focus to the window saved at hotkey press time.

        Uses AttachThreadInput (to the TARGET thread, not foreground thread)
        + SPI_SETFOREGROUNDLOCKTIMEOUT=0 bypass so SetForegroundWindow works
        even after long background processing (translation takes 8-15 sec,
        Windows normally blocks SetForegroundWindow after ~2 sec idle).
        Polls GetForegroundWindow to confirm focus actually switched.
        """
        if PLATFORM != 'windows':
            return
        hwnd = getattr(self, '_target_hwnd', None)
        if not hwnd:
            return
        try:
            import ctypes
            import ctypes.wintypes

            u32 = ctypes.windll.user32
            k32 = ctypes.windll.kernel32

            if not u32.IsWindow(hwnd):
                return

            # ── Bypass foreground lock ────────────────────────────────────────
            # Windows blocks SetForegroundWindow after ~2 seconds since last
            # user interaction. Translation processing takes 8-15 seconds, so
            # by the time we call _restore_focus() the lock is active and
            # SetForegroundWindow silently fails (just flashes the taskbar).
            # Setting SPI_SETFOREGROUNDLOCKTIMEOUT = 0 disables this protection
            # so our call succeeds regardless of elapsed time.
            try:
                SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
                SPIF_SENDCHANGE = 0x0002
                u32.SystemParametersInfoW(
                    SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                    ctypes.cast(ctypes.c_void_p(0), ctypes.c_void_p),
                    SPIF_SENDCHANGE
                )
            except Exception:
                pass

            # Restore from minimized if needed
            SW_RESTORE = 9
            if u32.IsIconic(hwnd):
                u32.ShowWindow(hwnd, SW_RESTORE)
                time.sleep(0.08)

            # ── Already in focus? Nothing to do ──────────────────────────────
            if u32.GetForegroundWindow() == hwnd:
                time.sleep(0.05)
                return

            # ── AttachThreadInput to TARGET window's thread ───────────────────
            target_tid = u32.GetWindowThreadProcessId(hwnd, None)
            my_tid     = k32.GetCurrentThreadId()

            attached = False
            if target_tid and target_tid != my_tid:
                attached = bool(u32.AttachThreadInput(my_tid, target_tid, True))

            try:
                u32.SetForegroundWindow(hwnd)
                u32.BringWindowToTop(hwnd)
            finally:
                if attached:
                    u32.AttachThreadInput(my_tid, target_tid, False)

            # ── Poll until focus actually switches (max 500ms) ────────────────
            deadline = time.time() + 0.5
            while time.time() < deadline:
                time.sleep(0.02)
                if u32.GetForegroundWindow() == hwnd:
                    time.sleep(0.05)
                    return

            # Focus didn't switch — last resort: show + force
            u32.ShowWindow(hwnd, 5)  # SW_SHOW
            u32.SetForegroundWindow(hwnd)
            time.sleep(0.15)

        except Exception as e:
            verbose = self.config.get('logging', 'verbose', default=False)
            if verbose:
                print(f"  [focus restore] {e}")

    def _paste_text(self, text: str):
        """Paste text into the window that had focus when the hotkey was pressed.

        Order of operations:
          1. restore_focus() — give focus back to the target window
          2. clear clipboard — prevent stale content duplication
          3. set clipboard with the final text
          4. wait 150ms — let clipboard propagate to the target process
          5. send Ctrl+V
        """
        method = self.config.get('paste', 'method', default='both')
        success = False

        # ── История трея добавляется ДО вставки, но refresh_menu запускается
        # ПОСЛЕ — чтобы обновление иконки трея не перехватило foreground фокус
        # в момент когда мы восстанавливаем его для целевого окна.
        _tray_needs_refresh = False
        if self.tray and text:
            clean_for_history = text.rstrip()
            self.tray.add_to_history(clean_for_history)
            _tray_needs_refresh = True   # refresh happens after paste below

        if method in ['ctrl_v', 'both']:
            # Tell keyboard_sim which window to target (needed for WM_PASTE)
            _hwnd = getattr(self, '_target_hwnd', None)
            if _hwnd and hasattr(keyboard_sim, 'set_target_hwnd'):
                keyboard_sim.set_target_hwnd(_hwnd)

            # Step 1: Restore focus
            self._restore_focus()

            # Extra settle for heavy apps like OpenOffice (VCL toolkit is slow
            # to accept focus — add 100ms more if window class suggests it)
            if PLATFORM == 'windows' and _hwnd:
                try:
                    import ctypes
                    _cls = ctypes.create_unicode_buffer(64)
                    ctypes.windll.user32.GetClassNameW(_hwnd, _cls, 64)
                    _cls_name = _cls.value.upper()
                    # SALFRAME = OpenOffice/LibreOffice VCL, AWTFRAME = Java Swing
                    if any(x in _cls_name for x in ('SALFRAME', 'AWTFRAME', 'SWTWINDOW')):
                        time.sleep(0.15)  # VCL/Java needs extra settle time
                except Exception:
                    pass

            # Step 2: Clear clipboard
            if PLATFORM == 'windows':
                try:
                    import ctypes
                    ctypes.windll.user32.OpenClipboard(0)
                    ctypes.windll.user32.EmptyClipboard()
                    ctypes.windll.user32.CloseClipboard()
                except Exception:
                    pass

            # Step 3: Set clipboard
            if clipboard.set_clipboard_text(text):
                # Step 4: Wait for clipboard to propagate to the target process.
                # 200ms instead of 150ms — gives remote processes (OpenOffice VCL,
                # Java Swing, Electron) enough time to register the clipboard change.
                time.sleep(0.20)

                # Step 5: Send Ctrl+V
                if keyboard_sim.paste_with_ctrl_v():
                    success = True
                    cprint("✓ Text pasted (Ctrl+V)", 'green')
                else:
                    print("Ctrl+V paste failed")
            else:
                print("Failed to copy to clipboard")
        
        # ── Now safe to refresh tray menu (paste is done, focus is established) ──
        if _tray_needs_refresh:
            import threading as _th
            _th.Thread(target=self.tray.refresh_menu, daemon=True).start()

        # Fallback to typing
        if not success and method in ['type', 'both']:
            if keyboard_sim.type_text(text):
                cprint("✓ Text typed (fallback)", 'green')
                success = True
            else:
                error_msg = "Failed to paste text"
                print(f"ERROR: {error_msg}")
                self.notifier.notify("Whisper PTT Error", error_msg, urgency="critical")
    
    def on_press(self, key):
        """Handle key press"""
        try:
            if key == self.hotkey or self._is_translate_key(key):
                # Capture foreground window HERE — this is the most reliable
                # moment: the user has just pressed the hotkey while focused
                # on the target window (chat, editor, browser, etc.).
                # Capturing later (after model load) risks getting the PTT
                # console window or nothing meaningful.
                if PLATFORM == 'windows':
                    try:
                        import win32gui
                        fg = win32gui.GetForegroundWindow()
                        if fg:
                            self._target_hwnd = fg
                    except Exception:
                        pass
                else:
                    self._target_hwnd = None

            if key == self.hotkey:
                verbose = self.config.get('logging', 'verbose', default=False)
                if verbose:
                    cprint(f"🔴 Hotkey pressed: {key}", 'red')
                self._translate_mode = False
                self.start_recording()
            elif self._is_translate_key(key):
                verbose = self.config.get('logging', 'verbose', default=False)
                if verbose:
                    cprint(f"🌐 Translate hotkey pressed: {key}", 'yellow')
                self._translate_mode = True
                self.start_recording()
        except AttributeError:
            pass
        except Exception as e:
            cprint(f"ERROR in on_press: {e}", 'red')
            import traceback
            traceback.print_exc()
    
    def on_release(self, key):
        """Handle key release"""
        try:
            if key == self.hotkey or self._is_translate_key(key):
                verbose = self.config.get('logging', 'verbose', default=False)
                if verbose:
                    cprint(f"⏹️  Hotkey released: {key}", 'gray')
                self.stop_recording()
        except AttributeError:
            pass
        except Exception as e:
            cprint(f"ERROR in on_release: {e}", 'red')
            import traceback
            traceback.print_exc()
    
    def _server_monitor_loop(self):
        """Background thread: polls remote server every 8 sec and logs status changes.

        Key changes:
        - Skip poll if transcription is in flight — server is busy, a health
          check timeout would trigger a false "offline" warning.
        - Do NOT force reset _last_check — let the cooldown logic work naturally.
          Forcing 0.0 was causing extra polls that raced with busy transcriptions.
        - Interval increased from 5s to 8s to reduce load and race conditions.
        """
        if self._remote is None:
            return
        CHECK_INTERVAL = 8  # seconds between polls (was 5s)
        while True:
            try:
                time.sleep(CHECK_INTERVAL)
                if self._remote._session_disabled:
                    return
                # Skip if actively transcribing — server is busy
                if getattr(self._remote, '_transcribing', False):
                    continue
                # Let the normal cooldown logic decide if a fresh check is needed
                # DO NOT reset _last_check = 0.0 — that caused false offline warnings
                self._remote._check_health()
            except Exception:
                pass  # never crash the monitor thread

    def run(self):
        """Run the PTT listener"""
        # Start server monitor thread if remote is configured
        if self._remote is not None:
            threading.Thread(
                target=self._server_monitor_loop,
                daemon=True,
                name="server-monitor"
            ).start()

        # Start tray in background thread if enabled
        verbose = self.config.get('logging', 'verbose', default=False)
        
        try:
            if self.tray:
                print("Creating tray icon...")
                try:
                    tray_icon = self.tray.create_icon()
                    if tray_icon:
                        print("Starting tray icon in background thread...")
                        # Store reference to prevent garbage collection
                        self.tray_thread = threading.Thread(target=self.tray.run, daemon=False)
                        self.tray_thread.start()
                        time.sleep(1.0)  # Give tray time to initialize
                        cprint("✓ Tray icon started successfully", 'green')
                    else:
                        print("⚠️  Failed to create tray icon (create_icon returned None)")
                except Exception as e:
                    print(f"⚠️  Error creating tray icon: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("⚠️  Tray icon disabled (not available or disabled in config)")
        except Exception as e:
            print(f"ERROR initializing tray: {e}")
            import traceback
            traceback.print_exc()
        
        # Start keyboard listener
        print(f"Starting keyboard listener (waiting for {self.hotkey})...")
        
        # Set up signal handler for Ctrl+C (works better than KeyboardInterrupt in some cases)
        self.running = True
        
        def signal_handler(signum, frame):
            print("\n\nCtrl+C detected. Shutting down...")
            self.running = False
            if self.tray and self.tray.icon:
                try:
                    self.tray.icon.stop()
                except:
                    pass
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        cprint("✓ Keyboard listener ready. Waiting for hotkey...", 'green')
        
        try:
            with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
                self.listener = listener
                while self.running:
                    try:
                        listener.join(timeout=0.1)
                        if not self.running:
                            break
                    except KeyboardInterrupt:
                        signal_handler(signal.SIGINT, None)
        except Exception as e:
            print(f"FATAL ERROR in keyboard listener: {e}")
            import traceback
            traceback.print_exc()
            raise
        except KeyboardInterrupt:
            signal_handler(signal.SIGINT, None)


class _TeeWriter:
    """Write to both the original stream (console) and a log file."""
    def __init__(self, original, log_fp):
        self._original = original
        self._log_fp = log_fp
    def write(self, data):
        if self._original:
            try: self._original.write(data)
            except: pass
        try:
            self._log_fp.write(data)
            self._log_fp.flush()
        except: pass
    def flush(self):
        if self._original:
            try: self._original.flush()
            except: pass
        try: self._log_fp.flush()
        except: pass
    def isatty(self):
        return self._original.isatty() if self._original and hasattr(self._original, 'isatty') else False



# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC MODE  —  python whisper-ptt.py --diagnose
# ══════════════════════════════════════════════════════════════════════════════

def run_diagnostics():
    """
    Full system diagnostic. Checks every component and prints OK/FAIL table.
    Exits with code 0 (all OK) or 1 (at least one FAIL).
    """
    import shutil

    results: list[tuple[str, bool, str]] = []   # (label, ok, advice)

    def chk(label: str, ok: bool, advice: str = ""):
        results.append((label, ok, advice))
        status = f"{_C['green']}[  OK  ]{_C['reset']}" if ok else f"{_C['red']}[ FAIL ]{_C['reset']}"
        print(f"  {status}  {label}")
        if not ok and advice:
            print(f"          {_C['yellow']}→ {advice}{_C['reset']}")

    cprint("=" * 62, 'cyan')
    cprint("  whisper_from_sssDeMoNsss — ДИАГНОСТИКА СИСТЕМЫ", 'white')
    cprint("  (System Diagnostic — checking all components)", 'gray')
    cprint("=" * 62, 'cyan')
    print()

    config = Config()

    # ── 1. Python version ────────────────────────────────────────────────────
    import sys as _sys
    py_ver = _sys.version_info
    py_ok  = py_ver >= (3, 10)
    chk(f"Python версия: {py_ver.major}.{py_ver.minor}.{py_ver.micro}", py_ok,
        "Требуется Python 3.10+. Скачайте: https://www.python.org/downloads/")

    # ── 2. FFmpeg ────────────────────────────────────────────────────────────
    ff_path = shutil.which("ffmpeg")
    if not ff_path and PLATFORM == "windows":
        # Try known WinGet paths
        import os as _os
        for d in [r"C:fmpegin", r"C:\ProgramData\chocolateyin"]:
            if _os.path.isfile(_os.path.join(d, "ffmpeg.exe")):
                ff_path = _os.path.join(d, "ffmpeg.exe"); break
    chk(f"FFmpeg: {ff_path or 'не найден'}", bool(ff_path),
        "Установите: winget install Gyan.FFmpeg  или  choco install ffmpeg")

    # ── 3. Required Python packages ──────────────────────────────────────────
    packages = [
        ("sounddevice",    "pip install sounddevice"),
        ("numpy",          "pip install numpy"),
        ("whisper",        "pip install openai-whisper"),
        ("pynput",         "pip install pynput"),
        ("colorama",       "pip install colorama"),
    ]
    for pkg, hint in packages:
        try:
            __import__(pkg)
            chk(f"Пакет: {pkg}", True)
        except ImportError:
            chk(f"Пакет: {pkg}", False, hint)

    # ── 4. Optional packages ─────────────────────────────────────────────────
    opt = [("pystray", "pip install pystray pillow"),
           ("PIL",     "pip install pillow"),
           ("tomllib", None), ("tomli", "pip install tomli")]
    for pkg, hint in opt:
        try:
            __import__(pkg)
            chk(f"Пакет (опц.): {pkg}", True)
            if pkg in ("tomllib","tomli"): break
        except ImportError:
            if hint:
                chk(f"Пакет (опц.): {pkg}", False, hint)

    # ── 5. TOML / config ─────────────────────────────────────────────────────
    cfg_path = config.config_path
    cfg_ok   = cfg_path.exists()
    chk(f"config.toml: {cfg_path}", cfg_ok,
        f"Создайте config.toml рядом со скриптом или запустите установщик INSTALL.bat")
    if cfg_ok:
        lang  = config.get('whisper', 'language', default='?')
        model = config.get('whisper', 'model',    default='?')
        chk(f"Конфиг: язык={lang}  модель={model}", True)

    # ── 6. GPU / PyTorch ─────────────────────────────────────────────────────
    try:
        import torch as _torch
        cuda_ok = _torch.cuda.is_available()
        if cuda_ok:
            gpu_name  = _torch.cuda.get_device_name(0)
            vram_gb   = round(_torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
            chk(f"GPU (CUDA): {gpu_name} — {vram_gb} GB VRAM", True)
        else:
            mps_ok = hasattr(_torch.backends, 'mps') and _torch.backends.mps.is_available()
            if mps_ok:
                chk("GPU (MPS / Apple Silicon): доступна", True)
            else:
                chk("GPU (CUDA/MPS): не найдена — режим CPU", False,
                    "На CPU транскрипция медленнее (3-8 сек). Для GPU установите CUDA Toolkit.")
    except ImportError:
        chk("PyTorch (torch)", False,
            "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124")

    # ── 7. Whisper model cache ───────────────────────────────────────────────
    try:
        import whisper as _wh
        import os as _os
        cache = Path(_os.path.expanduser("~")) / ".cache" / "whisper"
        model_name = config.get('whisper', 'model', default='medium')
        if model_name.endswith('.en'):
            model_name = model_name[:-3]
        # Check if model file exists (Whisper stores as <name>.pt)
        found_files = list(cache.glob(f"{model_name}*.pt")) if cache.exists() else []
        if found_files:
            size_mb = round(found_files[0].stat().st_size / 1024 / 1024)
            chk(f"Модель Whisper [{model_name}] в кэше: {found_files[0].name} ({size_mb} MB)", True)
        else:
            chk(f"Модель Whisper [{model_name}] в кэше", False,
                "Модель будет скачана (~140 MB–3 GB) при первом запуске. Требуется интернет.")
    except Exception as e:
        chk("Whisper (openai-whisper)", False, f"pip install openai-whisper  ({e})")

    # ── 8. Remote server ─────────────────────────────────────────────────────
    remote_enabled = config.get('remote', 'enabled', default=False)
    remote_url     = config.get('remote', 'url',     default='')
    if remote_enabled and remote_url:
        import urllib.request as _ur
        import json as _json
        try:
            resp = _ur.urlopen(f"{remote_url}/health", timeout=5)
            data = _json.loads(resp.read())
            model_loaded = data.get('model_loaded', False)
            srv_model    = data.get('model', '?')
            srv_device   = data.get('device', '?')
            if model_loaded:
                chk(f"Удалённый сервер [{remote_url}]: модель [{srv_model}] на {srv_device.upper()}", True)
            else:
                chk(f"Удалённый сервер [{remote_url}]: сервер запущен, модель загружается...", False,
                    "Подождите 30-120 секунд пока модель загрузится.")
        except Exception as e:
            chk(f"Удалённый сервер [{remote_url}]", False,
                f"Сервер недоступен ({e}). Проверьте: запущен ли WhisperServer? Start-Service WhisperServer")
    else:
        chk("Удалённый сервер: режим отключён (local GPU)", True)

    # ── 9. Audio device ──────────────────────────────────────────────────────
    try:
        import sounddevice as _sd
        devices = _sd.query_devices()
        input_devs = [d for d in devices if d['max_input_channels'] > 0]
        if input_devs:
            dev_name = config.get('audio', 'device_name', default=None)
            chosen   = config.get('audio', 'device_index', default=None)
            if chosen is not None:
                label = f"устройство #{chosen}"
            elif dev_name:
                match = next((d for d in input_devs if dev_name.lower() in d['name'].lower()), None)
                label = f"{match['name']}" if match else f"'{dev_name}' — НЕ НАЙДЕНО"
                if not match:
                    chk(f"Аудио устройство: {label}", False,
                        f"Устройство '{dev_name}' не найдено. Проверьте device_name в config.toml")
                    input_devs = None
            else:
                label = input_devs[0]['name']
            if input_devs:
                chk(f"Аудио устройство: {label}", True)
        else:
            chk("Аудио устройство (микрофон)", False,
                "Микрофон не найден. Подключите микрофон или проверьте настройки звука.")
    except Exception as e:
        chk("Аудио устройство (sounddevice)", False, f"Ошибка: {e}")

    # ── 10. Microphone recording test (0.5 sec) ──────────────────────────────
    try:
        import sounddevice as _sd
        import numpy as _np
        print("  [ .. ]  Тест микрофона (0.5 сек запись)...")
        sys.stdout.flush()
        rec = _sd.rec(int(0.5 * 16000), samplerate=16000, channels=1,
                      dtype='int16', blocking=True)
        rms = float(_np.sqrt(_np.mean(rec.astype(_np.float32)**2)))
        if rms > 10:
            chk(f"Тест микрофона: RMS={rms:.0f} — звук есть", True)
        else:
            chk(f"Тест микрофона: RMS={rms:.0f} — тишина (говорите или шумите при тесте)", False,
                "Проверьте: включён ли микрофон? Не заглушён ли? Правильное ли устройство в config.toml?")
    except Exception as e:
        chk("Тест микрофона (запись 0.5 сек)", False, f"Ошибка: {e}")

    # ── 11. Clipboard ────────────────────────────────────────────────────────
    try:
        from whisper_platform import clipboard as _cb
        test_str = "whisper_diagnose_test_🎤"
        ok = _cb.set_clipboard_text(test_str)
        chk("Буфер обмена (clipboard write)", ok,
            "Установите pywin32: pip install pywin32  или  pip install pyperclip")
    except Exception as e:
        chk("Буфер обмена (clipboard)", False, f"Ошибка: {e}")

    # ── 12. Keyboard simulation ──────────────────────────────────────────────
    try:
        from whisper_platform import keyboard_sim as _ks
        has_win32      = getattr(_ks, 'WIN32_AVAILABLE',     False)
        has_pyautogui  = getattr(_ks, 'PYAUTOGUI_AVAILABLE', False)
        sim_ok = has_win32 or has_pyautogui or PLATFORM != 'windows'
        detail = ("win32api" if has_win32 else "") + (" pyautogui" if has_pyautogui else "")
        chk(f"Симуляция клавиатуры: {detail.strip() or 'xdotool/osascript'}", sim_ok,
            "pip install pywin32  или  pip install pyautogui")
    except Exception as e:
        chk("Симуляция клавиатуры", False, f"Ошибка: {e}")

    # ── 13. Disk space ───────────────────────────────────────────────────────
    try:
        import shutil as _sh
        total, used, free = _sh.disk_usage(Path(__file__).parent)
        free_gb = round(free / 1024**3, 1)
        ok = free_gb >= 3.0
        chk(f"Место на диске: {free_gb} GB свободно", ok,
            "Нужно минимум 3 GB для моделей Whisper. Освободите место.")
    except Exception as e:
        chk("Место на диске", False, str(e))

    # ── 14. Log directory writable ───────────────────────────────────────────
    log_dir = Path(__file__).parent / 'logs'
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        test_file = log_dir / '.diag_write_test'
        test_file.write_text("ok"); test_file.unlink()
        chk(f"Папка логов: {log_dir}", True)
    except Exception as e:
        chk(f"Папка логов: {log_dir}", False, f"Нет прав на запись: {e}")

    # ── Summary ──────────────────────────────────────────────────────────────
    total_ok   = sum(1 for _, ok, _ in results if ok)
    total_fail = sum(1 for _, ok, _ in results if not ok)
    print()
    cprint("=" * 62, 'cyan')
    if total_fail == 0:
        cprint(f"  ✓ Всё в порядке! Все {total_ok} проверок пройдены.", 'green')
        cprint("    Запустите: python whisper-ptt.py", 'gray')
    else:
        cprint(f"  ✗ Найдено проблем: {total_fail}  /  Пройдено: {total_ok}", 'red')
        cprint("    Исправьте ошибки выше и повторите: python whisper-ptt.py --diagnose", 'yellow')
    cprint("=" * 62, 'cyan')

    # Save report to log
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        report_path = log_dir / 'whisper-diagnose.log'
        with open(report_path, 'w', encoding='utf-8') as rf:
            import time as _t
            rf.write(f"whisper-ptt --diagnose  {_t.strftime('%Y-%m-%d %H:%M:%S')}\n")
            rf.write("=" * 60 + "\n")
            for label, ok, advice in results:
                rf.write(f"{'[  OK  ]' if ok else '[ FAIL ]'}  {label}\n")
                if not ok and advice:
                    rf.write(f"         → {advice}\n")
            rf.write(f"\nTotal: {total_ok} OK, {total_fail} FAIL\n")
        print(f"\n  Отчёт сохранён: {report_path}")
    except Exception:
        pass

    import sys as _sys2
    _sys2.exit(0 if total_fail == 0 else 1)


def main():
    """Main entry point"""
    # ── --diagnose: run full system check and exit ────────────────────────────
    import sys as _sys_args
    if '--diagnose' in _sys_args.argv or '-d' in _sys_args.argv:
        run_diagnostics()
        return   # run_diagnostics() calls sys.exit() itself

    # Set up logging — always write to log file (needed for WebUI stats)
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'whisper-ptt.log'
    
    # Check if we're running headless (no console attached)
    try:
        is_headless = not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty()
    except:
        is_headless = True
    
    log_fp = open(log_file, 'a', encoding='utf-8')
    if is_headless:
        # Running headless (Task Scheduler / nohup) — log file only
        sys.stdout = log_fp
        sys.stderr = log_fp
    else:
        # Running interactively — tee to both console and log file
        sys.stdout = _TeeWriter(sys.stdout, log_fp)
        sys.stderr = _TeeWriter(sys.stderr, log_fp)

    print(f"\n{'='*60}")
    print(f"Whisper PTT started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Platform: {PLATFORM}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    print(f"{'='*60}\n")
    
    try:
        cprint("=" * 58, 'cyan')
        cprint("  whisper_from_sssDeMoNsss — говори, не печатай.", 'white')
        cprint("  Зажал клавишу — сказал — текст уже в чате.", 'gray')
        cprint("─" * 58, 'cyan')
        cprint("  Автор  : sssDeMoNsss", 'gray')
        cprint("  ВК     : vk.com/basset2", 'gray')
        cprint("  Telegram: @snnike", 'gray')
        cprint("─" * 58, 'cyan')
        cprint(f"  Platform: {PLATFORM.upper()}", 'cyan')
        cprint("=" * 58, 'cyan')
        
        # Ensure we're in the script's directory (important for Task Scheduler)
        script_dir = Path(__file__).parent.absolute()
        os.chdir(script_dir)
        print(f"Changed to script directory: {script_dir}")
        
        # Platform-specific checks
        if PLATFORM == 'linux':
            # Check for required Linux system tools
            required_tools = ['xclip', 'xdotool']
            missing_tools = []
            for tool in required_tools:
                try:
                    subprocess.run(['which', tool], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except subprocess.CalledProcessError:
                    missing_tools.append(tool)
            
            if missing_tools:
                print(f"ERROR: Missing required system tools: {', '.join(missing_tools)}")
                print(f"Install with: sudo apt install {' '.join(missing_tools)}")
                sys.exit(1)
        elif PLATFORM == 'windows':
            # Check for Windows-specific dependencies
            if not clipboard.WIN32_AVAILABLE and not clipboard.PYPERCLIP_AVAILABLE:
                print("WARNING: No clipboard library available.")
                print("Install one of: pip install pywin32 OR pip install pyperclip")
            
            if not keyboard_sim.PYAUTOGUI_AVAILABLE and not keyboard_sim.WIN32_AVAILABLE:
                print("WARNING: No keyboard simulation library available.")
                print("Install one of: pip install pyautogui OR pip install pywin32")
        
        # Load configuration
        print("Loading configuration...")
        config = Config()
        print("Configuration loaded successfully.")
        
        # Create PTT instance
        print("Initializing Whisper PTT...")
        ptt = WhisperPTT(config)
        print("Whisper PTT initialized successfully.")
        
        # Run
        print("Starting main loop...")
        ptt.run()
        
    except Exception as e:
        error_msg = f"FATAL ERROR: {e}\n"
        error_msg += "=" * 60 + "\n"
        import traceback
        error_msg += traceback.format_exc()
        print(error_msg)
        
        # Also write to log file if we have one
        if is_headless and 'log_fp' in locals():
            log_fp.write(error_msg)
            log_fp.flush()
        
        # Keep process alive for a bit so Task Scheduler can see the error
        time.sleep(5)
        sys.exit(1)


if __name__ == '__main__':
    main()