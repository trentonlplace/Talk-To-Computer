import asyncio
import atexit
import faulthandler
import os
import signal
import subprocess
import sys

# Dump C-level stack trace on segfault so we can see what actually crashed
faulthandler.enable()

import config
from audio_engine import AudioEngine
from browser_controller import BrowserController
from claude_manager import ClaudeManager
from gemini_client import GeminiClient
from tool_executor import ToolExecutor
from volume_duck import VolumeDuck
from wake_word import WakeWordDetector

_PID_FILE = os.path.join(os.path.dirname(__file__), ".ttc.pid")


def _kill_prior_instances():
    """Kill any previous Talk To Computer python process using the PID lockfile.
    Only kills the python.exe process itself, NOT the tree (which would nuke our own console)."""
    if not os.path.exists(_PID_FILE):
        return
    try:
        with open(_PID_FILE, "r") as f:
            old_pid = int(f.read().strip())
        if old_pid == os.getpid():
            return
        # Check if the old PID is actually a python process before killing
        result = subprocess.run(
            ["tasklist", "/fi", f"PID eq {old_pid}", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=5,
        )
        if "python" in result.stdout.lower():
            subprocess.run(
                ["taskkill", "/f", "/pid", str(old_pid)],
                capture_output=True, timeout=5,
            )
            print(f"[startup] Killed prior instance (PID {old_pid})")
        else:
            print(f"[startup] Prior PID {old_pid} already dead, cleaning up")
    except (ValueError, FileNotFoundError):
        pass
    except Exception as e:
        print(f"[startup] Could not kill prior instance: {e}")
    finally:
        try:
            os.remove(_PID_FILE)
        except OSError:
            pass


def _write_pid():
    """Write current PID to lockfile."""
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    """Remove PID lockfile on exit."""
    try:
        os.remove(_PID_FILE)
    except OSError:
        pass


def print_banner():
    print("=" * 50)
    print("  Talk To Computer - Voice Desktop Assistant")
    print("=" * 50)
    print(f"  Model:  {config.GEMINI_MODEL}")
    print(f"  Voice:  {config.GEMINI_VOICE}")
    print(f"  Input:  device {config.AUDIO_INPUT_DEVICE} @ {config.DEVICE_SAMPLE_RATE}Hz -> {config.GEMINI_INPUT_RATE}Hz")
    print(f"  Output: device {config.AUDIO_OUTPUT_DEVICE} @ {config.DEVICE_SAMPLE_RATE}Hz <- {config.GEMINI_OUTPUT_RATE}Hz")
    print(f"  Wake word: \"Computer\" (faster-whisper medium, CUDA fp16)")
    print("=" * 50)


async def wake_word_loop(audio: AudioEngine, gemini: GeminiClient, detector: WakeWordDetector):
    """Process individual audio chunks through Vosk for real-time wake word detection.
    Each chunk is ~100ms, giving near-instant detection latency."""
    loop = asyncio.get_running_loop()
    while True:
        chunk = await audio.wake_check_queue.get()

        # Run Vosk on this single chunk (fast, ~1-5ms)
        detected = await loop.run_in_executor(None, detector.process_chunk, chunk)

        if detected:
            print("[wake] Activated!")
            audio.activate_from_wake()
            # No timer here - wait for Gemini to respond first,
            # then the 5s timer starts after turn_complete


async def main():
    # Kill any prior instance before doing anything
    _kill_prior_instances()
    _write_pid()
    atexit.register(_remove_pid)

    print_banner()

    if not config.GEMINI_API_KEY:
        print("[error] GEMINI_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    loop = asyncio.get_running_loop()

    # Init components
    browser = BrowserController()
    claude = ClaudeManager()
    audio = AudioEngine(loop)
    ducker = VolumeDuck()
    executor = ToolExecutor(browser, claude)
    gemini = GeminiClient(audio, executor, ducker)
    detector = WakeWordDetector()

    # Wire volume ducking into audio engine
    audio.on_activate = ducker.duck
    audio.on_standby = ducker.unduck

    # Wire Claude -> Gemini feedback loop: when Claude finishes a task,
    # inject its output into Gemini so it can relay questions/results to the user
    def on_claude_done(project_name: str, output: str):
        asyncio.run_coroutine_threadsafe(
            gemini.notify_claude_output(project_name, output),
            loop,
        )
    claude.on_task_complete = on_claude_done

    # Shutdown handler
    shutdown_event = asyncio.Event()

    def on_shutdown():
        print("\n[shutdown] Stopping...")
        shutdown_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda *_: on_shutdown())
    else:
        loop.add_signal_handler(signal.SIGINT, on_shutdown)

    # Startup sequence (browser launches lazily on first use)
    print("\n[startup] Starting audio streams...")
    audio.start()

    print("[startup] Connecting to Gemini...\n")
    print('>>> Say "Computer" to activate (Ctrl+C to quit)\n')

    # Start wake word processor
    wake_task = asyncio.create_task(wake_word_loop(audio, gemini, detector))

    try:
        await gemini.run(shutdown_event)
    except Exception as e:
        print(f"[error] {e}")
    finally:
        wake_task.cancel()
        audio.stop()
        await claude.stop_all()
        await browser.stop()
        print("[shutdown] Done.")


if __name__ == "__main__":
    asyncio.run(main())
