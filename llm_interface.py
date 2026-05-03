import asyncio
import json
import re
from typing import Dict, List, Optional, Tuple, Union

import requests

from config import CONVERSATION_CONTEXT
from provider_manager import ProviderManager


class LLMInterface:
    def __init__(self, conversation_manager, provider_manager: ProviderManager):
        self.conversation_manager = conversation_manager
        self.provider_manager = provider_manager
        self.base_system_prompt = CONVERSATION_CONTEXT

    async def ask_llm(
        self,
        query: str,
        chat_id: Optional[str] = None,
        return_metadata: bool = False,
    ) -> Union[str, Dict[str, Union[str, List[Dict[str, str]]]]]:
        print(f"[LLM] Processing query: {query}")
        context_snippets = self.conversation_manager.search_chat_snippets(
            query,
            exclude_chat_id=chat_id,
            max_results=3,
        )
        plan_data = await self._get_internet_plan(query)

        if plan_data.get("internet") == "yes" and plan_data.get("search_query"):
            print("[LLM] Using model with internet context")
            response = await self._get_internet_enhanced_response(
                query,
                plan_data["search_query"],
                chat_id=chat_id,
                context_snippets=context_snippets,
            )
        else:
            print("[LLM] Using active provider")
            response = await self._get_offline_response(
                query,
                chat_id=chat_id,
                context_snippets=context_snippets,
            )

        if return_metadata:
            return {"response": response, "memory_snippets": context_snippets}
        return response

    def _build_system_prompt(self, chat_id: Optional[str] = None) -> str:
        settings = self.conversation_manager.get_settings()
        chat = self.conversation_manager.get_chat(chat_id) if chat_id else self.conversation_manager.get_chat()

        parts = [self.base_system_prompt]

        teaching_memory = (settings.get("teaching_memory") or "").strip()
        if teaching_memory:
            parts.append(
                "Long-term teaching memory about this learner. Use it when it helps keep continuity over time:\n"
                f"{teaching_memory}"
            )

        global_prompt = (settings.get("global_prompt") or "").strip()
        if global_prompt:
            parts.append(f"Global UI instructions:\n{global_prompt}")

        custom_prompt = (chat.get("custom_prompt") or "").strip()
        if custom_prompt:
            parts.append(f"Chat-specific instructions:\n{custom_prompt}")

        return "\n\n".join(parts)

    def _build_messages(
        self,
        query: str,
        chat_id: Optional[str],
        context_snippets: List[Dict[str, str]],
        extra_system_context: str = "",
    ) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self._build_system_prompt(chat_id)}]

        if context_snippets:
            memory_lines = [
                "Relevant snippets from other chats. Use them as soft memory, not as strict facts if they conflict with the current conversation:",
            ]
            for snippet in context_snippets:
                memory_lines.append(f"- Chat '{snippet['chat_title']}': {snippet['snippet']}")
            messages.append({"role": "system", "content": "\n".join(memory_lines)})

        if extra_system_context:
            messages.append({"role": "system", "content": extra_system_context})

        for message in self.conversation_manager.get_recent_messages(max_messages=30, chat_id=chat_id):
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": query})
        return messages

    async def _get_internet_plan(self, query: str) -> Dict[str, str]:
        try:
            normalized = query.lower().strip()
            internet_keywords = [
                "weather", "news", "headline", "latest", "current", "today", "now",
                "stock", "price", "score", "scores", "result", "results",
                "search the web", "look it up", "internet", "online", "web",
            ]

            needs_internet = any(keyword in normalized for keyword in internet_keywords)
            plan_data = {
                "internet": "yes" if needs_internet else "no",
                "search_query": query if needs_internet else "",
            }
            print(f"[Plan Agent] Heuristic plan: {plan_data}")
            return plan_data
        except Exception as error:
            print(f"[LLM] Error determining internet plan: {error}")
            return {"internet": "no", "search_query": ""}

    async def _get_internet_enhanced_response(
        self,
        query: str,
        search_query: str,
        chat_id: Optional[str],
        context_snippets: List[Dict[str, str]],
    ) -> str:
        try:
            method = None
            summary = None
            url = None
            extra_context = ""
            loop = asyncio.get_event_loop()
            search_url = f"http://localhost:8080/search?q={search_query}&format=json"

            print(f"[LLM] Fetching real-time data for: {search_query}")

            try:
                search_response = await loop.run_in_executor(None, requests.get, search_url)

                if search_response.status_code == 200:
                    raw_text = search_response.text.strip()
                    if raw_text in ['"query"', 'query']:
                        search_results = {}
                    else:
                        try:
                            search_results = json.loads(raw_text)
                            if isinstance(search_results, str):
                                search_results = {}
                        except Exception:
                            search_results = {}

                    if "answers" in search_results and search_results["answers"]:
                        summary = search_results["answers"][0]
                        method = "answers"
                        print(f"[LLM] Answer Found: {summary}")
                    elif (
                        "results" in search_results
                        and isinstance(search_results["results"], list)
                        and len(search_results["results"]) > 0
                    ):
                        first_result = search_results["results"][0]
                        if isinstance(first_result, dict) and "url" in first_result:
                            url = first_result["url"]
                            method = "onlineagent"
                            print(f"[LLM] Using URL from results: {url}")
                        else:
                            print("[LLM] Search result does not contain a valid URL.")
                    else:
                        print("[LLM] No usable search results found.")
            except Exception as error:
                print(f"[LLM] Error fetching search results: {error}")

            if method == "answers":
                extra_context = f"Additional internet data for the next reply: {summary}"

            if method == "onlineagent" and url:
                webpage_context = await loop.run_in_executor(None, self._fetch_webpage_context, url)
                if webpage_context:
                    extra_context = (
                        f"Use this webpage extract as supporting context. Source URL: {url}\n\n{webpage_context}"
                    )

            return await self._get_offline_response(query, chat_id, context_snippets, extra_system_context=extra_context)
        except Exception as error:
            print(f"[LLM] Error getting internet-enhanced response: {error}")
            return "Sorry, I'm having trouble retrieving information from the internet right now."

    async def _get_offline_response(
        self,
        query: str,
        chat_id: Optional[str],
        context_snippets: List[Dict[str, str]],
        extra_system_context: str = "",
    ) -> str:
        try:
            messages = self._build_messages(query, chat_id, context_snippets, extra_system_context=extra_system_context)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self.provider_manager.chat(messages))
        except Exception as error:
            print(f"[LLM] Error getting offline response: {error}")
            return "I'm having trouble processing your request right now."

    def _fetch_webpage_context(self, url: str) -> str:
        response = requests.get(url, timeout=12, headers={"User-Agent": "english-coach/1.0"})
        response.raise_for_status()
        html = response.text
        html = re.sub(r"<script.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<style.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:5000]

    def update_conversation(
        self,
        user_input: str,
        assistant_response: str,
        chat_id: Optional[str] = None,
    ) -> None:
        self.conversation_manager.update_conversation(user_input, assistant_response, chat_id=chat_id)
