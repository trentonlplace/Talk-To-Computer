import os
from dotenv import load_dotenv

load_dotenv()

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_VOICE = "Kore"

# Audio device IDs - WASAPI (run `python -m sounddevice` to list devices if IDs shift)
AUDIO_INPUT_DEVICE = 28  # Yeti Stereo Microphone, Windows WASAPI
AUDIO_OUTPUT_DEVICE = 24  # Speakers (4- Fosi Audio ZD3), Windows WASAPI

# Audio format - devices run at 48kHz (WASAPI requirement), we resample for Gemini
DEVICE_SAMPLE_RATE = 48000   # What the hardware actually runs at
GEMINI_INPUT_RATE = 16000    # What Gemini expects from mic
GEMINI_OUTPUT_RATE = 24000   # What Gemini sends back
CAPTURE_CHANNELS = 1
PLAYBACK_CHANNELS = 2
CAPTURE_BLOCKSIZE = 4800     # 100ms @ 48kHz
PLAYBACK_BLOCKSIZE = 4800    # 100ms @ 48kHz

# Claude Code
CLAUDE_CLI = "claude"
DEFAULT_WORKING_DIR = os.path.expanduser("~\\Desktop")

# Security: directories Claude is allowed to work in
ALLOWED_DIRECTORIES = [
    os.path.expanduser("~\\Desktop"),
    os.path.expanduser("~\\Documents"),
    os.path.expanduser("~\\Projects"),
]

# Security: max concurrent Claude tasks
MAX_CLAUDE_TASKS = 5

# Inactivity timeout - seconds of silence before dropping back to wake mode
INACTIVITY_TIMEOUT = 5

# Volume ducking
DUCK_LEVEL = 0.15
DUCK_DEVICE_NAME = "Fosi"

# Chime file paths
CHIME_ACTIVATE_PATH = os.path.join(DEFAULT_WORKING_DIR, "computerbeepup.wav")
CHIME_STANDBY_PATH = os.path.join(DEFAULT_WORKING_DIR, "computerbeepdown.wav")

# Wake word detection
WAKE_BUFFER_DURATION = 1.5   # seconds of audio before running transcription
WAKE_OVERLAP_DURATION = 0.3  # seconds of overlap when sliding buffer

# Claude logs directory
CLAUDE_LOGS_DIR = os.path.join(_PROJECT_DIR, "claude_logs")

# Browser
BROWSER_NAV_TIMEOUT = 15000  # milliseconds
SCREENSHOT_DIR = os.path.join(_PROJECT_DIR, "screenshots")

# Monitor positions: monitor_number -> (x, y, width, height)
MONITOR_POSITIONS = {
    1: (-1920, 0, 1920, 1080),
    2: (0, 0, 2560, 1440),
    3: (3840, 0, 1920, 1080),
}

# Security: blocked URL patterns for browser (never navigate here)
BLOCKED_URL_PATTERNS = [
    "192.168.",         # local network devices
    "10.0.",            # local network
    "127.0.0.1",        # localhost
    "localhost",
    "file://",          # local filesystem
    "chrome://",
    "about:",
]

# Twilio SMS (fallback when email gateway unavailable)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")

# Email-to-SMS gateway (primary SMS method - bypasses carrier A2P registration)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMS_DEFAULT_GATEWAY = os.getenv("SMS_DEFAULT_GATEWAY", "vtext.com")

# Carrier SMS gateways
SMS_GATEWAYS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "uscellular": "email.uscc.net",
    "sprint": "messaging.sprintpcs.com",
}

# Voice Activity Detection - only send audio when you're actually talking
VAD_ENERGY_THRESHOLD = 500    # RMS energy threshold (int16 scale, 0-32768)
VAD_HANGOVER_BLOCKS = 8       # Keep sending for 800ms after speech stops (8 * 100ms blocks)
VAD_PREFIX_BLOCKS = 3         # Include 300ms before speech detected (3 * 100ms blocks)
# Interruption: must be much louder than speaker bleed to count as user talking
INTERRUPT_ENERGY_THRESHOLD = 3000  # High threshold to distinguish user voice from speaker bleed
INTERRUPT_CONSECUTIVE = 3          # Need 3 consecutive loud chunks (~300ms) to trigger interrupt
