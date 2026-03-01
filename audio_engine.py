import asyncio
import collections
import os
import threading
import time
import wave

import numpy as np
import sounddevice as sd

import config

# Resample ratio constants
_CAPTURE_RATIO = config.GEMINI_INPUT_RATE / config.DEVICE_SAMPLE_RATE   # 16000/48000 = 1/3
_PLAYBACK_RATIO = config.DEVICE_SAMPLE_RATE / config.GEMINI_OUTPUT_RATE  # 48000/24000 = 2


def _resample_linear(data: np.ndarray, ratio: float) -> np.ndarray:
    """Fast linear interpolation resampling."""
    n_out = int(len(data) * ratio)
    indices = np.linspace(0, len(data) - 1, n_out, dtype=np.float32)
    idx_floor = indices.astype(np.intp)
    frac = indices - idx_floor
    idx_ceil = np.minimum(idx_floor + 1, len(data) - 1)
    return data[idx_floor] * (1 - frac) + data[idx_ceil] * frac


def _load_wav_as_float32(path: str) -> np.ndarray:
    """Load a WAV file and return mono float32 samples at device sample rate (48kHz)."""
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        wav_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    # Convert to float32
    if sampwidth == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    # Mix to mono if stereo
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    # Resample to device rate if needed
    if wav_rate != config.DEVICE_SAMPLE_RATE:
        ratio = config.DEVICE_SAMPLE_RATE / wav_rate
        samples = _resample_linear(samples, ratio)

    return samples.astype(np.float32)


# Load chime WAV files
_BEEP_UP_PATH = config.CHIME_ACTIVATE_PATH
_BEEP_DOWN_PATH = config.CHIME_STANDBY_PATH

CHIME_ACTIVATE = _load_wav_as_float32(_BEEP_UP_PATH)
CHIME_STANDBY = _load_wav_as_float32(_BEEP_DOWN_PATH)
print(f"[audio] Loaded chimes: beepup ({len(CHIME_ACTIVATE)} samples), beepdown ({len(CHIME_STANDBY)} samples)")


