import subprocess

import config


# Common app names -> executable paths or start menu names
APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "terminal": "wt.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
    "snipping tool": "snippingtool.exe",
    "spotify": "spotify",
    "discord": "discord",
    "steam": "steam",
    "vlc": "vlc",
    "obs": "obs64",
    "vscode": "code",
    "visual studio code": "code",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "brave": "brave",
    "apple music": "shell:AppsFolder\\AppleInc.AppleMusicWin_nzyj5cx40ttqa!App",
    "music": "shell:AppsFolder\\AppleInc.AppleMusicWin_nzyj5cx40ttqa!App",
    "itunes": "shell:AppsFolder\\AppleInc.AppleMusicWin_nzyj5cx40ttqa!App",
    "apple devices": "shell:AppsFolder\\AppleInc.AppleDevices_nzyj5cx40ttqa!App",
}

# Process names for killing (maps friendly name -> process image name)
PROCESS_NAMES = {
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "terminal": "WindowsTerminal.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "Taskmgr.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "steam": "steam.exe",
    "vlc": "vlc.exe",
    "obs": "obs64.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "brave": "brave.exe",
    "apple music": "AppleMusic.exe",
    "music": "AppleMusic.exe",
    "itunes": "AppleMusic.exe",
}


class AppController:
    def open_app(self, name: str) -> str:
        key = name.lower().strip()
        exe = APP_ALIASES.get(key)

        try:
            if exe:
                if exe.startswith("ms-"):
                    # Windows URI scheme (Settings, etc.)
                    subprocess.Popen(["start", exe], shell=True)
                elif exe.startswith("shell:"):
                    # Microsoft Store app - launch via explorer
                    subprocess.Popen(["explorer", exe])
                else:
                    subprocess.Popen(["start", "", exe], shell=True)
                return f"Opened {name}"
            else:
                # Try launching directly - Windows will search PATH and Start Menu
                subprocess.Popen(["start", "", name], shell=True)
                return f"Opened {name}"
        except Exception as e:
            return f"Error opening {name}: {e}"

    def close_app(self, name: str) -> str:
        key = name.lower().strip()
        process = PROCESS_NAMES.get(key)

        if not process:
            # Try the name directly as a process name
            process = name if name.endswith(".exe") else f"{name}.exe"

        try:
            result = subprocess.run(
                ["taskkill", "/im", process, "/f"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return f"Closed {name}"
            elif "not found" in result.stderr.lower():
                return f"{name} doesn't appear to be running"
            else:
                return f"Could not close {name}: {result.stderr.strip()}"
        except Exception as e:
            return f"Error closing {name}: {e}"

    def _find_window_ps(self, name: str) -> str:
        """PowerShell snippet to find a window by partial title match and return its handle."""
        # Escaping for PowerShell
        safe = name.replace("'", "''")
        return (
            f"$p = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{safe}*' -and $_.MainWindowHandle -ne 0 }} | "
            f"Select-Object -First 1; "
            f"if ($p) {{ $p.MainWindowHandle }} else {{ 'NOT_FOUND' }}"
        )

    def manage_window(self, name: str, action: str) -> str:
        """Maximize, minimize, restore, or focus a window by app name."""
        # Map actions to Win32 ShowWindow constants
        sw_commands = {
            "maximize": 3,    # SW_MAXIMIZE
            "minimize": 6,    # SW_MINIMIZE
            "restore": 9,     # SW_RESTORE
            "focus": 9,       # SW_RESTORE (then SetForegroundWindow)
        }

        action_lower = action.lower().strip()
        sw = sw_commands.get(action_lower)
        if sw is None:
            return f"Unknown action '{action}'. Use: maximize, minimize, restore, or focus."

        safe_name = name.replace("'", "''")
        ps_script = (
            f"Add-Type @'\n"
            f"using System;\n"
            f"using System.Runtime.InteropServices;\n"
            f"public class Win32 {{\n"
            f"  [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);\n"
            f"  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
            f"}}\n"
            f"'@\n"
            f"$p = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{safe_name}*' -and $_.MainWindowHandle -ne 0 }} | Select-Object -First 1\n"
            f"if ($p) {{\n"
            f"  [Win32]::ShowWindow($p.MainWindowHandle, {sw})\n"
            f"  [Win32]::SetForegroundWindow($p.MainWindowHandle)\n"
            f"  'OK'\n"
            f"}} else {{\n"
            f"  'NOT_FOUND'\n"
            f"}}"
        )

        try:
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.strip()
            if "NOT_FOUND" in output:
                return f"Couldn't find a window matching '{name}'"
            if "OK" in output or result.returncode == 0:
                return f"{action.capitalize()}d {name}"
            return f"Failed to {action} {name}: {result.stderr.strip()}"
        except Exception as e:
            return f"Error: {e}"

    def open_chrome_url(self, url: str) -> str:
        """Open a URL in real Chrome (not Playwright)."""
        try:
            subprocess.Popen(["start", "chrome", url], shell=True)
            return f"Opened Chrome with {url}"
        except Exception as e:
            return f"Error: {e}"

    def move_to_monitor(self, name: str, monitor: int, maximize: bool = True) -> str:
        """Move a window to a specific monitor number (1, 2, or 3) and optionally maximize."""
        safe_name = name.replace("'", "''")
        monitor_bounds = config.MONITOR_POSITIONS
        if monitor not in monitor_bounds:
            return f"Invalid monitor {monitor}. Use 1 (left), 2 (center/primary), or 3 (right)."

        x, y, w, h = monitor_bounds[monitor]
        sw_cmd = 3 if maximize else 9  # SW_MAXIMIZE or SW_RESTORE

        ps_script = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32 {\n"
            "  [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);\n"
            "  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
            "  [DllImport(\"user32.dll\")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);\n"
            "}\n"
            "'@\n"
            f"$p = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{safe_name}*' -and $_.MainWindowHandle -ne 0 }} | Select-Object -First 1\n"
            "if ($p) {\n"
            "  [Win32]::ShowWindow($p.MainWindowHandle, 9)\n"  # Restore first so MoveWindow works
            f"  [Win32]::MoveWindow($p.MainWindowHandle, {x}, {y}, {w}, {h}, $true)\n"
            f"  [Win32]::ShowWindow($p.MainWindowHandle, {sw_cmd})\n"
            "  [Win32]::SetForegroundWindow($p.MainWindowHandle)\n"
            "  'OK'\n"
            "} else {\n"
            "  'NOT_FOUND'\n"
            "}"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.strip()
            if "NOT_FOUND" in output:
                return f"Couldn't find a window matching '{name}'"
            action = "Maximized" if maximize else "Moved"
            return f"{action} {name} on monitor {monitor}"
        except Exception as e:
            return f"Error: {e}"

    def open_rdp(self, host: str) -> str:
        """Open Remote Desktop to a specific host."""
        try:
            subprocess.Popen(["mstsc", f"/v:{host}"])
            return f"Launched Remote Desktop to {host}"
        except Exception as e:
            return f"Error: {e}"

    def list_running(self) -> str:
        """List notable running applications."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                 "Select-Object ProcessName, MainWindowTitle | "
                 "Format-Table -AutoSize | Out-String -Width 200"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.strip()
            if not output:
                return "No windowed applications found"
            return f"Running applications:\n{output}"
        except Exception as e:
            return f"Error: {e}"
