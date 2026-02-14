"""
OpenClaw Notification Executor
Sends Windows toast notifications using PowerShell.

notification.send — Show a Windows 10/11 toast notification.
"""

import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


class NotificationExecutor:
    """Sends Windows toast notifications."""

    DEFAULT_TIMEOUT_MS = 5000
    MAX_TIMEOUT_MS = 10000
    MAX_TITLE_LENGTH = 100
    MAX_BODY_LENGTH = 500

    def __init__(self):
        self.execution_log: List[Dict[str, Any]] = []

    def send(
        self,
        title: str,
        body: str = "",
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Send a Windows toast notification.

        Args:
            title: Notification title text.
            body: Notification body text (optional).
            timeout_ms: Execution timeout in milliseconds.
            correlation_id: Correlation ID for tracing.

        Returns:
            (success, result_dict, error_message)
        """
        start = time.time()
        timeout_ms = min(timeout_ms or self.DEFAULT_TIMEOUT_MS, self.MAX_TIMEOUT_MS)

        if not title or not title.strip():
            return False, {}, "title is required"

        # Sanitize inputs
        title = title.strip()[:self.MAX_TITLE_LENGTH]
        body = (body or "").strip()[:self.MAX_BODY_LENGTH]

        # Escape for PowerShell string literals
        title_escaped = title.replace("'", "''").replace("`", "``")
        body_escaped = body.replace("'", "''").replace("`", "``")

        # Build PowerShell script for toast notification
        # Uses BurntToast module if available, falls back to .NET
        ps_script = self._build_toast_script(title_escaped, body_escaped)

        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
                encoding="utf-8",
                errors="replace",
            )

            elapsed = (time.time() - start) * 1000

            if result.returncode == 0:
                self._log("send", title=title, success=True,
                          elapsed_ms=elapsed, correlation_id=correlation_id)
                return True, {
                    "title": title,
                    "body": body,
                    "sent": True,
                    "elapsed_ms": round(elapsed, 1),
                }, None
            else:
                error = result.stderr.strip()[:200] if result.stderr else "Unknown error"
                self._log("send", title=title, success=False,
                          error=error, elapsed_ms=elapsed,
                          correlation_id=correlation_id)
                return False, {}, f"Notification failed: {error}"

        except subprocess.TimeoutExpired:
            elapsed = (time.time() - start) * 1000
            self._log("send", title=title, success=False,
                      error="timeout", elapsed_ms=elapsed,
                      correlation_id=correlation_id)
            return False, {}, "Notification timed out"
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self._log("send", title=title, success=False,
                      error=str(e), elapsed_ms=elapsed,
                      correlation_id=correlation_id)
            return False, {}, f"Notification error: {e}"

    @staticmethod
    def _build_toast_script(title: str, body: str) -> str:
        """Build PowerShell toast notification script.

        Uses .NET Windows.UI.Notifications API (works on Win10/11 without
        any extra modules). Falls back to a simple balloon notification
        via System.Windows.Forms if the modern API fails.
        """
        if body:
            xml_body = f"<text>{body}</text>"
        else:
            xml_body = ""

        return f"""
try {{
    # Modern toast (Win10/11)
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

    $xml = @'
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      {xml_body}
    </binding>
  </visual>
</toast>
'@

    $doc = [Windows.Data.Xml.Dom.XmlDocument]::new()
    $doc.LoadXml($xml)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SONIA')
    $notifier.Show($toast)
    Write-Output 'toast_sent'
}} catch {{
    # Fallback: balloon tip via System.Windows.Forms
    try {{
        Add-Type -AssemblyName System.Windows.Forms
        $icon = [System.Windows.Forms.ToolTipIcon]::Info
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $notify.ShowBalloonTip(5000, '{title}', '{body}', $icon)
        Start-Sleep -Seconds 3
        $notify.Dispose()
        Write-Output 'balloon_sent'
    }} catch {{
        Write-Error "Failed to send notification: $($_.Exception.Message)"
        exit 1
    }}
}}
"""

    def _log(self, operation: str, elapsed_ms: float = 0, success: bool = True,
             error: Optional[str] = None, correlation_id: Optional[str] = None,
             **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "operation": operation,
            "success": success,
            "elapsed_ms": round(elapsed_ms, 1),
            "correlation_id": correlation_id,
        }
        entry.update(kwargs)
        if error:
            entry["error"] = error
        self.execution_log.append(entry)

    def get_execution_log(self) -> List[Dict[str, Any]]:
        return self.execution_log.copy()
