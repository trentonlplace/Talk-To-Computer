import numpy as np
from faster_whisper import WhisperModel

import config

_BUFFER_DURATION = config.WAKE_BUFFER_DURATION
_BUFFER_SAMPLES = int(config.GEMINI_INPUT_RATE * _BUFFER_DURATION)
_OVERLAP_SAMPLES = int(config.GEMINI_INPUT_RATE * config.WAKE_OVERLAP_DURATION)


class WakeWordDetector:
    """Wake word detector using faster-whisper (medium model, CUDA float16)."""

    def __init__(self):
        import time
        # Try CUDA first, fall back to CPU if all attempts fail
        for attempt in range(3):
            try:
                print(f"[wake] Loading faster-whisper medium model on CUDA fp16 (attempt {attempt + 1})...")
                self.model = WhisperModel(
                    "medium", device="cuda", compute_type="float16"
                )
                self._buffer = np.array([], dtype=np.float32)
                print("[wake] Faster-whisper ready (medium, CUDA fp16)")
                return
            except Exception as e:
                print(f"[wake] CUDA load failed: {e}")
                if attempt < 2:
                    print("[wake] Retrying in 3 seconds...")
                    time.sleep(3)

        # CUDA failed 3 times - fall back to CPU (slower but functional)
        print("[wake] CUDA unavailable, falling back to CPU (int8)...")
        try:
            self.model = WhisperModel(
                "medium", device="cpu", compute_type="int8"
            )
            self._buffer = np.array([], dtype=np.float32)
            print("[wake] Faster-whisper ready (medium, CPU int8) - slower but working")
        except Exception as e:
            raise RuntimeError(f"Failed to load whisper model on both CUDA and CPU: {e}") from e

    def process_chunk(self, audio_bytes: bytes) -> bool:
        """Process a single audio chunk (~100ms of int16 PCM @ 16kHz).
        Accumulates into a buffer and runs transcription when enough audio.
        Returns True if 'computer' detected."""
        # Convert int16 bytes to float32 (whisper expects float32 in [-1, 1])
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._buffer = np.concatenate([self._buffer, samples])

        if len(self._buffer) < _BUFFER_SAMPLES:
            return False

        # Transcribe the buffer
        segments, _ = self.model.transcribe(
            self._buffer,
            language="en",
            beam_size=1,
            vad_filter=False,
            without_timestamps=True,
        )
        text = " ".join(seg.text for seg in segments).lower()

        if "computer" in text:
            self.reset()
            return True

        # Slide buffer: keep overlap for next round
        self._buffer = self._buffer[-_OVERLAP_SAMPLES:]
        return False

    def reset(self):
        """Clear the audio buffer after activation."""
        self._buffer = np.array([], dtype=np.float32)
