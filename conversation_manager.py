import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import CHAT_INDEX_FILE, CHAT_STORAGE_DIR, DEFAULT_CHAT_TITLE, HISTORY_FILE


class ConversationManager:
    def __init__(self):
        self.history_file = HISTORY_FILE
        self.storage_dir = CHAT_STORAGE_DIR
        self.index_file = CHAT_INDEX_FILE
        self.chats_dir = os.path.join(self.storage_dir, "chats")
        self._ensure_storage()
        self.index = self._load_or_create_index()
        self.active_chat_id = self.index.get("last_chat_id")
        if not self.active_chat_id:
            chat = self.create_chat(make_active=True)
            self.active_chat_id = chat["id"]
        self._sync_legacy_history()

    def _ensure_storage(self) -> None:
        os.makedirs(self.chats_dir, exist_ok=True)

    def _now(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _default_index(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "last_chat_id": None,
            "global_prompt": "",
            "teaching_memory": "",
            "chats": [],
        }

    def _chat_path(self, chat_id: str) -> str:
        return os.path.join(self.chats_dir, f"{chat_id}.json")

    def _save_json(self, path: str, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)

    def _save_index(self) -> None:
        self._save_json(self.index_file, self.index)

    def _load_json(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _load_or_create_index(self) -> Dict[str, Any]:
        if os.path.exists(self.index_file):
            try:
                data = self._load_json(self.index_file)
                if isinstance(data, dict):
                    data.setdefault("version", 1)
                    data.setdefault("last_chat_id", None)
                    data.setdefault("global_prompt", "")
                    data.setdefault("teaching_memory", "")
                    data.setdefault("chats", [])
                    return data
            except Exception as error:
                print(f"[HISTORY] Error loading chat index: {error}")

        data = self._default_index()
        self._migrate_legacy_history(data)
        self._save_json(self.index_file, data)
        return data

    def _migrate_legacy_history(self, index_data: Dict[str, Any]) -> None:
        if not os.path.exists(self.history_file):
            return

        try:
            legacy = self._load_json(self.history_file)
            user_messages = legacy.get("user", []) if isinstance(legacy, dict) else []
            assistant_messages = legacy.get("assistant", []) if isinstance(legacy, dict) else []
            if not user_messages and not assistant_messages:
                return

            chat_id = uuid.uuid4().hex
            created_at = self._now()
            messages: List[Dict[str, str]] = []

            max_len = max(len(user_messages), len(assistant_messages))
            for index in range(max_len):
                if index < len(user_messages) and user_messages[index]:
                    messages.append({
                        "role": "user",
                        "content": user_messages[index],
                        "created_at": created_at,
                    })
                if index < len(assistant_messages) and assistant_messages[index]:
                    messages.append({
                        "role": "assistant",
                        "content": assistant_messages[index],
                        "created_at": created_at,
                    })

            chat = {
                "id": chat_id,
                "title": "Imported chat",
                "created_at": created_at,
                "updated_at": created_at,
                "custom_prompt": "",
                "messages": messages,
            }
            self._save_json(self._chat_path(chat_id), chat)
            index_data["chats"] = [self._meta_from_chat(chat)]
            index_data["last_chat_id"] = chat_id
        except Exception as error:
            print(f"[HISTORY] Legacy migration failed: {error}")

    def _load_chat(self, chat_id: str) -> Dict[str, Any]:
        path = self._chat_path(chat_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Chat not found: {chat_id}")
        chat = self._load_json(path)
        chat.setdefault("custom_prompt", "")
        chat.setdefault("messages", [])
        return chat

    def _save_chat(self, chat: Dict[str, Any]) -> Dict[str, Any]:
        chat["updated_at"] = self._now()
        self._save_json(self._chat_path(chat["id"]), chat)
        self._upsert_meta(self._meta_from_chat(chat))
        return chat

    def _meta_from_chat(self, chat: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": chat["id"],
            "title": chat.get("title") or DEFAULT_CHAT_TITLE,
            "created_at": chat.get("created_at"),
            "updated_at": chat.get("updated_at"),
            "custom_prompt": chat.get("custom_prompt", ""),
            "message_count": len(chat.get("messages", [])),
            "preview": self._preview_for_chat(chat),
        }

    def _preview_for_chat(self, chat: Dict[str, Any]) -> str:
        for message in reversed(chat.get("messages", [])):
            content = (message.get("content") or "").strip()
            if content:
                return self._shorten(content, 90)
        return "No messages yet."

    def _upsert_meta(self, metadata: Dict[str, Any]) -> None:
        chats = [chat for chat in self.index.get("chats", []) if chat.get("id") != metadata["id"]]
        chats.append(metadata)
        chats.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        self.index["chats"] = chats
        if self.active_chat_id == metadata["id"]:
            self.index["last_chat_id"] = metadata["id"]
        self._save_index()

    def _set_active_chat_id(self, chat_id: str) -> None:
        self.active_chat_id = chat_id
        self.index["last_chat_id"] = chat_id
        self._save_index()
        self._sync_legacy_history(chat_id)

    def _shorten(self, text: str, limit: int = 60) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) <= limit:
            return clean
        return clean[: limit - 1].rstrip() + "…"

    def _derive_title(self, text: str) -> str:
        cleaned = self._shorten(text, 48)
        return cleaned or DEFAULT_CHAT_TITLE

    def _tokenize(self, text: str) -> List[str]:
        return [token for token in re.findall(r"[a-záéíóúñü']+", text.lower()) if len(token) > 2]

    def _sync_legacy_history(self, chat_id: Optional[str] = None) -> None:
        target_chat_id = chat_id or self.active_chat_id
        if not target_chat_id:
            return

        try:
            chat = self._load_chat(target_chat_id)
        except FileNotFoundError:
            return

        payload = {"user": [], "assistant": []}
        for message in chat.get("messages", []):
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                payload["user"].append(content)
            elif role == "assistant":
                payload["assistant"].append(content)

        self._save_json(self.history_file, payload)

    def create_chat(
        self,
        title: Optional[str] = None,
        custom_prompt: str = "",
        make_active: bool = True,
    ) -> Dict[str, Any]:
        timestamp = self._now()
        chat = {
            "id": uuid.uuid4().hex,
            "title": title or DEFAULT_CHAT_TITLE,
            "created_at": timestamp,
            "updated_at": timestamp,
            "custom_prompt": custom_prompt,
            "messages": [],
        }
        self._save_json(self._chat_path(chat["id"]), chat)
        self._upsert_meta(self._meta_from_chat(chat))
        if make_active:
            self._set_active_chat_id(chat["id"])
        return chat

    def list_chats(self) -> List[Dict[str, Any]]:
        return sorted(
            self.index.get("chats", []),
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )

    def get_settings(self) -> Dict[str, str]:
        return {
            "global_prompt": self.index.get("global_prompt", ""),
            "teaching_memory": self.index.get("teaching_memory", ""),
        }

    def update_settings(
        self,
        global_prompt: Optional[str] = None,
        teaching_memory: Optional[str] = None,
    ) -> Dict[str, str]:
        if global_prompt is not None:
            self.index["global_prompt"] = global_prompt.strip()
        if teaching_memory is not None:
            self.index["teaching_memory"] = teaching_memory.strip()
        self._save_index()
        return self.get_settings()

    def get_chat(self, chat_id: Optional[str] = None, touch: bool = False) -> Dict[str, Any]:
        target_chat_id = chat_id or self.active_chat_id
        if not target_chat_id:
            return self.create_chat(make_active=True)

        chat = self._load_chat(target_chat_id)
        if touch:
            self._set_active_chat_id(target_chat_id)
            metadata = self._meta_from_chat(chat)
            self._upsert_meta(metadata)
        return chat

    def set_active_chat(self, chat_id: str) -> Dict[str, Any]:
        chat = self.get_chat(chat_id)
        self._set_active_chat_id(chat_id)
        return chat

    def delete_chat(self, chat_id: str) -> Dict[str, Any]:
        chat_path = self._chat_path(chat_id)
        if not os.path.exists(chat_path):
            raise FileNotFoundError(f"Chat not found: {chat_id}")

        chats = [chat for chat in self.index.get("chats", []) if chat.get("id") != chat_id]
        self.index["chats"] = chats

        try:
            os.remove(chat_path)
        except FileNotFoundError:
            pass

        if self.active_chat_id == chat_id:
            next_chat_id = chats[0]["id"] if chats else None
            if next_chat_id:
                self._set_active_chat_id(next_chat_id)
            else:
                new_chat = self.create_chat(make_active=True)
                next_chat_id = new_chat["id"]
            self.active_chat_id = next_chat_id
        else:
            self._save_index()

        self._sync_legacy_history(self.active_chat_id)
        return self.export_chat_payload(self.active_chat_id)

    def update_chat(
        self,
        chat_id: str,
        title: Optional[str] = None,
        custom_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        chat = self.get_chat(chat_id)
        if title is not None:
            chat["title"] = title.strip() or DEFAULT_CHAT_TITLE
        if custom_prompt is not None:
            chat["custom_prompt"] = custom_prompt.strip()
        saved = self._save_chat(chat)
        if chat_id == self.active_chat_id:
            self._sync_legacy_history(chat_id)
        return saved

    def add_message(self, role: str, content: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"Unsupported role: {role}")

        chat = self.get_chat(chat_id or self.active_chat_id)
        message = {
            "role": role,
            "content": content.strip(),
            "created_at": self._now(),
        }
        if message["content"]:
            chat.setdefault("messages", []).append(message)

        if role == "user" and (not chat.get("title") or chat.get("title") == DEFAULT_CHAT_TITLE):
            chat["title"] = self._derive_title(content)

        saved = self._save_chat(chat)
        self._set_active_chat_id(saved["id"])
        return saved

    def update_conversation(
        self,
        user_input: str,
        assistant_response: str,
        chat_id: Optional[str] = None,
    ) -> None:
        target_chat_id = chat_id or self.active_chat_id
        self.add_message("user", user_input, target_chat_id)
        self.add_message("assistant", assistant_response, target_chat_id)

    def get_recent_messages(
        self,
        max_messages: int = 30,
        chat_id: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        chat = self.get_chat(chat_id)
        return chat.get("messages", [])[-max_messages:]

    def get_recent_history(
        self,
        max_turns: int = 15,
        chat_id: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        messages = self.get_recent_messages(max_messages=max_turns * 2, chat_id=chat_id)
        history = {"user": [], "assistant": []}
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                history["user"].append(content)
            elif role == "assistant":
                history["assistant"].append(content)
        return history

    def export_chat_payload(self, chat_id: Optional[str] = None) -> Dict[str, Any]:
        chat = self.get_chat(chat_id or self.active_chat_id)
        return {
            "id": chat["id"],
            "title": chat.get("title") or DEFAULT_CHAT_TITLE,
            "created_at": chat.get("created_at"),
            "updated_at": chat.get("updated_at"),
            "custom_prompt": chat.get("custom_prompt", ""),
            "messages": chat.get("messages", []),
        }

    def search_chat_snippets(
        self,
        query: str,
        exclude_chat_id: Optional[str] = None,
        max_results: int = 3,
    ) -> List[Dict[str, str]]:
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return []

        matches: List[Dict[str, Any]] = []
        for metadata in self.list_chats():
            chat_id = metadata.get("id")
            if not chat_id or chat_id == exclude_chat_id:
                continue

            try:
                chat = self._load_chat(chat_id)
            except Exception:
                continue

            messages = chat.get("messages", [])
            for index, message in enumerate(messages):
                content = (message.get("content") or "").strip()
                if not content:
                    continue

                content_tokens = set(self._tokenize(content))
                overlap = len(query_tokens & content_tokens)
                if overlap == 0:
                    continue

                paired = []
                for offset in (0, 1):
                    if index + offset < len(messages):
                        nearby = messages[index + offset]
                        role = nearby.get("role", "assistant")
                        label = "User" if role == "user" else "Coach"
                        nearby_text = (nearby.get("content") or "").strip()
                        if nearby_text:
                            paired.append(f"{label}: {self._shorten(nearby_text, 180)}")

                matches.append(
                    {
                        "chat_id": chat_id,
                        "chat_title": chat.get("title") or DEFAULT_CHAT_TITLE,
                        "score": overlap,
                        "updated_at": chat.get("updated_at") or "",
                        "snippet": "\n".join(paired) or self._shorten(content, 180),
                    }
                )

        matches.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)

        deduped: List[Dict[str, str]] = []
        seen = set()
        for item in matches:
            unique_key = (item["chat_id"], item["snippet"])
            if unique_key in seen:
                continue
            seen.add(unique_key)
            deduped.append(
                {
                    "chat_id": item["chat_id"],
                    "chat_title": item["chat_title"],
                    "snippet": item["snippet"],
                }
            )
            if len(deduped) >= max_results:
                break

        return deduped
