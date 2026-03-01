import asyncio
import json
import os
import sys
import traceback

import numpy as np
from google import genai
from google.genai import types

import config
from audio_engine import AudioEngine
from tool_executor import ToolExecutor

# Load system prompt from external file (editable without touching Python code)
_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.txt")
with open(_PROMPT_PATH, "r", encoding="utf-8") as _f:
    SYSTEM_PROMPT = _f.read()

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="browser_navigate",
        description="Navigate the browser to a URL or search query. If the input isn't a URL, it will be searched on Google.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "url": types.Schema(type="STRING", description="URL or search query"),
            },
            required=["url"],
        ),
    ),
    types.FunctionDeclaration(
        name="browser_click",
        description="Click an element on the current page by CSS selector or visible text.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "selector": types.Schema(type="STRING", description="CSS selector or visible text of the element to click"),
            },
            required=["selector"],
        ),
    ),
    types.FunctionDeclaration(
        name="browser_type",
        description="Type text into a form field identified by CSS selector or placeholder text.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "selector": types.Schema(type="STRING", description="CSS selector or placeholder text of the input field"),
                "text": types.Schema(type="STRING", description="Text to type into the field"),
            },
            required=["selector", "text"],
        ),
    ),
    types.FunctionDeclaration(
        name="browser_read_page",
        description="Read the text content of the current page (truncated to 2000 chars).",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="browser_screenshot",
        description="Take a screenshot of the current browser page.",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="run_claude_task",
        description="Send a task to a Claude Code agent. Uses project-based sessions: tasks for the SAME project go to the SAME terminal window. For follow-up requests about an existing project, reuse its exact project_name to route to the same session.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "prompt": types.Schema(type="STRING", description="Detailed prompt describing the task for Claude Code"),
                "project_name": types.Schema(type="STRING", description="Short descriptive name for the project (e.g. 'Todo App', 'Snake Game', 'Portfolio Site'). REUSE the same name for follow-up tasks on the same project."),
                "working_directory": types.Schema(type="STRING", description="Optional working directory path. Defaults to Desktop."),
            },
            required=["prompt", "project_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="check_claude_tasks",
        description="Check the status of all spawned Claude Code tasks.",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
    # File management tools
    types.FunctionDeclaration(
        name="file_list",
        description="List files and folders in a directory. Defaults to Desktop if no path given.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Directory path to list. Defaults to Desktop."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="file_info",
        description="Get info about a file or folder (size, dates, type).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Path to the file or folder"),
            },
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_read",
        description="Read the text contents of a file (first 4000 chars).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Path to the file to read"),
            },
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_mkdir",
        description="Create a new directory (folder).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Path of the directory to create"),
            },
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_move",
        description="Move or rename a file or folder.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "source": types.Schema(type="STRING", description="Current path"),
                "destination": types.Schema(type="STRING", description="New path"),
            },
            required=["source", "destination"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_copy",
        description="Copy a file or folder.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "source": types.Schema(type="STRING", description="Path to copy from"),
                "destination": types.Schema(type="STRING", description="Path to copy to"),
            },
            required=["source", "destination"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_delete",
        description="Delete a file or folder. Use with caution.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Path to delete"),
            },
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_open_explorer",
        description="Open Windows File Explorer at a specific folder. Defaults to Desktop.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Folder path to open in Explorer. Defaults to Desktop."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="file_open",
        description="Open a file with its default application (like double-clicking it).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "path": types.Schema(type="STRING", description="Path to the file to open"),
            },
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="file_close_explorer",
        description="Close all open File Explorer windows.",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="file_search",
        description="Search for files by name in a directory.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "directory": types.Schema(type="STRING", description="Directory to search in"),
                "pattern": types.Schema(type="STRING", description="Filename pattern to search for (partial match)"),
            },
            required=["directory", "pattern"],
        ),
    ),
    # App management tools
    types.FunctionDeclaration(
        name="app_open",
        description="Open a desktop application by name (e.g. Spotify, Discord, Chrome, Notepad, VS Code, Word, Excel, Steam, OBS, VLC, Terminal, Calculator, Settings).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Application name"),
            },
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="app_close",
        description="Close/kill a running application by name.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Application name to close"),
            },
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="app_list",
        description="List all currently running applications with visible windows.",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
    types.FunctionDeclaration(
        name="window_manage",
        description="Manage a window: maximize, minimize, restore, or bring to front/focus. Matches by partial window title.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Application or window name to match (partial match on window title)"),
                "action": types.Schema(type="STRING", description="Action: maximize, minimize, restore, or focus"),
            },
            required=["name", "action"],
        ),
    ),
    types.FunctionDeclaration(
        name="window_move_to_monitor",
        description="Move a window to a specific monitor and optionally maximize it. Monitor 1 = left (1920x1080), Monitor 2 = center/primary (2560x1440), Monitor 3 = right (1920x1080).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Application or window name to match (partial match on window title)"),
                "monitor": types.Schema(type="INTEGER", description="Monitor number: 1 (left), 2 (center/primary), 3 (right)"),
                "maximize": types.Schema(type="BOOLEAN", description="Whether to maximize the window on that monitor. Defaults to true."),
            },
            required=["name", "monitor"],
        ),
    ),
    types.FunctionDeclaration(
        name="open_chrome_url",
        description="Open a URL in the real Chrome browser (not the Playwright browser). Use this for things like Chrome Remote Desktop that need the user's Chrome profile and login.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "url": types.Schema(type="STRING", description="URL to open in Chrome"),
            },
            required=["url"],
        ),
    ),
    types.FunctionDeclaration(
        name="open_rdp",
        description="Open Microsoft Remote Desktop connection to a host.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "host": types.Schema(type="STRING", description="IP address or hostname to connect to"),
            },
            required=["host"],
        ),
    ),
    # Twilio SMS tools
    types.FunctionDeclaration(
        name="send_sms",
        description="Send a text message (SMS). Can send to a contact by name (e.g. 'Avi') or to Master by default if no recipient given.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "message": types.Schema(type="STRING", description="The text message body to send"),
                "to": types.Schema(type="STRING", description="Contact name (e.g. 'Avi') or phone number. Defaults to Captain if not specified."),
            },
            required=["message"],
        ),
    ),
    types.FunctionDeclaration(
        name="add_contact",
        description="Add or update a contact in the phone book.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Contact name"),
                "phone": types.Schema(type="STRING", description="Phone number"),
            },
            required=["name", "phone"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_contacts",
        description="List all saved contacts in the phone book.",
        parameters=types.Schema(
            type="OBJECT",
            properties={},
        ),
    ),
]


