from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from .llm import LLMClient, create_llm_client_from_env
from .models import ConferenceEntry
from .scraper import fetch_recent_meetings, parse_recent_meetings


@dataclass(frozen=True)
class PipelineConfig:
    repo_root: Path
    preferences_path: Path
    cache_path: Path
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: str
    smtp_starttls: bool = True

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "PipelineConfig":
        base = (repo_root or Path(os.environ.get("REPO_ROOT", Path.cwd()))).resolve()
        return cls(
            repo_root=base,
            preferences_path=base / "preferences.md",
            cache_path=base / "cache.md",
            smtp_host=os.environ["SMTP_HOST"],
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_username=os.environ["SMTP_USERNAME"],
            smtp_password=os.environ["SMTP_PASSWORD"],
            smtp_from=os.environ["SMTP_FROM"],
            smtp_to=os.environ["SMTP_TO"],
            smtp_starttls=os.environ.get("SMTP_STARTTLS", "true").lower() != "false",
        )


def run_pipeline(
    config: PipelineConfig | None = None,
    llm_client: LLMClient | None = None,
    fetch_data: Callable[[], list] | None = None,
    email_sender: Callable[[PipelineConfig, str], None] | None = None,
    now: datetime | None = None,
) -> list[ConferenceEntry]:
    config = config or PipelineConfig.from_env()
    llm_client = llm_client or create_llm_client_from_env()
    fetch_data = fetch_data or fetch_recent_meetings
    email_sender = email_sender or send_email
    current_time = now or datetime.now(timezone.utc)

    preferences = config.preferences_path.read_text(encoding="utf-8")
    data = fetch_data()
    parsed_entries = parse_recent_meetings(data)
    cached_ids = read_cache(config.cache_path)
    unseen_entries = [entry for entry in parsed_entries if entry.cache_key not in cached_ids]
    print("Pre-LLM sort: ")
    print(unseen_entries)
    selected_entries = llm_client.select_conferences(unseen_entries, preferences) if unseen_entries else []
    if selected_entries:
        # show that the entries were successfully found
        print(selected_entries)
        write_cache(config.cache_path, cached_ids | {entry.cache_key for entry in selected_entries}, selected_entries, current_time)
    elif not config.cache_path.exists():
        write_cache(config.cache_path, cached_ids, [], current_time)
    email_body = format_email(selected_entries)
    email_sender(config, email_body)
    return selected_entries


def read_cache(cache_path: Path) -> set[str]:
    if not cache_path.exists():
        return set()
    cached_ids: set[str] = set()
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- `") and "`" in line[3:]:
            cached_ids.add(line.split("`", 2)[1])
    return cached_ids


def write_cache(cache_path: Path, cached_ids: set[str], entries: list[ConferenceEntry], now: datetime) -> None:
    existing_lines: dict[str, str] = {}
    if cache_path.exists():
        existing_lines = {
            line.split("`", 2)[1]: line
            for line in cache_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("- `") and "`" in line[3:]
        }
    for entry in entries:
        existing_lines[entry.cache_key] = (
            f"- `{entry.cache_key}` | {entry.title} | {entry.dates or 'date TBD'} | "
            f"{entry.location or 'location TBD'} | notified {now.date().isoformat()}"
        )
    header = [
        "# Conference notification cache",
        "",
        "Conferences listed here have already been included in an email notification.",
        "",
    ]
    body = [existing_lines[key] for key in sorted(cached_ids) if key in existing_lines]
    cache_path.write_text("\n".join(header + body).rstrip() + "\n", encoding="utf-8")


def format_email(entries: list[ConferenceEntry]) -> str:
    if not entries:
        return (
            "Hello,\n\n"
            "There are no new conferences to be aware of at this time.\n\n"
            "Best,\nconference_fetcher"
        )
    sections = ["Hello,", "", "Here are the new conferences that matched your preferences:", ""]
    for entry in entries:
        sections.extend(
            [
                f"Title: {entry.title}",
                f"Conference date(s): {entry.dates or 'Not listed'}",
                f"Conference location: {entry.location or 'Not listed'}",
                f"Registration deadline: {entry.registration_deadline or 'Not listed'}",
                f"Pre-registration deadline: {entry.preregistration_deadline or 'Not listed'}",
                f"Abstract submission deadline: {entry.abstract_deadline or 'Not listed'}",
                f"Details: {entry.details or 'Not listed'}",
                f"Link: {entry.url or 'Not listed'}",
                f"Why it matched: {entry.llm_reason or 'Matched your saved preferences.'}",
                "",
            ]
        )
    sections.extend(["Best,", "conference_fetcher"])
    return "\n".join(sections)


def send_email(config: PipelineConfig, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Weekly conference digest"
    message["From"] = config.smtp_from
    message["To"] = config.smtp_to
    message.set_content(body)
    if config.smtp_starttls:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
