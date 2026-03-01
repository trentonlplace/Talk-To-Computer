import os
import shutil
import subprocess
import time

import config


def _check_allowed(path: str) -> str | None:
    """Return error string if path is outside allowed directories, else None."""
    real = os.path.realpath(path)
    for allowed in config.ALLOWED_DIRECTORIES:
        if real.startswith(os.path.realpath(allowed)):
            return None
    return f"BLOCKED: '{path}' is outside allowed directories"


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


class FileManager:
    def list_directory(self, path: str | None = None) -> str:
        path = path or config.DEFAULT_WORKING_DIR
        err = _check_allowed(path)
        if err:
            return err
        try:
            entries = os.listdir(path)
            if not entries:
                return f"{path} is empty"

            lines = []
            dirs = []
            files = []
            for name in sorted(entries):
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    dirs.append(f"[DIR]  {name}")
                else:
                    try:
                        size = _format_size(os.path.getsize(full))
                    except OSError:
                        size = "?"
                    files.append(f"       {name}  ({size})")

            lines = dirs + files
            header = f"Contents of {path} ({len(dirs)} folders, {len(files)} files):"
            return header + "\n" + "\n".join(lines[:50])
        except Exception as e:
            return f"Error listing {path}: {e}"

    def file_info(self, path: str) -> str:
        err = _check_allowed(path)
        if err:
            return err
        try:
            stat = os.stat(path)
            kind = "Directory" if os.path.isdir(path) else "File"
            return (
                f"{kind}: {os.path.basename(path)}\n"
                f"Path: {os.path.realpath(path)}\n"
                f"Size: {_format_size(stat.st_size)}\n"
                f"Modified: {_format_time(stat.st_mtime)}\n"
                f"Created: {_format_time(stat.st_ctime)}"
            )
        except Exception as e:
            return f"Error: {e}"

    def read_file(self, path: str) -> str:
        err = _check_allowed(path)
        if err:
            return err
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(4000)
            if len(content) == 4000:
                content += "\n... (truncated)"
            return content
        except Exception as e:
            return f"Error reading {path}: {e}"

    def create_directory(self, path: str) -> str:
        err = _check_allowed(path)
        if err:
            return err
        try:
            os.makedirs(path, exist_ok=True)
            return f"Created directory: {path}"
        except Exception as e:
            return f"Error: {e}"

    def move(self, source: str, destination: str) -> str:
        for p in (source, destination):
            err = _check_allowed(p)
            if err:
                return err
        try:
            shutil.move(source, destination)
            return f"Moved {source} -> {destination}"
        except Exception as e:
            return f"Error: {e}"

    def copy(self, source: str, destination: str) -> str:
        for p in (source, destination):
            err = _check_allowed(p)
            if err:
                return err
        try:
            if os.path.isdir(source):
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            return f"Copied {source} -> {destination}"
        except Exception as e:
            return f"Error: {e}"

    def delete(self, path: str) -> str:
        err = _check_allowed(path)
        if err:
            return err
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                return f"Deleted directory: {path}"
            else:
                os.remove(path)
                return f"Deleted file: {path}"
        except Exception as e:
            return f"Error: {e}"

    def open_in_explorer(self, path: str | None = None) -> str:
        path = path or config.DEFAULT_WORKING_DIR
        err = _check_allowed(path)
        if err:
            return err
        try:
            if os.path.isfile(path):
                # Open containing folder with file selected
                subprocess.Popen(["explorer", "/select,", os.path.realpath(path)])
            else:
                subprocess.Popen(["explorer", os.path.realpath(path)])
            return f"Opened Explorer at {path}"
        except Exception as e:
            return f"Error: {e}"

    def open_file(self, path: str) -> str:
        """Open a file with its default application."""
        err = _check_allowed(path)
        if err:
            return err
        try:
            os.startfile(os.path.realpath(path))
            return f"Opened {os.path.basename(path)}"
        except Exception as e:
            return f"Error: {e}"

    def close_explorer(self) -> str:
        """Close all File Explorer folder windows (not the taskbar)."""
        try:
            # Use COM to close only folder windows, leaves taskbar alone
            ps_script = (
                '(New-Object -ComObject Shell.Application).Windows() | '
                'ForEach-Object { $_.Quit() }'
            )
            subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=5
            )
            return "Closed all File Explorer windows"
        except Exception as e:
            return f"Error: {e}"

    def search(self, directory: str, pattern: str) -> str:
        """Search for files matching a name pattern in a directory."""
        err = _check_allowed(directory)
        if err:
            return err
        try:
            matches = []
            pattern_lower = pattern.lower()
            for root, dirs, files in os.walk(directory):
                for name in files:
                    if pattern_lower in name.lower():
                        full = os.path.join(root, name)
                        matches.append(full)
                        if len(matches) >= 20:
                            break
                if len(matches) >= 20:
                    break

            if not matches:
                return f"No files matching '{pattern}' found in {directory}"
            result = f"Found {len(matches)} file(s) matching '{pattern}':\n"
            result += "\n".join(matches)
            if len(matches) == 20:
                result += "\n... (showing first 20)"
            return result
        except Exception as e:
            return f"Error: {e}"
