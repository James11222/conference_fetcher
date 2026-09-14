from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from html import unescape

import requests

from .models import ConferenceEntry

MEETINGS_API_URL = "https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/meetings/meetings?days=21"
JSONData = dict[str, object] | list[object] | str | int | float | bool | None


def fetch_recent_meetings() -> JSONData:
    response = requests.get(MEETINGS_API_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_recent_meetings(data: JSONData) -> list[ConferenceEntry]:
    meetings = _extract_meetings(data)
    return [entry for entry in (_build_entry(meeting) for meeting in meetings) if entry]


def _extract_meetings(data: object) -> list[Mapping[str, object]]:
    if isinstance(data, Mapping):
        if any(key in data for key in ("title", "start", "end", "location", "web1", "web2")):
            return [data]
        preferred_keys = ("meetings", "results", "items", "data")
        for key in preferred_keys:
            value = data.get(key)
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
                raw_items = list(value)
                if raw_items:
                    return [meeting for meeting in raw_items if isinstance(meeting, Mapping)]
        for key, value in data.items():
            if key not in preferred_keys and isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
                meetings = [meeting for meeting in value if isinstance(meeting, Mapping)]
                if meetings:
                    return meetings
        return []
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
        return [meeting for meeting in data if isinstance(meeting, Mapping)]
    return []


def _build_entry(meeting: Mapping[str, object]) -> ConferenceEntry | None:
    title = _clean_text(meeting.get("title") or "")
    if not title:
        return None

    start = meeting.get("start") or ""
    end = meeting.get("end") or ""
    dates = f"{start} to {end}" if start and end else start or end

    location = _clean_text(meeting.get("location") or "")
    url = meeting.get("web1") or meeting.get("web2") or ""

    contact = _clean_text(meeting.get("contact") or "")
    email = meeting.get("email") or ""
    keywords = _clean_text(meeting.get("keywords") or "")

    details_parts = []
    if contact:
        details_parts.append(f"Contact: {contact}")
    if email:
        details_parts.append(f"Email: {email}")
    if keywords:
        details_parts.append(f"Keywords: {keywords}")
    details = "\n".join(details_parts)

    return ConferenceEntry(
        title=title,
        dates=dates,
        location=location,
        url=url,
        details=details,
    )


def _clean_text(value: object) -> str:
    value = unescape("" if value is None else str(value))
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return value
