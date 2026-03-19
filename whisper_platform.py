"""
whisper_platform.py — Platform abstraction layer for whisper_from_sssDeMoNsss
Provides: PLATFORM, clipboard, keyboard_sim, notifications, autostart

Supports Windows, Linux, macOS.
"""

import sys
import os

# ── Detect platform ────────────────────────────────────────────────────────────
if sys.platform == 'win32':
    PLATFORM = 'windows'
elif sys.platform == 'darwin':
    PLATFORM = 'macos'
else:
    PLATFORM = 'linux'


# ══════════════════════════════════════════════════════════════════════════════
# CLIPBOARD
# ══════════════════════════════════════════════════════════════════════════════

class _Clipboard:
    WIN32_AVAILABLE = False
    PYPERCLIP_AVAILABLE = False

    def __init__(self):
        if PLATFORM == 'windows':
            try:
                import win32clipboard  # noqa
                self.WIN32_AVAILABLE = True
            except ImportError:
                pass
            try:
                import pyperclip  # noqa
                self.PYPERCLIP_AVAILABLE = True
            except ImportError:
                pass
        elif PLATFORM == 'linux':
            pass  # uses xclip / xsel via subprocess
        elif PLATFORM == 'macos':
            pass  # uses pbcopy via subprocess

    def set_clipboard_text(self, text: str) -> bool:
        """Copy text to clipboard. Returns True on success."""
        try:
            if PLATFORM == 'windows':
                return self._set_windows(text)
            elif PLATFORM == 'linux':
                return self._set_linux(text)
            elif PLATFORM == 'macos':
                return self._set_macos(text)
        except Exception as e:
            print(f"Clipboard error: {e}")
        return False

    def _set_windows(self, text: str) -> bool:
        if self.WIN32_AVAILABLE:
            try:
                import win32clipboard
                import win32con
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                win32clipboard.CloseClipboard()
                return True
            except Exception:
                pass
        if self.PYPERCLIP_AVAILABLE:
            try:
                import pyperclip
                pyperclip.copy(text)
                return True
            except Exception:
                pass
        # Fallback: PowerShell (передаём текст через stdin, а не через f-строку,
        # чтобы избежать инъекции при наличии кавычек и спецсимволов в тексте)
        try:
            import subprocess
            subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 '$input | Set-Clipboard'],
                input=text, capture_output=True, timeout=5, text=True,
                encoding='utf-8'
            )
            return True
        except Exception:
            return False

    def _set_linux(self, text: str) -> bool:
        import subprocess
        # Try xclip first
        for tool, args in [
            ('xclip', ['-selection', 'clipboard']),
            ('xsel',  ['--clipboard', '--input']),
        ]:
            try:
                result = subprocess.run(
                    [tool] + args,
                    input=text.encode('utf-8'),
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
            except Exception:
                continue
        # Try pyperclip as fallback
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    def _set_macos(self, text: str) -> bool:
        import subprocess
        try:
            subprocess.run(
                ['pbcopy'],
                input=text.encode('utf-8'),
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            pass
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            return False


clipboard = _Clipboard()


# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARD SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════

class _KeyboardSim:
    WIN32_AVAILABLE = False
    PYAUTOGUI_AVAILABLE = False

    def __init__(self):
        if PLATFORM == 'windows':
            try:
                import win32api  # noqa
                self.WIN32_AVAILABLE = True
            except ImportError:
                pass
            try:
                import pyautogui  # noqa
                self.PYAUTOGUI_AVAILABLE = True
            except ImportError:
                pass

    def paste_with_ctrl_v(self) -> bool:
        """Simulate Ctrl+V keypress. Returns True on success."""
        try:
            if PLATFORM == 'windows':
                return self._ctrl_v_windows()
            elif PLATFORM in ('linux', 'macos'):
                return self._ctrl_v_xdotool()
        except Exception as e:
            print(f"Keyboard sim error: {e}")
        return False

    def _ctrl_v_windows(self) -> bool:
        """Send Ctrl+V to the target window.

        Multi-strategy paste for maximum compatibility:

        1. WM_PASTE via SendMessage (synchronous) to focused child control.
           Works for: Notepad, Notepad++, WordPad (standard Win32 edit ctrl).
           SendMessage waits for the app to process the message — more reliable
           than PostMessage (async) for apps that need time to handle it.

        2. WM_PASTE via PostMessage (async) — fallback for apps that deadlock
           on SendMessage from external threads.

        3. keybd_event Ctrl+V — for Chromium/Electron/UWP apps (Telegram,
           Opera, Chrome) that use keyboard hooks instead of WM_PASTE.
           Also used for OpenOffice which uses VCL toolkit and processes
           Ctrl+V through its own input pipeline, not WM_PASTE.

        4. pyautogui last resort.

        OpenOffice-specific: VCL toolkit intercepts keyboard input at a low
        level. WM_PASTE is ignored by VCL; the only reliable method is
        injecting actual key events (keybd_event). The "sometimes works"
        behaviour is caused by OpenOffice not having fully accepted focus
        before Ctrl+V arrives — solved by verifying foreground window before
        sending keys and retrying once if needed.
        """
        import ctypes
        import time

        VK_CONTROL      = 0x11
        VK_V            = 0x56
        KEYEVENTF_KEYUP = 0x0002
        WM_PASTE        = 0x0302

        u32  = ctypes.windll.user32
        k32  = ctypes.windll.kernel32

        target_hwnd = getattr(self, '_target_hwnd', None)

        # ── Helper: get focused child via AttachThreadInput ───────────────────
        def get_focused_child(hwnd):
            try:
                tid    = u32.GetWindowThreadProcessId(hwnd, None)
                my_tid = k32.GetCurrentThreadId()
                if not tid or tid == my_tid:
                    return hwnd
                attached = u32.AttachThreadInput(my_tid, tid, True)
                try:
                    focused = u32.GetFocus()
                    return focused if focused else hwnd
                finally:
                    if attached:
                        u32.AttachThreadInput(my_tid, tid, False)
            except Exception:
                return hwnd

        # ── Method 1: SendMessage WM_PASTE (synchronous, standard Win32) ─────
        # IMPORTANT: WM_PASTE ALWAYS returns 0 — never check `if result`!
        # SendMessage is synchronous, so by the time it returns the app has
        # already processed the paste. No foreground focus needed.
        if target_hwnd:
            try:
                paste_ctrl = get_focused_child(target_hwnd)
                u32.SendMessageW(paste_ctrl, WM_PASTE, 0, 0)
                time.sleep(0.05)
                return True   # SendMessage WM_PASTE always succeeds synchronously
            except Exception:
                pass

        # ── Method 2: PostMessage WM_PASTE (async fallback) ──────────────────
        if target_hwnd:
            try:
                paste_ctrl = get_focused_child(target_hwnd)
                if u32.PostMessageW(paste_ctrl, WM_PASTE, 0, 0):
                    time.sleep(0.1)
                    return True
            except Exception:
                pass

        # ── Method 3: keybd_event Ctrl+V with full focus enforcement ───────────
        # Used by: Telegram, Opera, Chrome, OpenOffice (VCL toolkit),
        # and any app that ignores WM_PASTE.
        #
        # CRITICAL FOR TRANSLATION MODE: after 5-15 seconds of Whisper processing
        # Windows revokes the right to call SetForegroundWindow (foreground lock).
        # Fix: temporarily set SPI_SETFOREGROUNDLOCKTIMEOUT=0 so SetForegroundWindow
        # works regardless of how much time has elapsed since last user input.
        # This is the same trick used by many professional automation tools.
        try:
            def _force_foreground(hwnd):
                """SetForegroundWindow with foreground-lock bypass."""
                try:
                    # Disable the foreground lock timeout so SetForegroundWindow
                    # always works, even after long background processing
                    SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
                    SPIF_SENDCHANGE = 0x0002
                    u32.SystemParametersInfoW(
                        SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                        ctypes.cast(ctypes.c_void_p(0), ctypes.c_void_p),
                        SPIF_SENDCHANGE
                    )
                except Exception:
                    pass

                try:
                    target_tid = u32.GetWindowThreadProcessId(hwnd, None)
                    my_tid     = k32.GetCurrentThreadId()
                    attached   = False
                    if target_tid and target_tid != my_tid:
                        attached = bool(u32.AttachThreadInput(my_tid, target_tid, True))
                    try:
                        if u32.IsIconic(hwnd):
                            u32.ShowWindow(hwnd, 9)   # SW_RESTORE
                            time.sleep(0.08)
                        u32.SetForegroundWindow(hwnd)
                        u32.BringWindowToTop(hwnd)
                    finally:
                        if attached:
                            u32.AttachThreadInput(my_tid, target_tid, False)
                except Exception:
                    pass

                # Poll up to 500ms for focus to actually switch
                deadline = time.time() + 0.5
                while time.time() < deadline:
                    time.sleep(0.02)
                    if u32.GetForegroundWindow() == hwnd:
                        time.sleep(0.05)
                        return True
                return False

            def send_ctrl_v():
                u32.keybd_event(VK_CONTROL, 0, 0, 0)
                u32.keybd_event(VK_V,       0, 0, 0)
                u32.keybd_event(VK_V,       0, KEYEVENTF_KEYUP, 0)
                u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

            if target_hwnd:
                if u32.GetForegroundWindow() != target_hwnd:
                    _force_foreground(target_hwnd)

            send_ctrl_v()
            time.sleep(0.08)
            return True
        except Exception:
            pass

        # ── Method 4: pyautogui last resort ──────────────────────────────────
        if self.PYAUTOGUI_AVAILABLE:
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(0.05)
                return True
            except Exception:
                pass

        return False

    def _ctrl_v_xdotool(self) -> bool:
        import subprocess
        import time
        time.sleep(0.05)
        try:
            result = subprocess.run(
                ['xdotool', 'key', '--clearmodifiers', 'ctrl+v'],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except FileNotFoundError:
            pass
        # macOS fallback
        if PLATFORM == 'macos':
            try:
                result = subprocess.run(
                    ['osascript', '-e',
                     'tell application "System Events" to keystroke "v" using command down'],
                    capture_output=True, timeout=5
                )
                return result.returncode == 0
            except Exception:
                pass
        return False

    def type_text(self, text: str) -> bool:
        """Type text character by character as fallback. Returns True on success."""
        try:
            if PLATFORM == 'windows' and self.PYAUTOGUI_AVAILABLE:
                import pyautogui
                pyautogui.write(text, interval=0.01)
                return True
            elif PLATFORM == 'linux':
                import subprocess
                result = subprocess.run(
                    ['xdotool', 'type', '--clearmodifiers', '--', text],
                    capture_output=True, timeout=30
                )
                return result.returncode == 0
            elif PLATFORM == 'macos':
                import subprocess
                escaped = text.replace('"', '\\"')
                result = subprocess.run(
                    ['osascript', '-e',
                     f'tell application "System Events" to type text "{escaped}"'],
                    capture_output=True, timeout=30
                )
                return result.returncode == 0
        except Exception as e:
            print(f"Type text error: {e}")
        return False


    def set_target_hwnd(self, hwnd):
        """Store target window handle so _ctrl_v_windows can use AttachThreadInput."""
        self._target_hwnd = hwnd

keyboard_sim = _KeyboardSim()


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

class _NotificationManager:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def notify(self, title: str, message: str, urgency: str = "normal"):
        if not self.enabled:
            return
        try:
            if PLATFORM == 'windows':
                self._notify_windows(title, message)
            elif PLATFORM == 'linux':
                self._notify_linux(title, message, urgency)
            elif PLATFORM == 'macos':
                self._notify_macos(title, message)
        except Exception:
            pass  # Notifications are non-critical

    def _notify_windows(self, title: str, message: str):
        try:
            from plyer import notification
            notification.notify(title=title, message=message, timeout=4)
            return
        except ImportError:
            pass
        try:
            import subprocess
            # Escape double-quotes so they don't break the PowerShell string
            safe_title   = title.replace('"'  , '`"')
            safe_message = message.replace('"', '`"')
            ps_cmd = (
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'$n = New-Object System.Windows.Forms.NotifyIcon; '
                f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
                f'$n.Visible = $true; '
                f'$n.ShowBalloonTip(3000, "{safe_title}", "{safe_message}", '
                f'[System.Windows.Forms.ToolTipIcon]::Info); '
                f'Start-Sleep -Seconds 4; $n.Dispose()'
            )
            subprocess.Popen(
                ['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps_cmd],
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
        except Exception:
            pass

    def _notify_linux(self, title: str, message: str, urgency: str):
        import subprocess
        urgency_map = {"low": "low", "normal": "normal", "critical": "critical"}
        urg = urgency_map.get(urgency, "normal")
        try:
            subprocess.Popen(
                ['notify-send', '-u', urg, title, message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            pass

    def _notify_macos(self, title: str, message: str):
        import subprocess
        try:
            # Escape double-quotes to prevent osascript string breakage
            safe_title   = title.replace('"'  , '\\\\"'  )
            safe_message = message.replace('"', '\\\\"'  )
            subprocess.Popen(
                ['osascript', '-e',
                 f'display notification "{safe_message}" with title "{safe_title}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass


class _NotificationsModule:
    NotificationManager = _NotificationManager


notifications = _NotificationsModule()


# ══════════════════════════════════════════════════════════════════════════════
# AUTOSTART
# ══════════════════════════════════════════════════════════════════════════════

class _Autostart:
    """Manage application autostart on login."""

    def enable(self, name: str, command: str) -> bool:
        """Enable autostart. Returns True on success."""
        try:
            if PLATFORM == 'windows':
                return self._enable_windows(name, command)
            elif PLATFORM == 'linux':
                return self._enable_linux(name, command)
            elif PLATFORM == 'macos':
                return self._enable_macos(name, command)
        except Exception as e:
            print(f"Autostart enable error: {e}")
        return False

    def disable(self, name: str) -> bool:
        """Disable autostart. Returns True on success."""
        try:
            if PLATFORM == 'windows':
                return self._disable_windows(name)
            elif PLATFORM == 'linux':
                return self._disable_linux(name)
            elif PLATFORM == 'macos':
                return self._disable_macos(name)
        except Exception as e:
            print(f"Autostart disable error: {e}")
        return False

    def _enable_windows(self, name: str, command: str) -> bool:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)
        return True

    def _disable_windows(self, name: str) -> bool:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        return True

    def _enable_linux(self, name: str, command: str) -> bool:
        from pathlib import Path
        autostart_dir = Path.home() / '.config' / 'autostart'
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop = autostart_dir / f"{name}.desktop"
        desktop.write_text(
            f"[Desktop Entry]\nType=Application\nName={name}\n"
            f"Exec={command}\nHidden=false\nNoDisplay=false\n"
            f"X-GNOME-Autostart-enabled=true\n",
            encoding='utf-8'
        )
        return True

    def _disable_linux(self, name: str) -> bool:
        from pathlib import Path
        desktop = Path.home() / '.config' / 'autostart' / f"{name}.desktop"
        if desktop.exists():
            desktop.unlink()
        return True

    def _enable_macos(self, name: str, command: str) -> bool:
        from pathlib import Path
        launch_agents = Path.home() / 'Library' / 'LaunchAgents'
        launch_agents.mkdir(parents=True, exist_ok=True)
        plist = launch_agents / f"com.{name}.plist"
        plist.write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>com.{name}</string>\n'
            f'  <key>ProgramArguments</key><array>'
            f'{"".join(f"<string>{a}</string>" for a in __import__("shlex").split(command))}'
            f'</array>\n'
            f'  <key>RunAtLoad</key><true/>\n'
            f'</dict></plist>\n',
            encoding='utf-8'
        )
        return True

    def _disable_macos(self, name: str) -> bool:
        from pathlib import Path
        plist = Path.home() / 'Library' / 'LaunchAgents' / f"com.{name}.plist"
        if plist.exists():
            plist.unlink()
        return True


autostart = _Autostart()
