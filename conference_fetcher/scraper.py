from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Iterable

from .models import ConferenceEntry

RECENT_MEETINGS_URL = "https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/meetings/recent/"

_FIELD_PATTERNS = {
    "dates": [
        r"conference dates?",
        r"meeting dates?",
        r"event dates?",
        r"dates?",
    ],
    "location": [r"conference location", r"location", r"venue", r"place"],
    "registration_deadline": [
        r"registration deadline",
        r"registration closes?",
        r"registration due",
    ],
    "preregistration_deadline": [
        r"pre[- ]registration deadline",
        r"pre[- ]registration closes?",
        r"pre[- ]registration due",
    ],
    "abstract_deadline": [
        r"abstract submission deadline",
        r"abstract deadline",
        r"submission deadline",
    ],
}
_ALL_FIELD_LABELS = sorted(
    {label for labels in _FIELD_PATTERNS.values() for label in labels},
    key=len,
    reverse=True,
)


class _MeetingListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, str | list[str]]] = []
        self._current: dict[str, str | list[str]] | None = None
        self._heading_level: int | None = None
        self._text_parts: list[str] = []
        self._heading_parts: list[str] = []
        self._link_href: str | None = None
        self._link_parts: list[str] = []
        self._in_item = 0
        # <details>/<summary> support
        self._details_depth: int = 0
        self._in_summary: bool = False
        self._summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        classes = attrs_dict.get("class", "")
        if tag == "details":
            # Each <details> element is a conference entry on the CADC page.
            if self._details_depth == 0:
                self._start_item()
            self._details_depth += 1
        elif tag in {"article"} or any(
            marker in classes.lower()
            for marker in ("views-row", "meeting", "conference", "node", "item", "list-group-item")
        ):
            self._start_item()
        if tag == "summary" and self._details_depth > 0 and self._current is not None:
            self._in_summary = True
            self._summary_parts = []
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._heading_parts = []
        if tag == "a":
            self._link_href = attrs_dict.get("href")
            self._link_parts = []
        if tag in {"br", "p", "div", "li", "dt", "dd"} and self._current is not None:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "summary" and self._in_summary:
            self._in_summary = False
            title = _clean_text("".join(self._summary_parts))
            if self._current is not None and title:
                self._current["title"] = title
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading_level is not None:
            heading = _clean_text("".join(self._heading_parts))
            self._heading_level = None
            # Only use headings to name entries when we are inside a non-details
            # container (e.g. <article>). Headings outside any container are
            # page-level navigation and should not generate entries.
            if heading and self._current is not None and self._details_depth == 0:
                self._finish_current_if_heading_starts_new_item(heading)
        if tag == "a" and self._link_href:
            link_text = _clean_text("".join(self._link_parts))
            if self._current is not None and not self._current.get("url") and link_text:
                self._current["url"] = self._link_href
            self._link_href = None
            self._link_parts = []
        if tag == "details":
            self._details_depth = max(0, self._details_depth - 1)
            if self._details_depth == 0 and self._current is not None:
                self._finalize_current()
        elif tag == "article" and self._current is not None:
            self._finalize_current()

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self._in_summary:
            self._summary_parts.append(data)
            # Also accumulate for link capture so linked summaries get URL recorded.
            if self._link_href is not None:
                self._link_parts.append(data)
            return
        if self._heading_level is not None:
            self._heading_parts.append(data)
        if self._link_href is not None:
            self._link_parts.append(data)
        if self._current is not None:
            self._text_parts.append(data)

    def close(self) -> None:
        super().close()
        self._finalize_current()

    def _start_item(self) -> None:
        if self._current is None:
            self._current = {"title": "", "url": "", "body": []}
            self._text_parts = []
            self._in_item += 1

    def _finish_current_if_heading_starts_new_item(self, heading: str) -> None:
        generic = heading.lower() in {"recent meetings", "meetings", "recent conferences"}
        if generic:
            return
        current_title = str(self._current.get("title", "")).strip() if self._current else ""
        if current_title:
            self._finalize_current()
            self._start_item()
        if self._current is not None:
            self._current["title"] = heading

    def _finalize_current(self) -> None:
        if self._current is None:
            return
        body = _clean_multiline_text("".join(self._text_parts))
        self._current["body"] = body
        title = str(self._current.get("title", "")).strip()
        if title:
            self.blocks.append(self._current)
        self._current = None
        self._text_parts = []
        self._in_item = 0


def fetch_recent_meetings(opener) -> str:
    with opener(RECENT_MEETINGS_URL, timeout=60) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_recent_meetings(html: str) -> list[ConferenceEntry]:
    parser = _MeetingListParser()
    parser.feed(html)
    parser.close()
    return [entry for entry in (_build_entry(block) for block in parser.blocks) if entry]


def _build_entry(block: dict[str, str | list[str]]) -> ConferenceEntry | None:
    title = _clean_text(str(block.get("title", "")))
    body = _clean_text(str(block.get("body", "")))
    if not title or title.lower() in {"recent meetings", "meetings", "recent conferences"}:
        return None
    return ConferenceEntry(
        title=title,
        dates=_extract_field(body, _FIELD_PATTERNS["dates"]),
        location=_extract_field(body, _FIELD_PATTERNS["location"]),
        registration_deadline=_extract_field(body, _FIELD_PATTERNS["registration_deadline"]),
        preregistration_deadline=_extract_field(body, _FIELD_PATTERNS["preregistration_deadline"]),
        abstract_deadline=_extract_field(body, _FIELD_PATTERNS["abstract_deadline"]),
        details=body,
        url=_normalize_url(str(block.get("url", ""))),
    )


def _extract_field(text: str, labels: Iterable[str]) -> str:
    next_labels = "|".join(_ALL_FIELD_LABELS)
    for label in labels:
        match = re.search(
            rf"(?is)\b(?:{label})\b\s*[:\-]\s*(.+?)(?=\s+\b(?:{next_labels})\b\s*[:\-]|$)",
            text,
        )
        if match:
            return _clean_text(match.group(1))
    return ""


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca{url}"


def _clean_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return value


def _clean_multiline_text(value: str) -> str:
    lines = [_clean_text(line) for line in unescape(value).splitlines()]
    return "\n".join(line for line in lines if line)
