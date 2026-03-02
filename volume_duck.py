"""Audio ducking for Fosi Audio ZD3 using Windows Core Audio (pycaw).

Dims the Fosi Audio volume when the assistant is active (wake word detected),
and restores it when the conversation ends (return to wake mode).

Uses a single persistent COM thread to avoid GC race conditions that cause
access violations when COM pointers are collected on the main thread while
another thread is mid-call.
"""

import threading
import warnings

from comtypes import CoInitialize, CoUninitialize, CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from queue import Queue

import config

# Suppress noisy COM VTable cleanup warnings from pycaw
warnings.filterwarnings("ignore", message="COM method call without VTable")


_DEVICE_NAME = config.DUCK_DEVICE_NAME
DUCK_LEVEL = config.DUCK_LEVEL


class VolumeDuck:
    def __init__(self):
        self._saved_volume: float | None = None
        self._lock = threading.Lock()
        # Persistent COM thread - all COM calls happen here, never on main thread
        self._queue: Queue = Queue()
        self._thread = threading.Thread(target=self._com_worker, daemon=True)
        self._thread.start()
        # Test device lookup on the COM thread
        ready = threading.Event()
        self._queue.put(("init", ready))
        ready.wait(timeout=5)

    def _com_worker(self):
        """Single long-lived thread that owns all COM objects. Prevents GC races."""
        CoInitialize()
        try:
            # Cache the volume interface so we don't re-enumerate devices every call
            self._vol = None
            self._device_name = None
            self._find_device()

            while True:
                item = self._queue.get()
                if item is None:
                    break
                action, *args = item
                try:
                    if action == "init":
                        if self._vol:
                            current = self._vol.GetMasterVolumeLevelScalar()
                            print(f"[volume] Found {self._device_name} (current: {current:.0%}, duck to: {DUCK_LEVEL:.0%})")
                        else:
                            print("[volume] WARNING: Could not find Fosi Audio device")
                        args[0].set()  # signal ready event

                    elif action == "duck":
                        if not self._vol:
                            self._find_device()
                        if not self._vol:
                            continue
                        with self._lock:
                            try:
                                current = self._vol.GetMasterVolumeLevelScalar()
                            except Exception:
                                self._find_device()
                                if not self._vol:
                                    continue
                                current = self._vol.GetMasterVolumeLevelScalar()
                            if self._saved_volume is None:
                                self._saved_volume = current
                                print(f"[volume] Ducking Fosi: {current:.0%} -> {DUCK_LEVEL:.0%}")
                            self._vol.SetMasterVolumeLevelScalar(DUCK_LEVEL, None)

                    elif action == "unduck":
                        if not self._vol:
                            self._find_device()
                        with self._lock:
                            if self._saved_volume is None:
                                continue
                            if not self._vol:
                                self._saved_volume = None
                                continue
                            restore_to = self._saved_volume
                            self._saved_volume = None
                            try:
                                print(f"[volume] Restoring Fosi: {DUCK_LEVEL:.0%} -> {restore_to:.0%}")
                                self._vol.SetMasterVolumeLevelScalar(restore_to, None)
                            except Exception:
                                self._find_device()
                                if self._vol:
                                    self._vol.SetMasterVolumeLevelScalar(restore_to, None)

                except Exception as e:
                    print(f"[volume] COM action error: {e}")
        finally:
            # Release COM references explicitly before uninitializing
            self._vol = None
            CoUninitialize()

    def _find_device(self):
        """Find the Fosi Audio endpoint. Must be called from COM thread only."""
        self._vol = None
        self._device_name = None
        try:
            devices = AudioUtilities.GetAllDevices()
            for d in devices:
                if _DEVICE_NAME.lower() in d.FriendlyName.lower() and d.state.name == "Active":
                    interface = d._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    self._vol = cast(interface, POINTER(IAudioEndpointVolume))
                    self._device_name = d.FriendlyName
                    return
        except Exception as e:
            print(f"[volume] Error finding device: {e}")

    def duck(self):
        """Dim the Fosi Audio volume. Call when assistant activates."""
        self._queue.put(("duck",))

    def unduck(self):
        """Restore the Fosi Audio volume. Call when returning to wake mode."""
        self._queue.put(("unduck",))
