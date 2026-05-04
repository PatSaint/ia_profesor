import asyncio
import base64
import html
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
from openai_web_auth import OpenAIWebAuthError
from provider_manager import ProviderError, ProviderManager

warnings.filterwarnings("ignore", message="You are using `torch.load` with `weights_only=False`")
warnings.filterwarnings("ignore", message="Performing inference on CPU when CUDA is available")
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


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
        self.provider_manager = ProviderManager()
        self.llm_interface = LLMInterface(self.conversation_manager, self.provider_manager)
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

    def detect_response_language(self, text: str) -> str:
        try:
            return detect(text)
        except Exception:
            return DEFAULT_RESPONSE_LANGUAGE

    def synthesize_for_text(self, text: str, lang: str | None = None) -> dict:
        final_lang = (lang or "").strip() or self.detect_response_language(text)
        audio_base64 = self.synthesize_speech_base64(text, final_lang)
        return {
            "ok": True,
            "audio_base64": audio_base64,
            "response_language": final_lang,
        }

    def get_bootstrap_payload(self) -> dict:
        active_chat = self.conversation_manager.export_chat_payload()
        return {
            "ok": True,
            "active_chat_id": active_chat["id"],
            "active_chat": active_chat,
            "chats": self.conversation_manager.list_chats(),
            "settings": self.conversation_manager.get_settings(),
            "providers": self.provider_manager.get_ui_state(),
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

            response_language = self.detect_response_language(response)

            return {
                "ok": True,
                "chat": self.conversation_manager.export_chat_payload(chat_id),
                "transcript": transcript,
                "response": response,
                "audio_base64": "",
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

            response_language = self.detect_response_language(response)

            return {
                "ok": True,
                "chat": self.conversation_manager.export_chat_payload(chat_id),
                "transcript": transcript,
                "response": response,
                "audio_base64": "",
                "response_language": response_language,
                "memory_snippets": memory_snippets,
            }


coach = WebVoiceCoach()


def json_error(message: str, status_code: int = 400):
    return jsonify({"ok": False, "error": message}), status_code


def _callback_html(ok: bool, message: str) -> str:
    title = "OpenAI login complete" if ok else "OpenAI login failed"
    color = "#10a37f" if ok else "#ef4444"
    payload = "true" if ok else "false"
    safe_display = html.escape(message)
    safe_message = message.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>{title}</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e5e7eb; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
      .card {{ max-width: 520px; padding: 28px; border-radius: 18px; border: 1px solid #243041; background: #111827; text-align:center; }}
      h1 {{ margin-top:0; color:{color}; }}
      p {{ line-height:1.5; color:#cbd5e1; }}
    </style>
  </head>
  <body>
    <div class=\"card\">
      <h1>{title}</h1>
      <p>{safe_display}</p>
    </div>
    <script>
      try {{
        if (window.opener) {{
          window.opener.postMessage({{ type: 'openai-web-auth', ok: {payload}, message: `{safe_message}` }}, window.location.origin);
        }}
      }} catch (_error) {{}}
      setTimeout(() => window.close(), 1200);
    </script>
  </body>
</html>"""


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


@app.delete("/api/chats/<chat_id>")
def delete_chat(chat_id: str):
    try:
        active_chat = coach.conversation_manager.delete_chat(chat_id)
    except FileNotFoundError:
        return json_error("Chat not found.", 404)

    return jsonify(
        {
            "ok": True,
            "active_chat": active_chat,
            "chats": coach.conversation_manager.list_chats(),
            "settings": coach.conversation_manager.get_settings(),
            "providers": coach.provider_manager.get_ui_state(),
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


@app.get("/api/providers")
def get_providers():
    return jsonify({"ok": True, "providers": coach.provider_manager.get_ui_state()})


@app.post("/api/providers/connect")
def connect_provider():
    payload = request.get_json(silent=True) or {}
    provider_id = (payload.get("provider") or "").strip()
    if not provider_id:
        return json_error("Provider is required.")

    try:
        providers = coach.provider_manager.configure_provider(provider_id, payload)
        return jsonify({"ok": True, "providers": providers})
    except ProviderError as error:
        return json_error(str(error), 400)
    except Exception as error:
        print(f"[WEB] Provider connect error: {error}")
        return json_error(str(error), 500)


@app.post("/api/providers/activate")
def activate_provider():
    payload = request.get_json(silent=True) or {}
    provider_id = (payload.get("provider") or "").strip()
    if not provider_id:
        return json_error("Provider is required.")

    try:
        providers = coach.provider_manager.activate_provider(provider_id, payload.get("model"))
        return jsonify({"ok": True, "providers": providers})
    except ProviderError as error:
        return json_error(str(error), 400)
    except Exception as error:
        print(f"[WEB] Provider activation error: {error}")
        return json_error(str(error), 500)


@app.post("/api/providers/openai-web/start")
def start_openai_web_login():
    try:
        result = coach.provider_manager.start_openai_web_login()
        return jsonify({"ok": True, **result, "providers": coach.provider_manager.get_ui_state()})
    except (ProviderError, OpenAIWebAuthError) as error:
        return json_error(str(error), 400)
    except Exception as error:
        print(f"[WEB] OpenAI browser login start error: {error}")
        return json_error(str(error), 500)


@app.get("/api/providers/openai-web/callback")
def complete_openai_web_login():
    error = (request.args.get("error") or "").strip()
    if error:
        description = (request.args.get("error_description") or error).strip()
        return _callback_html(False, description), 200, {"Content-Type": "text/html; charset=utf-8"}

    code = (request.args.get("code") or "").strip()
    state = (request.args.get("state") or "").strip()
    if not code or not state:
        return _callback_html(False, "Missing OAuth code or state."), 400, {"Content-Type": "text/html; charset=utf-8"}

    try:
        coach.provider_manager.complete_openai_web_login(code, state)
        return _callback_html(True, "Login completed. You can return to the app."), 200, {"Content-Type": "text/html; charset=utf-8"}
    except (ProviderError, OpenAIWebAuthError) as auth_error:
        return _callback_html(False, str(auth_error)), 400, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as auth_error:
        print(f"[WEB] OpenAI browser callback error: {auth_error}")
        return _callback_html(False, str(auth_error)), 500, {"Content-Type": "text/html; charset=utf-8"}


@app.post("/api/providers/openai-web/disconnect")
def disconnect_openai_web_login():
    try:
        providers = coach.provider_manager.disconnect_openai_web()
        return jsonify({"ok": True, "providers": providers})
    except Exception as error:
        print(f"[WEB] OpenAI browser disconnect error: {error}")
        return json_error(str(error), 500)


@app.post("/api/tts")
def generate_tts():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    lang = (payload.get("lang") or "").strip()
    if not text:
        return json_error("Text is required for TTS.")

    try:
        return jsonify(coach.synthesize_for_text(text, lang or None))
    except Exception as error:
        print(f"[WEB][TTS] On-demand generation error: {error}")
        return json_error(str(error), 500)


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
    host = os.getenv("IA_PROFESOR_HOST", "127.0.0.1")
    port = int(os.getenv("IA_PROFESOR_PORT", "5000"))
    print(f"[WEB] Starting local server on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
