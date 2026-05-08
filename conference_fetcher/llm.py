from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import replace

from .models import ConferenceEntry


class LLMClient:
    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        raise NotImplementedError


class GitHubModelsLLMClient(LLMClient):
    def __init__(self, token: str, model: str = "openai/gpt-4.1") -> None:
        self.token = token
        self.model = model

    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": _build_prompt(entries, preferences)}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "accept": "application/vnd.github+json",
                "content-type": "application/json",
                "authorization": f"Bearer {self.token}",
                "x-github-api-version": "2022-11-28",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise RuntimeError(
                    "GitHub Models request was unauthorized. Ensure the token has models:read access."
                ) from error
            raise
        text = body["choices"][0]["message"]["content"]
        return _selected_entries_from_response(entries, text)


def create_llm_client_from_env() -> LLMClient:
    token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise ValueError("Set GH_TOKEN before running the pipeline.")
    model = (os.environ.get("GH_MODEL") or "openai/gpt-4.1").strip()
    return GitHubModelsLLMClient(token, model)


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
        stripped = stripped.lstrip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
        stripped = stripped.rstrip("`").rstrip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])
