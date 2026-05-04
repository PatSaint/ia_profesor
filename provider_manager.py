import json
import os
import re
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional

import ollama
import requests

from config import (
    GEMINI_DEFAULT_MODEL,
    LLM_MODEL,
    OPENAI_WEB_DEFAULT_MODEL,
    OPENAI_WEB_MODELS,
    OLLAMA_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_MODEL,
    PROVIDER_CONFIG_FILE,
    PROVIDER_REQUEST_TIMEOUT,
)
from openai_web_auth import OpenAIWebAuthError, OpenAIWebAuthStore


class ProviderError(Exception):
    pass


class ProviderManager:
    def __init__(self):
        self.config_file = PROVIDER_CONFIG_FILE
        self.openai_web_auth = OpenAIWebAuthStore()
        self._ensure_storage()
        self.config = self._load_or_create_config()

    def _ensure_storage(self) -> None:
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

    def _default_config(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "active_provider": "ollama",
            "active_model": LLM_MODEL,
            "providers": {
                "ollama": {
                    "label": "Ollama",
                    "enabled": True,
                    "base_url": OLLAMA_DEFAULT_BASE_URL,
                    "selected_model": LLM_MODEL,
                    "available_models": [],
                    "connection_status": "Local mode ready.",
                    "last_error": "",
                },
                "openai_api": {
                    "label": "OpenAI API",
                    "enabled": False,
                    "api_key": "",
                    "selected_model": OPENAI_DEFAULT_MODEL,
                    "available_models": [],
                    "connection_status": "Add an API key to connect.",
                    "last_error": "",
                },
                "gemini_api": {
                    "label": "Gemini API",
                    "enabled": False,
                    "api_key": "",
                    "selected_model": GEMINI_DEFAULT_MODEL,
                    "available_models": [],
                    "connection_status": "Add an API key to connect.",
                    "last_error": "",
                },
                "openai_web": {
                    "label": "OpenAI Web/Login",
                    "enabled": False,
                    "selected_model": OPENAI_WEB_DEFAULT_MODEL,
                    "available_models": list(OPENAI_WEB_MODELS),
                    "connection_status": "Sign in with your ChatGPT browser account to enable Codex-compatible chat.",
                    "last_error": "",
                },
                "self_hosted_new": {
                    "label": "Agregar servidor local/red",
                    "enabled": False,
                    "custom_name": "",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "selected_model": "",
                    "available_models": [],
                    "connection_status": "Agregá un servidor local, de red o OpenAI-compatible.",
                    "last_error": "",
                    "preset": "openai_compatible",
                    "api_key": "",
                    "is_template": True,
                },
            },
        }

    def _load_json(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _save_json(self, path: str, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)

    def _load_or_create_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_file):
            try:
                config = self._load_json(self.config_file)
                if isinstance(config, dict):
                    return self._normalize_config(config)
            except Exception as error:
                print(f"[PROVIDERS] Error loading config: {error}")

        config = self._default_config()
        self._save_json(self.config_file, config)
        return config

    def _normalize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        defaults = self._default_config()
        merged = deepcopy(defaults)
        merged.update({key: value for key, value in config.items() if key != "providers"})
        merged_providers = merged["providers"]
        for provider_id, provider_defaults in defaults["providers"].items():
            stored = (config.get("providers") or {}).get(provider_id, {})
            if isinstance(stored, dict):
                provider_defaults.update(stored)
            merged_providers[provider_id] = provider_defaults

        for provider_id, stored in (config.get("providers") or {}).items():
            if provider_id in merged_providers:
                continue
            if isinstance(stored, dict):
                merged_providers[provider_id] = stored

        active_provider = merged.get("active_provider")
        if active_provider not in merged_providers:
            merged["active_provider"] = "ollama"

        openai_web = merged_providers.get("openai_web", {})
        if openai_web.get("selected_model") in {"", "chatgpt-4o-latest"}:
            openai_web["selected_model"] = OPENAI_WEB_DEFAULT_MODEL
        openai_web["available_models"] = self._sanitize_model_list(
            openai_web.get("available_models", []),
            openai_web.get("selected_model", OPENAI_WEB_DEFAULT_MODEL),
        ) or list(OPENAI_WEB_MODELS)
        self._sync_openai_web_provider(merged_providers)

        active_provider_config = merged_providers[merged["active_provider"]]
        merged["active_model"] = active_provider_config.get("selected_model") or merged.get("active_model") or LLM_MODEL
        self._save_json(self.config_file, merged)
        return merged

    def _save(self) -> None:
        self._save_json(self.config_file, self.config)

    def _provider(self, provider_id: str) -> Dict[str, Any]:
        provider = self.config.get("providers", {}).get(provider_id)
        if not provider:
            raise ProviderError(f"Unknown provider: {provider_id}")
        return provider

    def _mask_secret(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"

    def _sanitize_model_list(self, models: List[str], fallback_model: str) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for model in models:
            item = (model or "").strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)
        if fallback_model and fallback_model not in seen:
            cleaned.insert(0, fallback_model)
        return cleaned

    def get_ui_state(self) -> Dict[str, Any]:
        self._sync_openai_web_provider()
        active_provider = self.config.get("active_provider", "ollama")
        if active_provider != "ollama" and not self._provider(active_provider).get("enabled"):
            self.config["active_provider"] = "ollama"
            self.config["active_model"] = self._provider("ollama").get("selected_model") or LLM_MODEL
            self._save()
            active_provider = "ollama"
        active_config = self._provider(active_provider)
        providers = []

        for provider_id, provider in self.config.get("providers", {}).items():
            public_auth_state = self.openai_web_auth.get_public_state() if provider_id == "openai_web" else {}
            providers.append(
                {
                    "id": provider_id,
                    "label": provider.get("label", provider_id),
                    "enabled": bool(provider.get("enabled")),
                    "supports_chat": True,
                    "supports_activation": not bool(provider.get("is_template")),
                    "selected_model": provider.get("selected_model", ""),
                    "available_models": provider.get("available_models", []),
                    "connection_status": provider.get("connection_status", ""),
                    "last_error": provider.get("last_error", ""),
                    "base_url": provider.get("base_url", "") if provider_id == "ollama" or provider_id.startswith("self_hosted:") or provider_id == "self_hosted_new" else "",
                    "api_key_configured": bool(provider.get("api_key")) if provider_id in {"openai_api", "gemini_api"} or provider_id.startswith("self_hosted:") or provider_id == "self_hosted_new" else False,
                    "api_key_masked": self._mask_secret(provider.get("api_key", "")) if provider_id in {"openai_api", "gemini_api"} or provider_id.startswith("self_hosted:") or provider_id == "self_hosted_new" else "",
                    "preset": provider.get("preset", "") if provider_id.startswith("self_hosted:") or provider_id == "self_hosted_new" else "",
                    "custom_name": provider.get("custom_name", "") if provider_id.startswith("self_hosted:") or provider_id == "self_hosted_new" else "",
                    "is_template": bool(provider.get("is_template")),
                    "oauth_connected": bool(public_auth_state.get("connected")) if provider_id == "openai_web" else False,
                    "oauth_email": public_auth_state.get("email", "") if provider_id == "openai_web" else "",
                    "oauth_account_id": public_auth_state.get("account_id", "") if provider_id == "openai_web" else "",
                    "oauth_expires_at": public_auth_state.get("expires_at", 0) if provider_id == "openai_web" else 0,
                    "notes": self._provider_notes(provider_id),
                }
            )

        return {
            "active_provider": active_provider,
            "active_provider_label": active_config.get("label", active_provider),
            "active_model": self.config.get("active_model") or active_config.get("selected_model") or "",
            "providers": providers,
        }

    def _provider_notes(self, provider_id: str) -> str:
        notes = {
            "ollama": "Runs locally through Ollama and remains the default fallback.",
            "openai_api": "Official OpenAI Platform API with API key authentication.",
            "gemini_api": "Official Gemini API with API key authentication.",
            "openai_web": (
                "Adapted from OpenCode's Codex browser OAuth flow: PKCE login against auth.openai.com, local token "
                "storage, automatic refresh, and ChatGPT Codex-compatible requests."
            ),
        }
        if provider_id == "self_hosted_new":
            return "Creá conexiones locales o de red: Ollama, LM Studio o cualquier servidor OpenAI-compatible."
        if provider_id.startswith("self_hosted:"):
            return "Servidor self-hosted/local o en red. Puede ser Ollama, LM Studio u otro backend OpenAI-compatible."
        return notes.get(provider_id, "")

    def _sync_openai_web_provider(self, providers: Optional[Dict[str, Any]] = None) -> None:
        provider_map = providers or self.config.get("providers", {})
        provider = provider_map.get("openai_web")
        if not provider:
            return

        auth_state = self.openai_web_auth.get_public_state()
        provider["available_models"] = self._sanitize_model_list(provider.get("available_models", []), OPENAI_WEB_DEFAULT_MODEL)
        if provider.get("selected_model") not in provider["available_models"]:
            provider["selected_model"] = provider["available_models"][0]

        if auth_state.get("connected"):
            provider["enabled"] = True
            provider["last_error"] = ""
            summary = auth_state.get("email") or auth_state.get("account_id") or "ChatGPT account connected"
            provider["connection_status"] = f"Connected via browser login. {summary}. {len(provider['available_models'])} model(s) ready."
        else:
            provider["enabled"] = False
            if not provider.get("last_error"):
                provider["connection_status"] = "Sign in with your ChatGPT browser account to enable Codex-compatible chat."

    def start_openai_web_login(self) -> Dict[str, Any]:
        self._provider("openai_web")
        result = self.openai_web_auth.start_browser_login()
        provider = self._provider("openai_web")
        provider["last_error"] = ""
        provider["connection_status"] = "Browser login started. Finish the OpenAI sign-in window."
        self._save()
        return result

    def complete_openai_web_login(self, code: str, state: str) -> Dict[str, Any]:
        token = self.openai_web_auth.complete_browser_login(code, state)
        provider = self._provider("openai_web")
        provider["enabled"] = True
        provider["last_error"] = ""
        provider["available_models"] = self._sanitize_model_list(provider.get("available_models", []), OPENAI_WEB_DEFAULT_MODEL)
        provider["selected_model"] = provider.get("selected_model") or OPENAI_WEB_DEFAULT_MODEL
        provider["connection_status"] = f"Connected via browser login. {token.get('email') or token.get('account_id') or 'ChatGPT account ready'}."
        self._save()
        return self.get_ui_state()

    def disconnect_openai_web(self) -> Dict[str, Any]:
        self.openai_web_auth.clear()
        provider = self._provider("openai_web")
        provider["enabled"] = False
        provider["last_error"] = ""
        provider["connection_status"] = "Signed out from local OpenAI browser auth storage."
        if self.config.get("active_provider") == "openai_web":
            self.config["active_provider"] = "ollama"
            self.config["active_model"] = self._provider("ollama").get("selected_model") or LLM_MODEL
        self._save()
        return self.get_ui_state()

    def configure_provider(self, provider_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if provider_id == "self_hosted_new" or provider_id.startswith("self_hosted:"):
            return self._configure_self_hosted(provider_id, payload)

        provider = self._provider(provider_id)

        if provider_id == "openai_web":
            incoming_model = (payload.get("selected_model") or "").strip()
            if incoming_model:
                provider["selected_model"] = incoming_model
            self.refresh_models(provider_id, persist=False)
            self._sync_openai_web_provider()
            self._save()
            return self.get_ui_state()

        if provider_id == "ollama":
            provider["base_url"] = (payload.get("base_url") or provider.get("base_url") or OLLAMA_DEFAULT_BASE_URL).strip()

        if provider_id in {"openai_api", "gemini_api"}:
            incoming_key = payload.get("api_key")
            if incoming_key is not None:
                provider["api_key"] = incoming_key.strip()

        incoming_model = (payload.get("selected_model") or "").strip()
        if incoming_model:
            provider["selected_model"] = incoming_model

        try:
            models = self.refresh_models(provider_id, persist=False)
        except Exception as error:
            provider["enabled"] = False if provider_id != "ollama" else provider.get("enabled", True)
            provider["last_error"] = str(error)
            provider["connection_status"] = f"Connection failed: {error}"
            self._save()
            raise
        provider["enabled"] = True
        provider["last_error"] = ""
        if models and not provider.get("selected_model"):
            provider["selected_model"] = models[0]
        provider["connection_status"] = f"Connected. {len(models)} model(s) available."
        self._save()

        if payload.get("make_active"):
            self.activate_provider(provider_id, payload.get("selected_model") or provider.get("selected_model"))

        return self.get_ui_state()

    def refresh_models(self, provider_id: str, persist: bool = True) -> List[str]:
        provider = self._provider(provider_id)

        if provider_id == "ollama":
            models = self._list_ollama_models(provider)
        elif provider_id.startswith("self_hosted:"):
            models = self._list_self_hosted_models(provider)
        elif provider_id == "openai_api":
            api_key = (provider.get("api_key") or "").strip()
            if not api_key:
                raise ProviderError("OpenAI API key is required.")
            models = self._list_openai_models(api_key)
        elif provider_id == "gemini_api":
            api_key = (provider.get("api_key") or "").strip()
            if not api_key:
                raise ProviderError("Gemini API key is required.")
            models = self._list_gemini_models(api_key)
        elif provider_id == "openai_web":
            if not self.openai_web_auth.is_connected():
                raise ProviderError("OpenAI browser login is not connected yet.")
            self.openai_web_auth.ensure_fresh_token()
            models = list(OPENAI_WEB_MODELS)
        else:
            raise ProviderError("This provider cannot load models in the current app.")

        provider["available_models"] = self._sanitize_model_list(models, provider.get("selected_model", ""))
        if not provider.get("selected_model") and provider["available_models"]:
            provider["selected_model"] = provider["available_models"][0]
        if persist:
            provider["last_error"] = ""
            provider["connection_status"] = f"Connected. {len(provider['available_models'])} model(s) available."
            self._save()
        return provider["available_models"]

    def activate_provider(self, provider_id: str, model: Optional[str] = None) -> Dict[str, Any]:
        provider = self._provider(provider_id)
        if provider_id == "openai_web" and not self.openai_web_auth.is_connected():
            raise ProviderError("Connect OpenAI browser login before activating it.")
        if provider.get("is_template"):
            raise ProviderError("Guardá primero este servidor antes de activarlo.")

        if provider_id != "ollama" and not provider.get("enabled"):
            raise ProviderError("Connect this provider before activating it.")

        selected_model = (model or provider.get("selected_model") or "").strip()
        if selected_model:
            provider["selected_model"] = selected_model

        if not provider.get("selected_model"):
            raise ProviderError("Choose a model before activating this provider.")

        self.config["active_provider"] = provider_id
        self.config["active_model"] = provider["selected_model"]
        self._save()
        return self.get_ui_state()

    def get_active_provider(self) -> Dict[str, Any]:
        provider_id = self.config.get("active_provider", "ollama")
        provider = self._provider(provider_id)
        return {
            "id": provider_id,
            "label": provider.get("label", provider_id),
            "model": self.config.get("active_model") or provider.get("selected_model") or "",
        }

    def chat(self, messages: List[Dict[str, str]]) -> str:
        active = self.get_active_provider()
        provider_id = active["id"]
        model = active["model"]

        try:
            if provider_id == "ollama":
                return self._chat_with_ollama(model, messages)
            if provider_id == "openai_api":
                provider = self._provider(provider_id)
                return self._chat_with_openai(provider.get("api_key", ""), model, messages)
            if provider_id == "gemini_api":
                provider = self._provider(provider_id)
                return self._chat_with_gemini(provider.get("api_key", ""), model, messages)
            if provider_id == "openai_web":
                return self._chat_with_openai_web(model, messages)
            if provider_id.startswith("self_hosted:"):
                provider = self._provider(provider_id)
                return self._chat_with_self_hosted(provider, model, messages)
            raise ProviderError(f"Provider {provider_id} is not supported for chat.")
        except Exception as error:
            print(f"[PROVIDERS] Active provider '{provider_id}' failed: {error}")
            if provider_id == "ollama":
                raise
            raise ProviderError(f"Active provider '{provider_id}' failed: {error}")

    def _fallback_to_ollama(self, messages: List[Dict[str, str]], original_error: Exception) -> str:
        fallback = self._provider("ollama")
        fallback_model = fallback.get("selected_model") or LLM_MODEL
        try:
            response = self._chat_with_ollama(fallback_model, messages)
            fallback["connection_status"] = f"Fallback succeeded after remote provider error: {original_error}"
            self._save()
            return response
        except Exception as fallback_error:
            raise ProviderError(f"Active provider failed ({original_error}) and Ollama fallback also failed ({fallback_error}).")

    def _list_ollama_models(self, provider: Dict[str, Any]) -> List[str]:
        base_url = (provider.get("base_url") or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
        response = requests.get(f"{base_url}/api/tags", timeout=15)
        response.raise_for_status()
        payload = response.json()
        models = []
        for item in payload.get("models", []):
            name = item.get("name") or item.get("model") or ""
            if name:
                models.append(name)
        return models or [provider.get("selected_model") or LLM_MODEL]

    def _list_openai_models(self, api_key: str) -> List[str]:
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if response.status_code == 401:
            raise ProviderError("OpenAI API key was rejected.")
        response.raise_for_status()
        payload = response.json()
        ids = [item.get("id", "") for item in payload.get("data", [])]
        preferred = [model for model in ids if re.match(r"^(gpt|o[134])", model)]
        return sorted(preferred or ids)

    def _normalize_self_hosted_url(self, base_url: str, preset: str) -> str:
        url = (base_url or "").strip().rstrip("/")
        if not url:
            raise ProviderError("Base URL is required.")
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = f"http://{url}"
        if preset != "ollama" and not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    def _list_self_hosted_models(self, provider: Dict[str, Any]) -> List[str]:
        preset = (provider.get("preset") or "openai_compatible").strip()
        base_url = self._normalize_self_hosted_url(provider.get("base_url", ""), preset)
        provider["base_url"] = base_url

        if preset == "ollama":
            return self._list_ollama_models(provider)

        headers = {"Content-Type": "application/json"}
        api_key = (provider.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.get(f"{base_url}/models", headers=headers, timeout=PROVIDER_REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        models = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
        return self._sanitize_model_list(models, provider.get("selected_model", ""))

    def _chat_with_self_hosted(self, provider: Dict[str, Any], model: str, messages: List[Dict[str, str]]) -> str:
        preset = (provider.get("preset") or "openai_compatible").strip()
        base_url = self._normalize_self_hosted_url(provider.get("base_url", ""), preset)
        provider["base_url"] = base_url
        if preset == "ollama":
            client = ollama.Client(host=base_url)
            response = client.chat(model=model, messages=messages)
            return response["message"]["content"].strip()

        headers = {"Content-Type": "application/json"}
        api_key = (provider.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages},
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return self._extract_openai_text(response.json())

    def _configure_self_hosted(self, provider_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        custom_name = (payload.get("custom_name") or "").strip()
        preset = (payload.get("preset") or "openai_compatible").strip() or "openai_compatible"
        base_url = (payload.get("base_url") or "").strip()
        api_key = (payload.get("api_key") or "").strip()
        selected_model = (payload.get("selected_model") or "").strip()

        if not custom_name:
            raise ProviderError("A display name is required for the local/server AI.")
        if not base_url:
            raise ProviderError("A base URL is required for the local/server AI.")

        if provider_id == "self_hosted_new":
            provider_id = f"self_hosted:{uuid.uuid4().hex[:10]}"
            provider = {
                "label": custom_name,
                "enabled": False,
                "custom_name": custom_name,
                "base_url": base_url,
                "selected_model": selected_model,
                "available_models": [],
                "connection_status": "Checking connection...",
                "last_error": "",
                "preset": preset,
                "api_key": api_key,
            }
            self.config["providers"][provider_id] = provider
        else:
            provider = self._provider(provider_id)
            provider["label"] = custom_name
            provider["custom_name"] = custom_name
            provider["base_url"] = base_url
            provider["preset"] = preset
            provider["api_key"] = api_key
            if selected_model:
                provider["selected_model"] = selected_model

        try:
            models = self.refresh_models(provider_id, persist=False)
        except Exception as error:
            provider["enabled"] = False
            provider["last_error"] = str(error)
            provider["connection_status"] = f"Connection failed: {error}"
            self._save()
            raise

        provider["enabled"] = True
        provider["last_error"] = ""
        if selected_model:
            provider["selected_model"] = selected_model
        elif models and not provider.get("selected_model"):
            provider["selected_model"] = models[0]
        provider["connection_status"] = f"Connected. {len(models)} model(s) available."
        self._save()
        return self.get_ui_state()

    def _list_gemini_models(self, api_key: str) -> List[str]:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if response.status_code == 400:
            raise ProviderError("Gemini API key was rejected or the API is not enabled.")
        response.raise_for_status()
        payload = response.json()
        models = []
        for item in payload.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            name = (item.get("name") or "").replace("models/", "")
            if name:
                models.append(name)
        preferred = [model for model in models if model.startswith("gemini-")]
        return sorted(preferred or models)

    def _chat_with_ollama(self, model: str, messages: List[Dict[str, str]]) -> str:
        base_url = (self._provider("ollama").get("base_url") or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
        client = ollama.Client(host=base_url)
        response = client.chat(model=model, messages=messages)
        return response["message"]["content"].strip()

    def _chat_with_openai(self, api_key: str, model: str, messages: List[Dict[str, str]]) -> str:
        if not api_key:
            raise ProviderError("OpenAI API key is required.")

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
            },
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if response.status_code == 401:
            raise ProviderError("OpenAI API key was rejected.")
        response.raise_for_status()
        return self._extract_openai_text(response.json())

    def _extract_openai_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", []) if isinstance(payload, dict) else []
        if not choices:
            output = payload.get("output", []) if isinstance(payload, dict) else []
            if isinstance(output, list):
                parts: List[str] = []
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "message":
                        for content in item.get("content", []):
                            if isinstance(content, dict) and content.get("text"):
                                parts.append(str(content.get("text")))
                    elif item.get("text"):
                        parts.append(str(item.get("text")))
                text = "\n".join(part.strip() for part in parts if str(part).strip()).strip()
                if text:
                    return text
            raise ProviderError("OpenAI returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "\n".join(part for part in text_parts if part).strip()
        if message.get("reasoning_text") and not content:
            return str(message.get("reasoning_text")).strip()
        return str(content).strip()

    def _chat_with_openai_web(self, model: str, messages: List[Dict[str, str]]) -> str:
        if not self.openai_web_auth.is_connected():
            raise ProviderError("OpenAI browser login is not connected.")

        def extract_stream_text(response: requests.Response) -> str:
            chunks: List[str] = []

            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                else:
                    line = str(raw_line).strip()
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue

                try:
                    payload = json.loads(data)
                except Exception:
                    continue

                if not isinstance(payload, dict):
                    continue

                event_type = str(payload.get("type", ""))

                if event_type.endswith("output_text.delta"):
                    delta = payload.get("delta")
                    if isinstance(delta, str) and delta:
                        chunks.append(delta)
                    continue

                if event_type.endswith("output_text.done"):
                    text = payload.get("text")
                    if isinstance(text, str) and text:
                        chunks.append(text)
                    continue

                if event_type == "response.completed":
                    response_data = payload.get("response")
                    if isinstance(response_data, dict):
                        try:
                            text = self._extract_openai_text(response_data)
                            if text:
                                chunks.append(text)
                        except Exception:
                            pass

            final_text = "".join(chunks).strip()
            if final_text:
                return final_text
            raise ProviderError("OpenAI web returned an empty streamed response.")

        def build_payload_parts() -> tuple[str, List[Dict[str, Any]]]:
            instructions_parts: List[str] = []
            items: List[Dict[str, Any]] = []
            for message in messages:
                role = (message.get("role") or "user").strip() or "user"
                content = (message.get("content") or "").strip()
                if not content:
                    continue
                if role == "system":
                    instructions_parts.append(content)
                    continue
                items.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )
            instructions = "\n\n".join(part for part in instructions_parts if part).strip()
            if not instructions:
                instructions = "You are a helpful AI assistant."
            return instructions, items

        def make_request(force_refresh: bool = False) -> requests.Response:
            if force_refresh:
                self.openai_web_auth.ensure_fresh_token(force_refresh=True)
            headers = self.openai_web_auth.get_request_headers()
            headers["session_id"] = f"ia-profesor-{uuid.uuid4()}"
            headers["Accept"] = "text/event-stream"
            instructions, input_items = build_payload_parts()
            payload: Dict[str, Any] = {
                "model": model,
                "instructions": instructions,
                "input": input_items,
                "store": False,
                "stream": True,
            }
            return requests.post(
                self.openai_web_auth.CODEX_API_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=PROVIDER_REQUEST_TIMEOUT,
                stream=True,
            )

        try:
            response = make_request(force_refresh=False)
            if response.status_code == 401:
                response = make_request(force_refresh=True)
            if response.status_code in {401, 403}:
                raise ProviderError("OpenAI browser login was rejected. Sign in again.")
            if response.status_code >= 400:
                detail = response.text.strip()
                raise ProviderError(f"OpenAI web request failed ({response.status_code}): {detail[:800]}")
            response.raise_for_status()
            return extract_stream_text(response)
        except OpenAIWebAuthError as error:
            raise ProviderError(str(error))

    def _chat_with_gemini(self, api_key: str, model: str, messages: List[Dict[str, str]]) -> str:
        if not api_key:
            raise ProviderError("Gemini API key is required.")

        system_parts = []
        contents = []
        for message in messages:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                }
            )

        payload: Dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["system_instruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=payload,
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if response.status_code in {400, 404}:
            detail = response.text.strip()
            raise ProviderError(f"Gemini request failed ({response.status_code}). {detail[:600]}")
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            raise ProviderError("Gemini returned no candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return text.strip()
