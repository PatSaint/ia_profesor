import asyncio
import base64
import os
import subprocess
import sys
import tempfile
import threading
import warnings
from pathlib import Path

import whisper
from flask import Flask, jsonify, render_template, request
from langdetect import detect

from config import DEFAULT_RESPONSE_LANGUAGE, ENGLISH_VOICE, FFPLAY_PATH, SPANISH_VOICE, WHISPER_MODEL
from conversation_manager import ConversationManager
from llm_interface import LLMInterface

warnings.filterwarnings("ignore", message="You are using `torch.load` with `weights_only=False`")
warnings.filterwarnings("ignore", message="Performing inference on CPU when CUDA is available")
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")

app = Flask(__name__)


def ensure_ffmpeg_available() -> None:
    ffmpeg_dir = FFPLAY_PATH if os.path.isdir(FFPLAY_PATH) else os.path.dirname(FFPLAY_PATH)
    if ffmpeg_dir and os.path.exists(ffmpeg_dir):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


class WebVoiceCoach:
    def __init__(self):
        print("[WEB] Loading Whisper model...")
        ensure_ffmpeg_available()
        self.whisper_model = whisper.load_model(WHISPER_MODEL, device="cpu")
        self.conversation_manager = ConversationManager()
        self.llm_interface = LLMInterface(self.conversation_manager)
        self.lock = threading.Lock()
        print("[WEB] Web voice coach ready.")

    def transcribe_audio(self, audio_file: str) -> tuple[str, str]:
        result = self.whisper_model.transcribe(audio_file)
        transcription = result.get("text", "").strip()
        detected_lang = result.get("language", DEFAULT_RESPONSE_LANGUAGE)
        print(f"[WEB][AUDIO] Transcribed text: {transcription}")
        return transcription, detected_lang

    def get_voice_for_language(self, lang: str) -> str:
        voice_map = {
            "en": ENGLISH_VOICE,
            "es": SPANISH_VOICE,
            "ar": "ar-EG-SalmaNeural",
            "fr": "fr-FR-DeniseNeural",
            "de": "de-DE-KatjaNeural",
            "zh": "zh-CN-XiaoxiaoNeural",
            "ja": "ja-JP-NanamiNeural",
            "ru": "ru-RU-SvetlanaNeural",
        }
        return voice_map.get(lang or DEFAULT_RESPONSE_LANGUAGE, ENGLISH_VOICE)

    def synthesize_speech_base64(self, text: str, lang: str) -> str:
        voice = self.get_voice_for_language(lang)
        edge_tts_exe = os.path.join(os.path.dirname(sys.executable), "edge-tts.exe")
        edge_tts_cmd = edge_tts_exe if os.path.exists(edge_tts_exe) else "edge-tts"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            temp_path = temp_file.name

        try:
            result = subprocess.run(
                [edge_tts_cmd, "--voice", voice, "--text", text, "--write-media", temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"edge-tts exited with code {result.returncode}")
            audio_bytes = Path(temp_path).read_bytes()
            if not audio_bytes:
                raise RuntimeError("edge-tts generated an empty audio file")
            return base64.b64encode(audio_bytes).decode("utf-8")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def get_bootstrap_payload(self) -> dict:
        active_chat = self.conversation_manager.export_chat_payload()
        return {
            "ok": True,
            "active_chat_id": active_chat["id"],
            "active_chat": active_chat,
            "chats": self.conversation_manager.list_chats(),
            "settings": self.conversation_manager.get_settings(),
        }

    async def process_audio(self, audio_file: str, chat_id: str) -> dict:
        with self.lock:
            transcript, _detected_lang = self.transcribe_audio(audio_file)
            self.conversation_manager.set_active_chat(chat_id)

            if not transcript.strip():
                return {
                    "ok": True,
                    "chat": self.conversation_manager.export_chat_payload(chat_id),
                    "transcript": "",
                    "response": "I didn't catch that. Please try again and speak a little closer to the microphone.",
                    "audio_base64": "",
                    "response_language": "en",
                    "memory_snippets": [],
                }

            llm_result = await self.llm_interface.ask_llm(transcript, chat_id=chat_id, return_metadata=True)
            response = llm_result["response"]
            memory_snippets = llm_result["memory_snippets"]
            self.llm_interface.update_conversation(transcript, response, chat_id=chat_id)

            try:
                response_language = detect(response)
            except Exception:
                response_language = DEFAULT_RESPONSE_LANGUAGE

            audio_base64 = self.synthesize_speech_base64(response, response_language)

            return {
                "ok": True,
                "chat": self.conversation_manager.export_chat_payload(chat_id),
                "transcript": transcript,
                "response": response,
                "audio_base64": audio_base64,
                "response_language": response_language,
                "memory_snippets": memory_snippets,
            }

    async def process_text(self, text: str, chat_id: str) -> dict:
        with self.lock:
            transcript = text.strip()
            self.conversation_manager.set_active_chat(chat_id)
            if not transcript:
                return {"ok": False, "error": "Empty text message."}

            llm_result = await self.llm_interface.ask_llm(transcript, chat_id=chat_id, return_metadata=True)
            response = llm_result["response"]
            memory_snippets = llm_result["memory_snippets"]
            self.llm_interface.update_conversation(transcript, response, chat_id=chat_id)

            try:
                response_language = detect(response)
            except Exception:
                response_language = DEFAULT_RESPONSE_LANGUAGE

            audio_base64 = self.synthesize_speech_base64(response, response_language)

            return {
                "ok": True,
                "chat": self.conversation_manager.export_chat_payload(chat_id),
                "transcript": transcript,
                "response": response,
                "audio_base64": audio_base64,
                "response_language": response_language,
                "memory_snippets": memory_snippets,
            }


coach = WebVoiceCoach()


def json_error(message: str, status_code: int = 400):
    return jsonify({"ok": False, "error": message}), status_code


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/bootstrap")
def bootstrap():
    return jsonify(coach.get_bootstrap_payload())


@app.post("/api/chats")
def create_chat():
    payload = request.get_json(silent=True) or {}
    chat = coach.conversation_manager.create_chat(
        title=(payload.get("title") or "").strip() or None,
        custom_prompt=(payload.get("custom_prompt") or "").strip(),
        make_active=True,
    )
    return jsonify(
        {
            "ok": True,
            "chat": coach.conversation_manager.export_chat_payload(chat["id"]),
            "chats": coach.conversation_manager.list_chats(),
            "settings": coach.conversation_manager.get_settings(),
        }
    )


@app.get("/api/chats/<chat_id>")
def get_chat(chat_id: str):
    try:
        chat = coach.conversation_manager.set_active_chat(chat_id)
    except FileNotFoundError:
        return json_error("Chat not found.", 404)

    return jsonify(
        {
            "ok": True,
            "chat": coach.conversation_manager.export_chat_payload(chat["id"]),
            "chats": coach.conversation_manager.list_chats(),
            "settings": coach.conversation_manager.get_settings(),
        }
    )


@app.patch("/api/chats/<chat_id>")
def update_chat(chat_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        chat = coach.conversation_manager.update_chat(
            chat_id,
            title=payload.get("title"),
            custom_prompt=payload.get("custom_prompt"),
        )
    except FileNotFoundError:
        return json_error("Chat not found.", 404)

    return jsonify(
        {
            "ok": True,
            "chat": coach.conversation_manager.export_chat_payload(chat["id"]),
            "chats": coach.conversation_manager.list_chats(),
        }
    )


@app.post("/api/settings")
def update_settings():
    payload = request.get_json(silent=True) or {}
    settings = coach.conversation_manager.update_settings(
        global_prompt=payload.get("global_prompt"),
        teaching_memory=payload.get("teaching_memory"),
    )
    return jsonify({"ok": True, "settings": settings})


def _process_audio_request(chat_id: str):
    audio = request.files.get("audio")
    if not audio:
        return json_error("No audio file received.")

    suffix = Path(audio.filename or "recording.webm").suffix or ".webm"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            audio.save(temp_path)

        result = asyncio.run(coach.process_audio(temp_path, chat_id))
        return jsonify(result)
    except FileNotFoundError:
        return json_error("Chat not found.", 404)
    except Exception as error:
        print(f"[WEB] Request error: {error}")
        return jsonify({"ok": False, "error": str(error)}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/api/chats/<chat_id>/audio")
def chat_audio(chat_id: str):
    return _process_audio_request(chat_id)


@app.post("/api/chats/<chat_id>/text")
def chat_text(chat_id: str):
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return json_error("No text received.")

    try:
        result = asyncio.run(coach.process_text(text, chat_id))
        return jsonify(result)
    except FileNotFoundError:
        return json_error("Chat not found.", 404)
    except Exception as error:
        print(f"[WEB] Text request error: {error}")
        return jsonify({"ok": False, "error": str(error)}), 500


@app.post("/api/chat")
def legacy_audio_route():
    return _process_audio_request(coach.conversation_manager.active_chat_id)


@app.post("/api/text")
def legacy_text_route():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return json_error("No text received.")

    try:
        result = asyncio.run(coach.process_text(text, coach.conversation_manager.active_chat_id))
        return jsonify(result)
    except Exception as error:
        print(f"[WEB] Legacy text request error: {error}")
        return jsonify({"ok": False, "error": str(error)}), 500


if __name__ == "__main__":
    print("[WEB] Starting local server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
