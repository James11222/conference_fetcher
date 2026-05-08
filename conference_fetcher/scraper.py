from __future__ import annotations

import re
from html import unescape

import requests

from .models import ConferenceEntry

MEETINGS_API_URL = "https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/meetings/meetings?days=21"


def fetch_recent_meetings() -> list[dict]:
    response = requests.get(MEETINGS_API_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_recent_meetings(data: list[dict]) -> list[ConferenceEntry]:
    return [entry for entry in (_build_entry(meeting) for meeting in data) if entry]


def _build_entry(meeting: dict) -> ConferenceEntry | None:
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


def _clean_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return value