INACTIVITY_TIMEOUT = config.INACTIVITY_TIMEOUT


class GeminiClient:
    def __init__(self, audio: AudioEngine, executor: ToolExecutor, ducker=None):
        self.audio = audio
        self.executor = executor
        self.ducker = ducker
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.session = None
        self._inactivity_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=config.GEMINI_VOICE,
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(text=SYSTEM_PROMPT)]
            ),
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        )

    async def notify_claude_output(self, project_name: str, output: str):
        """Inject Claude's output into the Gemini session so it can react."""
        if not self.session:
            return
        # Truncate very long output to avoid overwhelming Gemini
        if len(output) > 3000:
            output = output[:1500] + "\n...[truncated]...\n" + output[-1500:]
        text = (
            f"CLAUDE CODE UPDATE for project '{project_name}':\n"
            f"---\n{output}\n---\n"
            f"Read this output. If Claude asked questions or needs clarification, "
            f"ask Captain each question now so you can send the answers back. "
            f"If Claude completed the task successfully, let Captain know it's done."
        )
        # Show Claude's output in a visible popup window
        self._show_output_window(project_name, output)

        try:
            # Activate from wake mode so Gemini can speak
            if self.audio.wake_mode:
                self.audio.play_activate_chime()
                self.audio.wake_mode = False
                if self.ducker:
                    self.ducker.duck()
            await self.session.send_client_content(
                turns=[types.Content(
                    role="user",
                    parts=[types.Part(text=text)],
                )],
                turn_complete=True,
            )
            print(f"[gemini] Injected Claude output for '{project_name}'")
        except Exception as e:
            print(f"[gemini] Failed to inject Claude output: {e}")

    def _show_output_window(self, project_name: str, output: str):
        """Open a visible notepad window with Claude's output so the user can read it."""
        import os
        import subprocess
        out_dir = config.CLAUDE_LOGS_DIR
        out_file = os.path.join(out_dir, f"_latest_{project_name.replace(' ', '_')}.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"CLAUDE - {project_name}\n")
            f.write(f"{'='*60}\n\n")
            f.write(output)
        # Use 'start' to open notepad in foreground, detached from our process
        subprocess.Popen(
            ["cmd", "/c", "start", "Claude Output", "notepad.exe", out_file],
            shell=True,
        )
        print(f"[gemini] Opened Claude output for '{project_name}' in Notepad")

    async def run(self, shutdown_event: asyncio.Event):
        """Connect to Gemini and run send/receive loops until shutdown.
        Auto-reconnects on transient errors with exponential backoff."""
        import time as _time
        self._loop = asyncio.get_running_loop()
        backoff = 1  # seconds
        max_backoff = 60

        while not shutdown_event.is_set():
            try:
                async with self.client.aio.live.connect(
                    model=config.GEMINI_MODEL,
                    config=self._live_config,
                ) as session:
                    self.session = session
                    connect_time = _time.monotonic()
                    print("[gemini] Connected to Live API")

                    # Reset to wake mode on reconnect
                    self.audio.wake_mode = True
                    if self.ducker:
                        self.ducker.unduck()

                    send_task = asyncio.create_task(self._send_audio_loop())
                    recv_task = asyncio.create_task(self._receive_loop())
                    wait_task = asyncio.create_task(shutdown_event.wait())

                    done, pending = await asyncio.wait(
                        [send_task, recv_task, wait_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for t in pending:
                        t.cancel()

                    self.session = None

                    # If shutdown was requested, exit the loop
                    if shutdown_event.is_set():
                        print("[gemini] Disconnected (shutdown)")
                        return

                    # Only reset backoff if connection lasted >10s (not an immediate failure)
                    if _time.monotonic() - connect_time > 10:
                        backoff = 1

                    print("[gemini] Disconnected, will reconnect...")

            except Exception as e:
                self.session = None
                if shutdown_event.is_set():
                    return
                print(f"[gemini] Connection error: {e}")

            # Exponential backoff before reconnect
            print(f"[gemini] Reconnecting in {backoff}s...")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=backoff)
                return  # Shutdown requested during wait
            except asyncio.TimeoutError:
                pass  # Timeout expired, try reconnecting
            backoff = min(backoff * 2, max_backoff)

    def _cancel_inactivity_timer(self):
        """Cancel any pending inactivity timeout."""
        if self._inactivity_task and not self._inactivity_task.done():
            self._inactivity_task.cancel()
            self._inactivity_task = None

    def _start_inactivity_timer(self):
        """Start a timer that drops back to wake mode after INACTIVITY_TIMEOUT seconds."""
        self._cancel_inactivity_timer()
        self._inactivity_task = asyncio.create_task(self._inactivity_countdown())

    async def _inactivity_countdown(self):
        """Wait for timeout, but keep extending if user is still speaking."""
        import time
        try:
            while True:
                await asyncio.sleep(1)  # Check every second
                elapsed = time.monotonic() - self.audio.last_speech_time
                if elapsed < INACTIVITY_TIMEOUT:
                    continue  # User spoke recently, keep waiting
                # Truly inactive for the full timeout
                self.audio.wake_mode = True
                self.audio.play_standby_chime()
                if self.ducker:
                    self.ducker.unduck()
                print(f"[gemini] No activity for {INACTIVITY_TIMEOUT}s, listening for 'Computer'...")
                break
        except asyncio.CancelledError:
            pass  # Timer was cancelled because Gemini is responding

    async def _send_audio_loop(self):
        """Continuously send mic audio to Gemini."""
        while True:
            data = await self.audio.capture_queue.get()
            if self.session:
                try:
                    await self.session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )
                except Exception as e:
                    print(f"[gemini] Send error: {e}")
                    break

    async def _receive_loop(self):
        """Receive responses from Gemini: audio, tool calls, turn completions."""
        while True:
            if not self.session:
                await asyncio.sleep(0.1)
                continue
            try:
                async for message in self.session.receive():
                    server_content = message.server_content
                    if server_content:
                        if server_content.model_turn:
                            # Gemini is responding - cancel any inactivity timer
                            self._cancel_inactivity_timer()
                            for part in server_content.model_turn.parts:
                                if part.inline_data:
                                    if not self.audio.is_speaking:
                                        print("[gemini] Speaking...")
                                    self.audio.set_speaking(True)
                                    self.audio.feed_playback(part.inline_data.data)
                                if part.text:
                                    print(f"[gemini] Text: {part.text[:100]}")

                        if getattr(server_content, "interrupted", False):
                            # User interrupted Gemini - stop playback immediately
                            self.audio.playback_buffer.clear()
                            self.audio._playback_leftover = np.array([], dtype=np.float32)
                            self.audio.set_speaking(False)
                            self._cancel_inactivity_timer()
                            print("[gemini] Interrupted by user")

                        if server_content.turn_complete:
                            await asyncio.sleep(0.3)
                            self.audio.set_speaking(False)
                            # Start inactivity timer - wait for follow-up before dropping to wake mode
                            self._start_inactivity_timer()
                            print(f"[gemini] Turn complete, listening for {INACTIVITY_TIMEOUT}s...")

                    tool_call = message.tool_call
                    if tool_call:
                        await self._handle_tool_call(tool_call)

            except Exception as e:
                print(f"[gemini] Receive error: {e}")
                traceback.print_exc()
                break

    async def _handle_tool_call(self, tool_call):
        """Execute tool calls and send responses back to Gemini."""
        responses = []
        for fc in tool_call.function_calls:
            print(f"[tools] {fc.name}({json.dumps(fc.args, default=str)[:100]})")
            result = await self.executor.execute(fc.name, fc.args or {})
            responses.append(
                types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response=result,
                )
            )

        if self.session and responses:
            await self.session.send_tool_response(function_responses=responses)
