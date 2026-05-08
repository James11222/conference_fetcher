from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import replace

from .models import ConferenceEntry


class LLMClient:
    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        raise NotImplementedError


class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-latest") -> None:
        self.api_key = api_key
        self.model = model

    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        payload = {
            "model": self.model,
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": _build_prompt(entries, preferences)}],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = "".join(part.get("text", "") for part in body.get("content", []))
        return _selected_entries_from_response(entries, text)


class GitHubModelsLLMClient(LLMClient):
    def __init__(self, token: str, model: str = "gpt-4o-mini") -> None:
        self.token = token
        self.model = model

    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": _build_prompt(entries, preferences)}],
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            "https://models.inference.ai.azure.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"]
        return _selected_entries_from_response(entries, text)


def create_llm_client_from_env() -> LLMClient:
    backend = os.environ.get("LLM_BACKEND", "anthropic").strip().lower()
    if backend == "anthropic":
        api_key = os.environ["ANTHROPIC_API_KEY"]
        return AnthropicLLMClient(api_key, os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"))
    if backend in {"github", "copilot", "github_models"}:
        token = os.environ["GITHUB_TOKEN"]
        return GitHubModelsLLMClient(token, os.environ.get("GITHUB_MODEL", "gpt-4o-mini"))
    raise ValueError("LLM_BACKEND must be one of: anthropic, github, copilot, github_models")


def _build_prompt(entries: list[ConferenceEntry], preferences: str) -> str:
    serializable_entries = [
        {
            "id": entry.cache_key,
            "title": entry.title,
            "dates": entry.dates,
            "location": entry.location,
            "registration_deadline": entry.registration_deadline,
            "preregistration_deadline": entry.preregistration_deadline,
            "abstract_deadline": entry.abstract_deadline,
            "details": entry.details,
            "url": entry.url,
        }
        for entry in entries
    ]
    return (
        "You are helping shortlist academic conference announcements.\n"
        "Read the user preferences and decide which conferences should be emailed.\n"
        "Only include entries that are a strong match.\n"
        "Return JSON with this exact schema:\n"
        '{"selected":[{"id":"<conference-id>","reason":"<short reason>"}]}\n\n'
        f"User preferences (markdown):\n{preferences}\n\n"
        f"Conference entries (JSON):\n{json.dumps(serializable_entries, indent=2)}"
    )


def _selected_entries_from_response(entries: list[ConferenceEntry], response_text: str) -> list[ConferenceEntry]:
    data = _extract_json_object(response_text)
    reasons = {item["id"]: item.get("reason", "") for item in data.get("selected", [])}
    entries_by_id = {entry.cache_key: entry for entry in entries}
    selected: list[ConferenceEntry] = []
    for entry_id, reason in reasons.items():
        entry = entries_by_id.get(entry_id)
        if entry:
            selected.append(replace(entry, llm_reason=reason.strip()))
    return selected


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])
