import asyncio
import glob
import os
import subprocess
import sys
import time
import uuid

import config


class ClaudeProject:
    def __init__(self, name: str, working_dir: str):
        self.name = name
        self.working_dir = working_dir
        self.process: subprocess.Popen | None = None
        self.task_dir: str = ""
        self.tasks: list[dict] = []
        self.started_at = time.time()


class ClaudeManager:
    def __init__(self):
        self.projects: dict[str, ClaudeProject] = {}
        self._base_dir = config.CLAUDE_LOGS_DIR
        os.makedirs(self._base_dir, exist_ok=True)
        # Callback: called with (project_name, output) when a task completes
        self.on_task_complete = None
        # Recover prior projects from disk
        self._recover_projects()

    def _recover_projects(self):
        """Scan claude_logs/ on startup to recover prior project history."""
        for entry in os.scandir(self._base_dir):
            if not entry.is_dir():
                continue
            project_name = entry.name.replace("_", " ")
            project = ClaudeProject(project_name, config.DEFAULT_WORKING_DIR)
            project.task_dir = entry.path

            # Recover tasks from .done, .error, .running, .pending files
            seen_ids = set()
            for pattern, status in [("*.done", None), ("*.error", "error"),
                                    ("*.running", "interrupted"), ("*.pending", "pending")]:
                for path in glob.glob(os.path.join(entry.path, pattern)):
                    tid = os.path.basename(path).split(".")[0]
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)

                    task = {
                        "task_id": tid,
                        "prompt": "",
                        "status": status or "completed",
                        "started_at": os.path.getmtime(path),
                        "finished_at": os.path.getmtime(path),
                    }

                    # For .done files, check exit code
                    if pattern == "*.done":
                        try:
                            with open(path, "r") as f:
                                code = f.read().strip()
                            task["status"] = "completed" if code == "0" else "failed"
                        except Exception:
                            task["status"] = "completed"

                    # Read log output if available
                    log_file = os.path.join(entry.path, f"{tid}.log")
                    if os.path.exists(log_file):
                        try:
                            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                                task["output"] = f.read()
                        except Exception:
                            pass

                    project.tasks.append(task)

            if project.tasks:
                # Sort tasks by start time
                project.tasks.sort(key=lambda t: t["started_at"])
                self.projects[project_name] = project

        if self.projects:
            print(f"[claude] Recovered {len(self.projects)} prior projects from disk")

    @staticmethod
    def _escape_prompt(prompt: str) -> str:
        """Escape a prompt string for safe embedding in a cmd.exe double-quoted argument."""
        return prompt.replace('"', "'").replace("%", "%%")

    def _is_project_alive(self, project: ClaudeProject) -> bool:
        return project.process is not None and project.process.poll() is None

    def _launch_claude(
        self,
        prompt_file: str,
        working_dir: str,
        project_name: str,
        env: dict,
        continue_session: bool = False,
    ) -> subprocess.Popen:
        """Launch Claude Code in a new console, reading the prompt from a file.

        Uses a Python launcher script to bypass cmd.exe's ~8K command line
        length limit. The prompt is read from disk and passed directly via
        subprocess (CreateProcess has a 32K limit).
        """
        safe_title = project_name.replace('"', '\\"')
        launcher = os.path.join(os.path.dirname(prompt_file), os.path.basename(prompt_file).replace(".prompt", "_launch.py"))
        continue_flag = " '--continue'," if continue_session else ""
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(f'''import subprocess, sys, os
os.system('title Claude - {safe_title}')
with open(r"{prompt_file}", "r", encoding="utf-8") as f:
    prompt = f.read()
args = ["claude", "--dangerously-skip-permissions",{continue_flag} prompt]
subprocess.run(args)
input("\\nClaude session ended. Press Enter to close...")
''')
        return subprocess.Popen(
            [sys.executable, launcher],
            cwd=working_dir,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    async def spawn_task(
        self, prompt: str, project_name: str, working_dir: str | None = None
    ) -> str:
        if not working_dir:
            working_dir = config.DEFAULT_WORKING_DIR

        # Security: validate working directory
        real_dir = os.path.realpath(working_dir)
        allowed = any(
            real_dir.startswith(os.path.realpath(d))
            for d in config.ALLOWED_DIRECTORIES
        )
        if not allowed:
            return f"BLOCKED: Directory '{working_dir}' is not in allowed paths"

        # Check if project already exists and is running
        project = self.projects.get(project_name)

        if project and self._is_project_alive(project):
            # Project session is alive - send follow-up in a new window with --continue
            task_id = uuid.uuid4().hex[:8]
            project.tasks.append(
                {
                    "task_id": task_id,
                    "prompt": prompt,
                    "status": "running",
                    "started_at": time.time(),
                }
            )

            # Write prompt to file — avoids cmd.exe 8K command line length limit
            prompt_file = os.path.join(project.task_dir, f"{task_id}.prompt")
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(prompt)

            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            # Use Python launcher to bypass cmd.exe length limits
            new_proc = self._launch_claude(
                prompt_file, project.working_dir, project_name, env,
                continue_session=True,
            )
            project.process = new_proc

            print(f"[claude] Follow-up in '{project_name}': {prompt[:80]}...")
            return f"Follow-up task sent to project '{project_name}'"

        # New project (or dead session) - create session
        project = ClaudeProject(project_name, working_dir)
        safe_name = project_name.replace(" ", "_").replace("/", "_")[:40]
        project.task_dir = os.path.join(self._base_dir, safe_name)
        os.makedirs(project.task_dir, exist_ok=True)

        # Clean any leftover task files from previous session
        for old in glob.glob(os.path.join(project.task_dir, "*.pending")):
            os.remove(old)
        for old in glob.glob(os.path.join(project.task_dir, "*.running")):
            os.remove(old)

        # Write first task
        task_id = uuid.uuid4().hex[:8]
        task_file = os.path.join(project.task_dir, f"{task_id}.pending")
        with open(task_file, "w", encoding="utf-8") as f:
            f.write(prompt)
        project.tasks.append(
            {
                "task_id": task_id,
                "prompt": prompt,
                "status": "queued",
                "started_at": time.time(),
            }
        )

        # Write prompt to file — avoids cmd.exe 8K command line length limit
        prompt_file = os.path.join(project.task_dir, f"{task_id}.prompt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        # Launch Claude Code in a new visible console window
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        process = self._launch_claude(
            prompt_file, working_dir, project_name, env,
            continue_session=False,
        )
        project.process = process
        self.projects[project_name] = project

        # Mark the task as running immediately
        running_file = os.path.join(project.task_dir, f"{task_id}.running")
        if os.path.exists(task_file):
            os.rename(task_file, running_file)

        print(f"[claude] New project '{project_name}': {prompt[:80]}...")

        # Monitor in background
        asyncio.create_task(self._monitor_project(project))

        return f"New project '{project_name}' started"

    async def _monitor_project(self, project: ClaudeProject):
        """Monitor a project session for task completions and log output."""
        while self._is_project_alive(project):
            await asyncio.sleep(3)
            self._refresh_project_status(project)
        # Final refresh
        self._refresh_project_status(project)
        print(f"[claude] Project '{project.name}' session ended")

    def _refresh_project_status(self, project: ClaudeProject):
        """Check task files for status updates and print new log output."""
        for task in project.tasks:
            tid = task["task_id"]
            if task["status"] in ("completed", "failed", "error"):
                continue

            done_file = os.path.join(project.task_dir, f"{tid}.done")
            running_file = os.path.join(project.task_dir, f"{tid}.running")
            error_file = os.path.join(project.task_dir, f"{tid}.error")
            log_file = os.path.join(project.task_dir, f"{tid}.log")

            if os.path.exists(done_file):
                with open(done_file, "r") as f:
                    exit_code = f.read().strip()
                task["status"] = "completed" if exit_code == "0" else "failed"
                task["finished_at"] = time.time()
                if os.path.exists(log_file):
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        task["output"] = f.read()
                    # Print summary
                    lines = task["output"].strip().split("\n")
                    tail = lines[-3:] if len(lines) > 3 else lines
                    print(f"[claude:{project.name}] Task {task['status']}:")
                    for line in tail:
                        print(f"  {line[:200]}")
                    # Notify Gemini so it can relay output to user
                    if self.on_task_complete and task.get("output"):
                        self.on_task_complete(project.name, task["output"])
            elif os.path.exists(error_file):
                task["status"] = "error"
                task["finished_at"] = time.time()
            elif os.path.exists(running_file):
                task["status"] = "running"
                # Read latest log output
                if os.path.exists(log_file):
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        task["output"] = f.read()

    def get_tasks(self) -> list[dict]:
        results = []
        for name, project in self.projects.items():
            self._refresh_project_status(project)
            alive = self._is_project_alive(project)
            for task in project.tasks:
                elapsed = (task.get("finished_at") or time.time()) - task["started_at"]
                info = {
                    "project": name,
                    "project_alive": alive,
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "prompt": task["prompt"][:100],
                    "elapsed_seconds": round(elapsed, 1),
                }
                if task.get("output"):
                    info["output_preview"] = task["output"][-500:]
                results.append(info)
        return results

    def get_active_projects(self) -> list[str]:
        """Return names of projects with live sessions."""
        return [
            name
            for name, p in self.projects.items()
            if self._is_project_alive(p)
        ]

    async def stop_all(self):
        for project in self.projects.values():
            if project.process and project.process.poll() is None:
                try:
                    project.process.terminate()
                except (ProcessLookupError, OSError):
                    pass
        print("[claude] All project sessions terminated")
