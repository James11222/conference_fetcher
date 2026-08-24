from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import replace

from .models import ConferenceEntry

_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
_EDITOR_VERSION = "vscode/1.107.0"
_USER_AGENT = "GitHubCopilotChat/0.35.0"
_EDITOR_PLUGIN_VERSION = "copilot-chat/0.35.0"
_COPILOT_INTEGRATION_ID = "vscode-chat"


class LLMClient:
    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        raise NotImplementedError


class GitHubCopilotLLMClient(LLMClient):
    def __init__(self, token: str, model: str = "gpt-5-mini") -> None:
        self.token = token
        self.model = model

    def _get_copilot_token(self) -> str:
        request = urllib.request.Request(
            _COPILOT_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token,
                "Editor-Version": _EDITOR_VERSION,
                "Editor-Plugin-Version": _EDITOR_PLUGIN_VERSION,
                "User-Agent": _USER_AGENT,
                "Copilot-Integration-Id": _COPILOT_INTEGRATION_ID,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise RuntimeError(
                    "GitHub Copilot token exchange was unauthorized. "
                    "Ensure the token has copilot-requests:write access."
                ) from error
            if error.code == 404:
                # The token exchange endpoint is not available for this token type
                # (e.g. GitHub Actions GITHUB_TOKEN). Fall back to using the token directly.
                return self.token
            raise
        except json.JSONDecodeError as error:
            raise RuntimeError("Copilot token exchange returned invalid JSON.") from error
        copilot_token = str(body.get("token") or "").strip()
        if not copilot_token:
            raise RuntimeError("Copilot token exchange returned an empty token.")
        return copilot_token

    def select_conferences(self, entries: list[ConferenceEntry], preferences: str) -> list[ConferenceEntry]:
        copilot_token = self._get_copilot_token()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": _build_prompt(entries, preferences)}],
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            _COPILOT_CHAT_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer " + copilot_token,
                "Editor-Version": _EDITOR_VERSION,
                "Editor-Plugin-Version": _EDITOR_PLUGIN_VERSION,
                "User-Agent": _USER_AGENT,
                "Copilot-Integration-Id": _COPILOT_INTEGRATION_ID,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise RuntimeError(
                    "GitHub Copilot request was unauthorized. "
                    "Ensure the token has copilot-requests:write access."
                ) from error
            if error.code == 400:
                body = error.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"GitHub Copilot request was rejected (HTTP 400). "
                    f"The model '{self.model}' may be invalid or unsupported. "
                    f"Response: {body}"
                ) from error
            raise
        text = body["choices"][0]["message"]["content"]
        return _selected_entries_from_response(entries, text)


# Keep the old name as an alias for backwards compatibility.
GitHubModelsLLMClient = GitHubCopilotLLMClient


def create_llm_client_from_env() -> LLMClient:
    token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise ValueError("Set GH_TOKEN before running the pipeline.")
    model = (os.environ.get("GH_MODEL") or "gpt-5-mini").strip()
    return GitHubCopilotLLMClient(token, model)


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
