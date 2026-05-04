# Ollama Voice Assistant


---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Installation Guide](#installation-guide)
   - [Python Dependencies](#python-dependencies)
   - [FFmpeg Installation](#ffmpeg-installation)
   - [Whisper Installation](#whisper-installation)
   - [Ollama Setup](#ollama-setup)
   - [SearXNG Setup](#searxng-setup)
4. [Usage](#usage)
5. [Code Structure and Customization](#code-structure-and-customization)
6. [Troubleshooting](#troubleshooting)
7. [License and Contributions](#license-and-contributions)
8. [Adding the Zip Package on GitHub](#adding-the-zip-package-on-github)

---

## Overview

This voice assistant is a local application that uses:

- **Ollama** for AI model inference (default model: `llama3.1`, customizable).
- **Whisper (medium model)** for high-quality speech-to-text transcription.
- **Edge TTS** for natural, synthesized voice responses.
- **SearXNG** for real-time internet search queries (when required).
- **Keyboard hotkeys** for toggling recording and exiting the assistant.
- **Web UI option** with a ChatGPT-like layout, chat sidebar, and microphone button.
- **Conversation memory** stored locally with multiple persistent chats and long-term teaching notes.
- **Multi-provider AI selector** with persisted provider/model settings for Ollama, OpenAI API, and Gemini API.

---

## Features

- **Voice Recognition:**\
  Captures audio in the browser and transcribes it locally using OpenAI’s Whisper.

- **Internet Search Integration:**\
  Employs a custom search logic using a local SearXNG instance to fetch up-to-date data when needed.\
  *Refer to the [SearXNG Documentation](https://searxng.github.io/searxng/) for setup instructions.*

- **Natural Text-to-Speech:**\
  Uses Edge TTS to convert responses to speech. Voices adjust based on detected language (default: `en-US-AndrewNeural` for English, `es-ES-ElviraNeural` for Spanish).

- **Conversation Memory:**\
  Stores multiple persistent chats under `chat_data/` so you can continue later.

- **ChatGPT-style Web UI:**\
  Includes a sidebar of chats, text input, microphone button, browser audio playback, editable teaching instructions, and a provider/model selection panel.

- **Provider Switching:**\
  Lets you choose the active AI provider globally for the app. Ollama remains the default fallback if a remote provider fails.

- **OpenAI Web/Login (OpenCode-style):**\
  Includes a browser OAuth flow adapted from OpenCode so you can sign in with ChatGPT locally, persist tokens under `chat_data/`, refresh them automatically, and use Codex-compatible requests without storing raw browser cookies.

---

## Installation Guide

### Instalación simple en Windows

Si querés una instalación tipo "doble clic y listo":

1. Descargá o cloná este repo.
2. Ejecutá `install.bat` (recomendado) o `install.ps1`.
3. Elegí la carpeta base donde querés instalarlo.
4. El instalador clona `ia_profesor`, prepara `.venv`, instala dependencias, verifica Ollama, descarga `qwen2.5:1.5b` y crea el acceso directo `Iniciar ia_profesor` en el escritorio.

Después, abrilo siempre desde el acceso directo del escritorio. En cada inicio el launcher intenta actualizar el repo sin tocar tus datos locales (`chat_data/` y `conversation_history.json`).

### Python Dependencies

Ensure you have Python 3.8+ installed. Install the required packages using:

```bash
pip install -r requirements.txt
```

---

### FFmpeg Installation (Required for Audio Playback)

The assistant uses **ffplay** (a component of FFmpeg) to play audio files. Install FFmpeg as follows:

#### **Windows:**

1. Download FFmpeg from [FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/).
2. Extract the ZIP file (e.g., to `C:\ffmpeg`).
3. Add `C:\ffmpeg\bin` to your System PATH (via Environment Variables).
4. Verify installation by running:
   ```bash
   ffmpeg -version
   ```

---

### Whisper Installation

Whisper is used for transcribing recorded audio. Install Whisper with:

```bash
pip install -U openai-whisper
```

*Note:* Whisper’s models can require significant memory. The script uses the medium model by default.
⚠️The script runs whisper on CPU to conserve memory for the ollama model⚠️

---

### Ollama Setup (For AI Responses)

Ollama provides local inference without internet dependency. To set up:

1. **Download and Install Ollama:**\
   Visit the [Ollama Official Site](https://ollama.ai/download) and follow the installation instructions for your OS.

2. **Pull a Model:**\
   For example, to pull the `llama3.1` model, run:

   ```bash
   ollama pull llama3.1
   ```

3. **Start the Ollama Server:**\
   Run:

   ```bash
   ollama serve
   ```

### **4. Recommended Models Based on Hardware**

| Hardware Specs | Recommended Model |
|--------------|----------------|
| ✅ **Low-end (8GB RAM, iGPU, laptop)** | `mistral` or `phi` |
| ✅ **Mid-range (16GB RAM, RTX 3060/4060)** | `llama3` (smaller versions) |
| ✅ **High-end (32GB+ RAM, RTX 4080/4090, A100, H100)** | `llama3.1` or `mixtral` |
| ✅ **AI-optimized GPU (3090, 4090, A100, etc.)** | `gemma`, `command-r` |

To change models, update the `model` parameter in the code:
```python
response = ollama.chat(model="<CHANGE THIS>", messages=[
    {"role": "system", "content": conversation_context},
    {"role": "user", "content": full_prompt}
])
```

---

## ▶️ How to Use

### **1. Start the Web Version**

If you prefer a browser interface with a microphone button, run:

```sh
web.bat
```

En Windows también podés usar `Iniciar ia_profesor.bat`, que además verifica actualizaciones y dependencias antes de abrir la app. Si detecta Ollama, lo prepara; si no, igual podés usar proveedores remotos como OpenAI o Gemini.

Then open `http://127.0.0.1:5000` if the browser does not open automatically.

The web UI lets you:
- manage multiple chats from a sidebar
- resume the last open conversation automatically
- start/stop recording with the mouse
- keep using text input when you don't want to speak
- edit global coaching instructions, long-term teaching memory, and chat-specific prompts
- choose the active AI provider and model from the "Seleccionar IA" panel
- hear the generated voice directly in the browser

### Provider notes

- **Ollama:** fully supported locally, pero ahora es opcional.
- **OpenAI API:** supported via API key and live model listing from the OpenAI Platform API.
- **Gemini API:** supported via API key and live model listing from the Gemini API.
- **OpenAI Web/Login:** supported through an OpenCode-inspired PKCE browser flow against `auth.openai.com`, with local token refresh and Codex-compatible chat requests.

Provider settings are persisted locally in `chat_data/providers.json`, which stays out of git because `chat_data/` is already ignored.

---

### SearXNG Setup

This version integrates SearXNG to perform real-time internet searches when needed.

1. **Installation and Configuration:**  
   Follow the detailed setup instructions in the [SearXNG Documentation](https://searxng.github.io/searxng/).

2. **Local Instance:**  
   Ensure your SearXNG instance is running and accessible, typically at `http://localhost:8080/search`.

3. **Integration in Code:**  
   The assistant sends search queries to this endpoint to fetch real-time data.

#### Quick Setup (Using Docker)

Ensure that **SearXNG is inside the same directory as this project** or that you are **in the `searxng-docker/searxng` directory** when running these commands.

### **Editing Configuration Files for SearXNG (Docker Setup)**

#### **Windows (PowerShell)**
```powershell
cd searxng-docker\searxng
notepad settings.yml
```

**Paste the updated `settings.yml` content below:**

```yml
# see https://docs.searxng.org/admin/settings/settings.html#settings-use-default-settings
use_default_settings: true

server:
  secret_key: "<PUT A SECRET KEY HERE>"
  limiter: false  # Fully disable rate limiting
  public_instance: false  # Allow API access
  image_proxy: true
  api_enabled: true  
  http_protocol_version: "1.1"
  default_http_headers:
    Access-Control-Allow-Origin: "*"
    Access-Control-Allow-Methods: "GET, POST, OPTIONS"
    Access-Control-Allow-Headers: "*"

ui:
  static_use_hash: true

redis:
  url: redis://redis:6379/0

search:
  formats:
    - html
    - json 

```
Save and exit, then restart SearXNG:
```bash
docker restart searxng
```

#### **Editing `Caddyfile` (If Using Caddy)**
##### **Windows (PowerShell)**
```powershell
cd searxng-docker\searxng
notepad Caddyfile
```
**Paste the updated `Caddyfile` content below:**
```txt
{
  admin off
}

{$SEARXNG_HOSTNAME} {
  log {
        output discard
  }

  tls {$SEARXNG_TLS}

  @api {
        path /config
        path /healthz
        path /stats/errors
        path /stats/checker
        path /search
  }

  @static {
        path /static/*
  }

  @notstatic {
        not path /static/*
  }

  @imageproxy {
        path /image_proxy
  }

  @notimageproxy {
        not path /image_proxy
  }

  header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-XSS-Protection "1; mode=block"
        X-Content-Type-Options "nosniff"
        Permissions-Policy "accelerometer=(),ambient-light-sensor=(),autoplay=(),camera=(),encrypted-media=(),focus-without-user-activation=(),geolocation=(),gyroscope=(),magnetometer=(),microphone=(),midi=(),payment=(),picture-in-picture=(),speaker=(),sync-xhr=(),usb=(),vr=()"
        Feature-Policy "accelerometer 'none';ambient-light-sensor 'none'; autoplay 'none';camera 'none';encrypted-media 'none';focus-without-user-activation 'none'; geolocation 'none';gyroscope 'none';magnetometer 'none';microphone 'none';midi 'none';payment 'none';picture-in-picture 'none'; speaker 'none';sync-xhr 'none';usb 'none';vr 'none'"
        Referrer-Policy "no-referrer"
        X-Robots-Tag "noindex, noarchive, nofollow"
        -Server
  }

  header @api {
        Access-Control-Allow-Origin  "*"
        Access-Control-Allow-Methods "GET, POST, OPTIONS"
        Access-Control-Allow-Headers "*"
        Access-Control-Expose-Headers "*"
  }

  header @static {
        Cache-Control "public, max-age=31536000"
        defer
  }

  header @notstatic {
        Cache-Control "no-cache, no-store"
        Pragma "no-cache"
  }

  header @imageproxy {
        Content-Security-Policy "default-src 'none'; img-src 'self' data:"
  }

  header @notimageproxy {
        Content-Security-Policy "upgrade-insecure-requests; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self' https://github.com/searxng/searxng/issues/new; font-src 'self'; frame-ancestors 'self'; base-uri 'self'; connect-src 'self' https://overpass-api.de; img-src 'self' data: https://*.tile.openstreetmap.org; frame-src https://www.youtube-nocookie.com https://player.vimeo.com https://www.dailymotion.com https://www.deezer.com https://www.mixcloud.com https://w.soundcloud.com https://embed.spotify.com"
  }

  # SearXNG
  handle {
        encode zstd gzip

        reverse_proxy localhost:8080 {
               header_up X-Real-IP {remote_host}
               header_up X-Forwarded-For {remote_host}
               header_up X-Forwarded-Port {http.request.port}
               header_up X-Forwarded-Proto {http.request.scheme}

               header_up Access-Control-Allow-Origin "*"
               header_up Access-Control-Allow-Methods "GET, POST, OPTIONS"
               header_up Access-Control-Allow-Headers "*"
               header_up Access-Control-Expose-Headers "*"
               header_up User-Agent ""
        }
  }

  @api_requests path /*
  
  handle @api_requests {
      header Access-Control-Allow-Origin "*"
      header Access-Control-Allow-Methods "GET, POST, OPTIONS"
      header Access-Control-Allow-Headers "*"
      header Access-Control-Expose-Headers "*"

      reverse_proxy localhost:8080

```
Restart Caddy:
```bash
docker restart caddy
```

#### **Editing `.env` File (Environment Variables for SearXNG)**
##### **Windows (PowerShell)**
```powershell
cd searxng-docker\searxng
notepad .env
```
**Paste the updated `.env` content below:**
```ini
# By default listen on https://localhost
# To change this:
# * uncomment SEARXNG_HOSTNAME, and replace <host> by the SearXNG hostname
# * uncomment LETSENCRYPT_EMAIL, and replace <email> by your email (require to create a Let's Encrypt certificate)

# SEARXNG_HOSTNAME=<host>
# LETSENCRYPT_EMAIL=<email>

# Optional:
# If you run a very small or a very large instance, you might want to change the amount of used uwsgi workers and threads per worker
# More workers (= processes) means that more search requests can be handled at the same time, but it also causes more resource usage

# SEARXNG_UWSGI_WORKERS=4
# SEARXNG_UWSGI_THREADS=4
SEARXNG_RATE_LIMIT=0

```
Restart SearXNG:
```bash
docker restart searxng
```

---

## Usage

To start the voice assistant, run:

```bash
python voice_assistant.py
```

Press **ALT** to start/stop recording and **ESC** to exit.

---

## Code Structure and Customization

The assistant consists of multiple components:

- `web_app.py`: Flask server for the local web coach.
- `templates/index.html`: ChatGPT-style browser interface.
- `chat_data/`: persistent multi-chat storage.
- `conversation_history.json`: compatibility mirror of the active chat.
- `web.bat`: starts the local web coach.

### Customization Options

- **Whisper Model Size:** Change the model size in `config.py` (`WHISPER_MODEL`).
- **AI Model:** Change the default AI model in `config.py` (`LLM_MODEL`).
- **Voice Selection:** Customize TTS voices in `config.py`.
- **System Prompts:** Modify the default coaching behavior in `config.py` or override it from the web UI.

---

## Troubleshooting

If issues arise:

- Ensure all dependencies are installed correctly.
- Verify that Whisper, Ollama, and SearXNG services are running.
- Check for missing environment variables or configuration errors.

---

## License and Contributions

This project is open-source. Contributions, bug fixes, and feature suggestions are welcome! Feel free to submit pull requests or open issues.

---

For any questions refer to `Discord:` `hamzanasry`

---

