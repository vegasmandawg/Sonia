"""
OpenClaw Desktop Executor — Stage 5 M3
Implements desktop automation actions: app launch/close, window management,
keyboard/mouse input, and clipboard operations.
All operations are Windows-native using subprocess and ctypes.
"""

import os
import time
import subprocess
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


class DesktopExecutor:
    """
    Executes desktop automation operations.
    All operations return (success, result_dict, error_string).
    """

    DEFAULT_TIMEOUT_MS = 5000
    MAX_TIMEOUT_MS = 30000

    # ── App Launch ────────────────────────────────────────────────────

    def app_launch(
        self,
        target: str,
        args: Optional[List[str]] = None,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Launch an application by name or path."""
        start_time = time.time()

        if not target:
            return False, {}, "target is required"

        # Safety: block obviously dangerous targets
        blocked = {"format", "del", "rmdir", "rd", "shutdown", "restart"}
        base = os.path.splitext(os.path.basename(target))[0].lower()
        if base in blocked:
            return False, {}, f"Target '{target}' is blocked for safety"

        try:
            cmd = [target] + (args or [])
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            elapsed = round((time.time() - start_time) * 1000, 2)
            return True, {
                "pid": proc.pid,
                "target": target,
                "args": args or [],
                "duration_ms": elapsed,
            }, None

        except FileNotFoundError:
            return False, {}, f"Application not found: {target}"
        except OSError as e:
            return False, {}, f"OS error launching {target}: {e}"
        except Exception as e:
            return False, {}, f"Failed to launch {target}: {e}"

    # ── App Close ─────────────────────────────────────────────────────

    def app_close(
        self,
        target: str,
        force: bool = False,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Close an application by name."""
        start_time = time.time()

        if not target:
            return False, {}, "target is required"

        try:
            # Use taskkill to close the application
            base = os.path.splitext(os.path.basename(target))[0]
            cmd = ["taskkill"]
            if force:
                cmd.append("/F")
            cmd.extend(["/IM", f"{base}.exe"])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            elapsed = round((time.time() - start_time) * 1000, 2)

            if result.returncode == 0:
                return True, {
                    "target": target,
                    "force": force,
                    "output": result.stdout.strip(),
                    "duration_ms": elapsed,
                }, None
            else:
                return False, {}, f"taskkill failed: {result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return False, {}, f"Timeout closing {target}"
        except Exception as e:
            return False, {}, f"Failed to close {target}: {e}"

    # ── Window List ───────────────────────────────────────────────────

    def window_list(
        self,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """List visible windows with titles."""
        start_time = time.time()

        try:
            user32 = ctypes.windll.user32
            windows = []

            def enum_callback(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if buf.value.strip():
                            windows.append({
                                "hwnd": hwnd,
                                "title": buf.value,
                            })
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
            )
            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

            elapsed = round((time.time() - start_time) * 1000, 2)
            return True, {
                "windows": windows,
                "count": len(windows),
                "duration_ms": elapsed,
            }, None

        except Exception as e:
            return False, {}, f"Failed to list windows: {e}"

    # ── Window Focus ──────────────────────────────────────────────────

    def window_focus(
        self,
        title: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Focus a window by title (partial match)."""
        start_time = time.time()

        if not title:
            return False, {}, "title is required"

        try:
            user32 = ctypes.windll.user32
            target_hwnd = None
            target_title = ""

            def enum_callback(hwnd, _):
                nonlocal target_hwnd, target_title
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if title.lower() in buf.value.lower():
                            target_hwnd = hwnd
                            target_title = buf.value
                            return False  # Stop enumeration
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
            )
            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

            if target_hwnd is None:
                return False, {}, f"No window found matching '{title}'"

            user32.SetForegroundWindow(target_hwnd)
            elapsed = round((time.time() - start_time) * 1000, 2)
            return True, {
                "hwnd": target_hwnd,
                "title": target_title,
                "duration_ms": elapsed,
            }, None

        except Exception as e:
            return False, {}, f"Failed to focus window '{title}': {e}"

    # ── Keyboard Type ─────────────────────────────────────────────────

    def keyboard_type(
        self,
        text: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Type text using PowerShell SendKeys (safe, no raw input injection)."""
        start_time = time.time()

        if not text:
            return False, {}, "text is required"

        # Limit length for safety
        if len(text) > 1000:
            return False, {}, "Text too long (max 1000 chars)"

        try:
            # Use PowerShell Add-Type + SendKeys for safety
            escaped = text.replace("'", "''")
            ps_cmd = (
                f"Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}')"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            elapsed = round((time.time() - start_time) * 1000, 2)

            if result.returncode == 0:
                return True, {
                    "chars_typed": len(text),
                    "duration_ms": elapsed,
                }, None
            else:
                return False, {}, f"SendKeys failed: {result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return False, {}, "Keyboard type timed out"
        except Exception as e:
            return False, {}, f"Failed to type text: {e}"

    # ── Keyboard Hotkey ───────────────────────────────────────────────

    def keyboard_hotkey(
        self,
        keys: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Send a keyboard hotkey combo (e.g. 'ctrl+c', 'alt+f4')."""
        start_time = time.time()

        if not keys:
            return False, {}, "keys is required"

        # Block dangerous hotkeys
        dangerous = {"alt+f4", "ctrl+alt+delete", "ctrl+alt+del"}
        if keys.lower().replace(" ", "") in {d.replace(" ", "") for d in dangerous}:
            return False, {}, f"Hotkey '{keys}' is blocked for safety"

        try:
            # Map key names to SendKeys format
            key_map = {
                "ctrl": "^", "control": "^",
                "alt": "%", "shift": "+",
                "enter": "{ENTER}", "return": "{ENTER}",
                "tab": "{TAB}", "escape": "{ESC}", "esc": "{ESC}",
                "backspace": "{BACKSPACE}", "delete": "{DELETE}",
                "up": "{UP}", "down": "{DOWN}",
                "left": "{LEFT}", "right": "{RIGHT}",
                "home": "{HOME}", "end": "{END}",
                "pageup": "{PGUP}", "pagedown": "{PGDN}",
                "f1": "{F1}", "f2": "{F2}", "f3": "{F3}", "f4": "{F4}",
                "f5": "{F5}", "f6": "{F6}", "f7": "{F7}", "f8": "{F8}",
                "f9": "{F9}", "f10": "{F10}", "f11": "{F11}", "f12": "{F12}",
            }

            parts = [p.strip().lower() for p in keys.split("+")]
            sendkeys_str = ""
            for part in parts:
                if part in key_map:
                    sendkeys_str += key_map[part]
                elif len(part) == 1:
                    sendkeys_str += part
                else:
                    return False, {}, f"Unknown key: '{part}'"

            ps_cmd = (
                f"Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.SendKeys]::SendWait('{sendkeys_str}')"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            elapsed = round((time.time() - start_time) * 1000, 2)

            if result.returncode == 0:
                return True, {
                    "keys": keys,
                    "sendkeys": sendkeys_str,
                    "duration_ms": elapsed,
                }, None
            else:
                return False, {}, f"Hotkey failed: {result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return False, {}, "Keyboard hotkey timed out"
        except Exception as e:
            return False, {}, f"Failed to send hotkey: {e}"

    # ── Mouse Click ───────────────────────────────────────────────────

    def mouse_click(
        self,
        x: int,
        y: int,
        button: str = "left",
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Click at screen coordinates."""
        start_time = time.time()

        if x is None or y is None:
            return False, {}, "x and y coordinates are required"

        # Bounds check (reasonable screen limits)
        if x < 0 or y < 0 or x > 7680 or y > 4320:
            return False, {}, f"Coordinates ({x}, {y}) out of bounds"

        try:
            user32 = ctypes.windll.user32
            # Move cursor
            user32.SetCursorPos(x, y)

            # Click events
            if button == "left":
                user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            elif button == "right":
                user32.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
                user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
            else:
                return False, {}, f"Unknown button: '{button}' (use 'left' or 'right')"

            elapsed = round((time.time() - start_time) * 1000, 2)
            return True, {
                "x": x, "y": y, "button": button,
                "duration_ms": elapsed,
            }, None

        except Exception as e:
            return False, {}, f"Mouse click failed: {e}"

    # ── Clipboard Read ────────────────────────────────────────────────

    def clipboard_read(
        self,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Read text from the Windows clipboard."""
        start_time = time.time()

        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
            elapsed = round((time.time() - start_time) * 1000, 2)

            if result.returncode == 0:
                text = result.stdout.rstrip("\n")
                return True, {
                    "text": text,
                    "length": len(text),
                    "duration_ms": elapsed,
                }, None
            else:
                return False, {}, f"Clipboard read failed: {result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return False, {}, "Clipboard read timed out"
        except Exception as e:
            return False, {}, f"Failed to read clipboard: {e}"

    # ── Clipboard Write ───────────────────────────────────────────────

    def clipboard_write(
        self,
        text: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Write text to the Windows clipboard."""
        start_time = time.time()

        if text is None:
            return False, {}, "text is required"

        # Limit length for safety
        if len(text) > 100000:
            return False, {}, "Text too long for clipboard (max 100000 chars)"

        try:
            result = subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)+chr(39))}'"],
                capture_output=True, text=True, timeout=5,
            )
            elapsed = round((time.time() - start_time) * 1000, 2)

            if result.returncode == 0:
                return True, {
                    "chars_written": len(text),
                    "duration_ms": elapsed,
                }, None
            else:
                return False, {}, f"Clipboard write failed: {result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return False, {}, "Clipboard write timed out"
        except Exception as e:
            return False, {}, f"Failed to write clipboard: {e}"
