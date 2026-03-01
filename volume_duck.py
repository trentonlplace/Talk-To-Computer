"""Audio ducking for Fosi Audio ZD3 using Windows Core Audio (pycaw).

Dims the Fosi Audio volume when the assistant is active (wake word detected),
and restores it when the conversation ends (return to wake mode).
"""

import threading
import warnings

from comtypes import CoInitialize, CoUninitialize, CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER

import config

# Suppress noisy COM VTable cleanup warnings from pycaw
warnings.filterwarnings("ignore", message="COM method call without VTable")


_DEVICE_NAME = config.DUCK_DEVICE_NAME
DUCK_LEVEL = config.DUCK_LEVEL


class VolumeDuck:
    def __init__(self):
        self._saved_volume: float | None = None
        self._lock = threading.Lock()
        # Test that we can find the device at startup
        vol, name = self._get_fosi_volume()
        if vol:
            current = vol.GetMasterVolumeLevelScalar()
            print(f"[volume] Found {name} (current: {current:.0%}, duck to: {DUCK_LEVEL:.0%})")
        else:
            print("[volume] WARNING: Could not find Fosi Audio device")

    def _get_fosi_volume(self):
        """Find the active Fosi Audio endpoint and return (IAudioEndpointVolume, name).
        Returns (None, None) if not found."""
        try:
            devices = AudioUtilities.GetAllDevices()
            for d in devices:
                if _DEVICE_NAME.lower() in d.FriendlyName.lower() and d.state.name == "Active":
                    interface = d._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    return volume, d.FriendlyName
            return None, None
        except Exception as e:
            print(f"[volume] Error finding device: {e}")
            return None, None

    def _run_com_action(self, action):
        """Run a COM action in a new thread with proper COM initialization."""
        CoInitialize()
        try:
            action()
        except Exception as e:
            print(f"[volume] COM action error: {e}")
        finally:
            CoUninitialize()

    def duck(self):
        """Dim the Fosi Audio volume. Call when assistant activates."""
        def _do_duck():
            with self._lock:
                vol, _ = self._get_fosi_volume()
                if not vol:
                    return
                current = vol.GetMasterVolumeLevelScalar()
                # Only save if we haven't already ducked
                if self._saved_volume is None:
                    self._saved_volume = current
                    print(f"[volume] Ducking Fosi: {current:.0%} -> {DUCK_LEVEL:.0%}")
                vol.SetMasterVolumeLevelScalar(DUCK_LEVEL, None)

        threading.Thread(target=lambda: self._run_com_action(_do_duck), daemon=True).start()

    def unduck(self):
        """Restore the Fosi Audio volume. Call when returning to wake mode."""
        def _do_unduck():
            with self._lock:
                if self._saved_volume is None:
                    return
                vol, _ = self._get_fosi_volume()
                if not vol:
                    self._saved_volume = None
                    return
                restore_to = self._saved_volume
                self._saved_volume = None
                print(f"[volume] Restoring Fosi: {DUCK_LEVEL:.0%} -> {restore_to:.0%}")
                vol.SetMasterVolumeLevelScalar(restore_to, None)

        threading.Thread(target=lambda: self._run_com_action(_do_unduck), daemon=True).start()
