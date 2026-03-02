import asyncio
import os
import subprocess

import config
from app_controller import AppController
from browser_controller import BrowserController
from claude_manager import ClaudeManager
from file_manager import FileManager
from twilio_manager import TwilioManager


class ToolExecutor:
    def __init__(self, browser: BrowserController, claude: ClaudeManager):
        self.browser = browser
        self.claude = claude
        self.files = FileManager()
        self.apps = AppController()
        self.twilio = TwilioManager()

    async def execute(self, function_name: str, args: dict) -> dict:
        try:
            match function_name:
                # Browser tools
                case "browser_navigate":
                    result = await self.browser.navigate(args["url"])
                case "browser_click":
                    result = await self.browser.click(args["selector"])
                case "browser_type":
                    result = await self.browser.type_text(args["selector"], args["text"])
                case "browser_read_page":
                    result = await self.browser.read_page()
                case "browser_screenshot":
                    result = await self.browser.screenshot()
                # Claude tools
                case "run_claude_task":
                    result = await self.claude.spawn_task(
                        args["prompt"],
                        args.get("project_name", "Untitled Project"),
                        args.get("working_directory"),
                    )

                case "check_claude_tasks":
                    tasks = self.claude.get_tasks()
                    if not tasks:
                        result = "No Claude tasks running or completed."
                    else:
                        result = str(tasks)
                # File management tools
                case "file_list":
                    result = self.files.list_directory(args.get("path"))
                case "file_info":
                    result = self.files.file_info(args["path"])
                case "file_read":
                    result = self.files.read_file(args["path"])
                case "file_mkdir":
                    result = self.files.create_directory(args["path"])
                case "file_move":
                    result = self.files.move(args["source"], args["destination"])
                case "file_copy":
                    result = self.files.copy(args["source"], args["destination"])
                case "file_delete":
                    result = self.files.delete(args["path"])
                case "file_open_explorer":
                    result = self.files.open_in_explorer(args.get("path"))
                case "file_open":
                    result = self.files.open_file(args["path"])
                case "file_search":
                    result = self.files.search(args["directory"], args["pattern"])
                case "file_close_explorer":
                    result = self.files.close_explorer()
                # App management tools
                case "app_open":
                    result = self.apps.open_app(args["name"])
                case "app_close":
                    result = self.apps.close_app(args["name"])
                case "app_list":
                    result = self.apps.list_running()
                case "window_manage":
                    result = self.apps.manage_window(args["name"], args["action"])
                case "window_move_to_monitor":
                    result = self.apps.move_to_monitor(
                        args["name"], int(args["monitor"]),
                        args.get("maximize", True)
                    )
                case "open_chrome_url":
                    result = self.apps.open_chrome_url(args["url"])
                case "open_rdp":
                    result = self.apps.open_rdp(args["host"])
                # Twilio tools
                case "send_sms":
                    result = self.twilio.send_sms(
                        args["message"],
                        args.get("to"),
                    )
                case "add_contact":
                    result = self.twilio.add_contact(
                        args["name"],
                        args["phone"],
                    )
                case "get_contacts":
                    result = self.twilio.get_contacts()
                # System command execution
                case "run_command":
                    result = await self._run_command(
                        args["command"],
                        args.get("working_directory"),
                        args.get("timeout", 30),
                    )
                case _:
                    result = f"Unknown function: {function_name}"
            return {"result": result}
        except Exception as e:
            print(f"[tools] Error in {function_name}: {e}")
            return {"error": str(e)}

    async def _run_command(self, command: str, working_dir: str | None, timeout: int) -> str:
        """Execute a shell command via PowerShell and return output."""
        cwd = working_dir or config.DEFAULT_WORKING_DIR
        print(f"[cmd] Running: {command[:120]}...")
        loop = asyncio.get_running_loop()

        def _exec():
            try:
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", command],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = ""
                if proc.stdout:
                    output += proc.stdout
                if proc.stderr:
                    output += f"\nSTDERR: {proc.stderr}"
                if proc.returncode != 0:
                    output += f"\n(exit code {proc.returncode})"
                return output.strip()[:4000] or "(no output)"
            except subprocess.TimeoutExpired:
                return f"Command timed out after {timeout}s"
            except Exception as e:
                return f"Command failed: {e}"

        return await loop.run_in_executor(None, _exec)
