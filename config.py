from typing import Tuple
import os
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# CUSTOMIZE: File settings
HISTORY_FILE = os.path.join(BASE_DIR, "conversation_history.json")
CHAT_STORAGE_DIR = os.path.join(BASE_DIR, "chat_data")
CHAT_INDEX_FILE = os.path.join(CHAT_STORAGE_DIR, "index.json")
PROVIDER_CONFIG_FILE = os.path.join(CHAT_STORAGE_DIR, "providers.json")
OPENAI_WEB_AUTH_FILE = os.path.join(CHAT_STORAGE_DIR, "openai_web_auth.json")

# CUSTOMIZE: Speech/voice settings
WHISPER_MODEL = "tiny"
DEFAULT_RESPONSE_LANGUAGE = "en"
ENGLISH_VOICE = "en-US-JennyNeural"
SPANISH_VOICE = "es-ES-ElviraNeural"
FFPLAY_PATH = os.getenv(
    "FFPLAY_PATH",
    r"C:\Users\TEL\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffplay.exe"
)

# CUSTOMIZE: LLM model settings - web coach uses this Ollama model
LLM_MODEL = "qwen2.5:1.5b"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
GEMINI_DEFAULT_MODEL = "gemini-1.5-flash"
OPENAI_WEB_DEFAULT_MODEL = "gpt-5.4"
OPENAI_WEB_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2"]
OPENAI_WEB_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_WEB_ISSUER = "https://auth.openai.com"
OPENAI_WEB_CALLBACK_PORT = 1455
OLLAMA_DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
PROVIDER_REQUEST_TIMEOUT = 45

# CUSTOMIZE: Default location if auto-detection fails
DEFAULT_CITY = "Your City"
DEFAULT_COUNTRY = "Your Country"

def detect_location() -> Tuple[str, str]:
    """Auto-detect user location from IP address with fallback to defaults."""
    try:
        response = requests.get(
            'https://ipapi.co/json/',
            timeout=3,
            headers={"User-Agent": "voice-assistant-local/1.0"}
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('city', DEFAULT_CITY), data.get('country_name', DEFAULT_COUNTRY)
        elif response.status_code not in (403, 429):
            print(f"[LOCATION] Error: HTTP {response.status_code}")
    except Exception as e:
        print(f"[LOCATION] Detection failed: {e}")
    
    return DEFAULT_CITY, DEFAULT_COUNTRY

# Get location and date information
CITY, COUNTRY = detect_location()
DATE_STR = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# CUSTOMIZE: System prompt that controls the assistant's behavior and responses
CONVERSATION_CONTEXT = (
    f"You are a friendly English speaking coach with long-term conversation memory. "
    f"The user's location is {CITY}, {COUNTRY}, and the current time is {DATE_STR}. "
    f"Your main job is to help the user practice spoken English. "
    f"Prefer answering in simple natural English unless the user asks for Spanish help. "
    f"Keep your answers concise, clear and helpful. "
    f"When the user speaks English, briefly correct grammar or word choice when useful. "
    f"If the transcription suggests a likely pronunciation issue, mention the likely target word and give a short pronunciation hint in plain text. "
    f"Encourage the user to repeat corrected phrases out loud. "
    f"Only mention location and time information when directly relevant to the user's question. "
    f"Do not make up information about current events, weather, or news unless you have access to it via internet search. "
    f"Respond directly to questions without unnecessary acknowledgments or apologies. "
    f"When unsure about something, clearly state that you don't know rather than speculating."
)

DEFAULT_CHAT_TITLE = "New chat"