class AudioEngine:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.capture_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.playback_buffer: collections.deque[np.ndarray] = collections.deque()
        self.is_speaking = False
        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None
        # Thread safety: protects shared state accessed from both audio callback and async main thread
        self._state_lock = threading.Lock()
        # Leftover playback samples between callbacks
        self._playback_leftover = np.array([], dtype=np.float32)

        # Wake word mode: True = waiting for "Computer", False = active (streaming to Gemini)
        self.wake_mode = True
        # Queue for individual audio chunks to be checked for wake word in real-time
        self.wake_check_queue: asyncio.Queue[bytes] = asyncio.Queue()
        # Small prefix buffer: forwarded to Gemini on activation so it hears
        # what comes right after "computer" even if detection takes a chunk or two
        self._wake_prefix: collections.deque[bytes] = collections.deque(maxlen=5)
        # Track last time user voice was detected (for inactivity timer)
        self.last_speech_time: float = 0.0
        # Interruption detection: count consecutive loud chunks while Gemini speaks
        self._interrupt_count: int = 0
        # Callbacks for volume ducking (set by main.py)
        self.on_activate = None   # Called when switching to active mode
        self.on_standby = None    # Called when returning to wake mode

    def _play_chime(self, chime: np.ndarray):
        """Push a pre-generated chime (float32 @ 48kHz) into the playback buffer."""
        self.playback_buffer.append(chime)

    def play_activate_chime(self):
        self._play_chime(CHIME_ACTIVATE)

    def play_standby_chime(self):
        self._play_chime(CHIME_STANDBY)

    def activate_from_wake(self):
        """Switch from wake mode to active mode. Plays chime, ducks music volume,
        and forwards recent audio prefix to Gemini so it hears what comes right after 'computer'."""
        self.play_activate_chime()
        with self._state_lock:
            self.wake_mode = False
        if self.on_activate:
            self.on_activate()
        # Forward recent prefix chunks so Gemini gets the start of the sentence
        for chunk in self._wake_prefix:
            self.capture_queue.put_nowait(chunk)
        self._wake_prefix.clear()
        # Drain any remaining wake chunks from the queue (they'll now go to Gemini via active mode)
        while not self.wake_check_queue.empty():
            try:
                leftover = self.wake_check_queue.get_nowait()
                self.capture_queue.put_nowait(leftover)
            except asyncio.QueueEmpty:
                break

    def _capture_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] capture status: {status}")

        # Downsample 48kHz -> 16kHz for Gemini
        samples_48k = indata[:, 0].astype(np.float32)
        rms = np.sqrt(np.mean(samples_48k ** 2))
        samples_16k = _resample_linear(samples_48k, _CAPTURE_RATIO)
        audio_bytes = samples_16k.astype(np.int16).tobytes()

        if self.wake_mode:
            # Wake word mode: send EVERY chunk for real-time detection (no batching)
            self._wake_prefix.append(audio_bytes)
            try:
                self.loop.call_soon_threadsafe(self.wake_check_queue.put_nowait, audio_bytes)
            except Exception:
                pass  # Drop frame if event loop is shutting down
        elif self.is_speaking:
            # Gemini is talking - mic is muted to avoid feedback loop.
            # But detect intentional interruption: user voice is much louder than speaker bleed.
            if rms >= config.INTERRUPT_ENERGY_THRESHOLD:
                self._interrupt_count += 1
            else:
                self._interrupt_count = 0
            if self._interrupt_count >= config.INTERRUPT_CONSECUTIVE:
                # User is deliberately talking over Gemini - interrupt
                # Use lock for compound state mutation (non-blocking to avoid audio glitches)
                if self._state_lock.acquire(blocking=False):
                    try:
                        self._interrupt_count = 0
                        self.playback_buffer.clear()
                        self._playback_leftover = np.array([], dtype=np.float32)
                        self.is_speaking = False
                        self.last_speech_time = time.monotonic()
                    finally:
                        self._state_lock.release()
                # Send this chunk so Gemini hears the user
                try:
                    self.loop.call_soon_threadsafe(self.capture_queue.put_nowait, audio_bytes)
                except Exception:
                    pass
        else:
            # Active mode: stream audio to Gemini
            if rms >= config.VAD_ENERGY_THRESHOLD:
                self.last_speech_time = time.monotonic()
            try:
                self.loop.call_soon_threadsafe(self.capture_queue.put_nowait, audio_bytes)
            except Exception:
                pass

    def _playback_callback(self, outdata, frames, time_info, status):
        if status:
            print(f"[audio] playback status: {status}")

        needed = frames
        collected = self._playback_leftover

        while len(collected) < needed and self.playback_buffer:
            chunk = self.playback_buffer.popleft()
            if isinstance(chunk, np.ndarray):
                collected = np.concatenate([collected, chunk])
            else:
                mono_24k = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                mono_48k = _resample_linear(mono_24k, _PLAYBACK_RATIO)
                collected = np.concatenate([collected, mono_48k])

        if len(collected) >= needed:
            use = collected[:needed]
            self._playback_leftover = collected[needed:]
        else:
            use = np.concatenate([collected, np.zeros(needed - len(collected), dtype=np.float32)])
            self._playback_leftover = np.array([], dtype=np.float32)

        outdata[:, 0] = use[:frames]
        outdata[:, 1] = use[:frames]

    def feed_playback(self, audio_bytes: bytes):
        """Push Gemini audio (int16 mono 24kHz raw bytes) into the playback buffer."""
        self.playback_buffer.append(audio_bytes)

    def set_speaking(self, speaking: bool):
        with self._state_lock:
            self.is_speaking = speaking
            if not speaking:
                self._interrupt_count = 0

    def start(self):
        print(f"[audio] Input device:  {config.AUDIO_INPUT_DEVICE} @ {config.DEVICE_SAMPLE_RATE}Hz")
        print(f"[audio] Output device: {config.AUDIO_OUTPUT_DEVICE} @ {config.DEVICE_SAMPLE_RATE}Hz")
        print(f"[audio] Gemini: capture {config.GEMINI_INPUT_RATE}Hz, playback {config.GEMINI_OUTPUT_RATE}Hz")

        self._input_stream = sd.InputStream(
            samplerate=config.DEVICE_SAMPLE_RATE,
            channels=config.CAPTURE_CHANNELS,
            dtype="int16",
            blocksize=config.CAPTURE_BLOCKSIZE,
            device=config.AUDIO_INPUT_DEVICE,
            callback=self._capture_callback,
        )

        self._output_stream = sd.OutputStream(
            samplerate=config.DEVICE_SAMPLE_RATE,
            channels=config.PLAYBACK_CHANNELS,
            dtype="float32",
            blocksize=config.PLAYBACK_BLOCKSIZE,
            device=config.AUDIO_OUTPUT_DEVICE,
            callback=self._playback_callback,
        )

        self._input_stream.start()
        self._output_stream.start()
        print("[audio] Streams started")

    def stop(self):
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
        print("[audio] Streams stopped")
