from __future__ import annotations

import html
import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
    email_sender: Callable[[PipelineConfig, str, str], None] | None = None,
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
    email_html_body = format_email_html(selected_entries)
    email_sender(config, email_body, email_html_body)
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


def _html_escape(value: str) -> str:
    return html.escape(value or "Not listed")


def _meta_row(label: str, value: str) -> str:
    escaped_value = _html_escape(value)
    return (
        f'<tr>'
        f'<td style="font-size:12px;font-weight:600;color:#5f6368;white-space:nowrap;'
        f'padding:3px 12px 3px 0;vertical-align:top;">{html.escape(label)}</td>'
        f'<td style="font-size:13px;color:#3c4043;padding:3px 0;">{escaped_value}</td>'
        f'</tr>'
    )


def _html_conference_card(index: int, entry: ConferenceEntry) -> str:
    title = html.escape(entry.title)
    url = html.escape(entry.url or "", quote=True)
    title_html = (
        f'<a href="{url}" style="font-size:17px;font-weight:700;color:#1a73e8;'
        f'text-decoration:none;line-height:1.3;">{title}</a>'
        if entry.url else
        f'<span style="font-size:17px;font-weight:700;color:#1a1a2e;line-height:1.3;">{title}</span>'
    )
    reason = html.escape(entry.llm_reason or "Matched your saved preferences.")

    meta_rows = "".join([
        _meta_row("Dates", entry.dates),
        _meta_row("Location", entry.location),
        _meta_row("Registration deadline", entry.registration_deadline),
        _meta_row("Pre-registration deadline", entry.preregistration_deadline),
        _meta_row("Abstract deadline", entry.abstract_deadline),
        _meta_row("Details", entry.details),
    ])

    return (
        f'<tr><td style="padding:0 0 24px 0;">'
        f'<div style="background:#ffffff;border:1px solid #e8eaed;border-radius:10px;'
        f'padding:20px 22px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        f'<div style="font-size:11px;font-weight:700;color:#9aa0a6;letter-spacing:.06em;'
        f'text-transform:uppercase;margin-bottom:6px;">#{index}</div>'
        f'{title_html}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="margin-top:12px;border-collapse:collapse;">{meta_rows}</table>'
        f'<div style="margin-top:14px;background:#f1f8ff;border-left:3px solid #1a73e8;'
        f'border-radius:0 6px 6px 0;padding:10px 14px;">'
        f'<div style="font-size:11px;font-weight:700;color:#1a73e8;letter-spacing:.05em;'
        f'text-transform:uppercase;margin-bottom:4px;">Why it matched</div>'
        f'<div style="font-size:13px;color:#3c4043;line-height:1.5;">{reason}</div>'
        f'</div>'
        f'</div>'
        f'</td></tr>'
    )


def format_email_html(entries: list[ConferenceEntry]) -> str:
    _today = date.today()
    today = _today.strftime("%A, %B ") + str(_today.day) + _today.strftime(", %Y")

    if not entries:
        body_content = (
            '<tr><td style="padding:20px 0;">'
            '<div style="background:#f1f8ff;border:1px solid #c8e6fa;border-radius:10px;'
            'padding:28px 24px;text-align:center;">'
            '<div style="font-size:32px;margin-bottom:10px;">📭</div>'
            '<div style="font-size:16px;font-weight:600;color:#3c4043;margin-bottom:6px;">'
            'No new conferences this week</div>'
            '<div style="font-size:14px;color:#5f6368;">'
            'There are no new conferences to be aware of at this time.</div>'
            '</div>'
            '</td></tr>'
        )
    else:
        n = len(entries)
        plural = "conference" if n == 1 else "conferences"
        intro = (
            f'<tr><td style="padding:0 0 20px 0;">'
            f'<p style="font-size:15px;color:#3c4043;margin:0;">'
            f'<strong>{n}</strong> {plural} matched your preferences this week.</p>'
            f'</td></tr>'
        )
        cards = "".join(_html_conference_card(i, e) for i, e in enumerate(entries, start=1))
        body_content = intro + cards

    return f"""\
<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#f4f5f7;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f5f7;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="620" cellpadding="0" cellspacing="0"
             style="max-width:620px;width:100%;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                    Roboto,Helvetica,Arial,sans-serif;">
        <!-- Header -->
        <tr><td style="background:#1a1a2e;padding:28px 32px;border-radius:12px 12px 0 0;">
          <div style="font-size:22px;font-weight:700;color:#ffffff;">
            📅 Conference Digest</div>
          <div style="font-size:14px;color:#b8b8d0;margin-top:6px;">{today}</div>
        </td></tr>
        <!-- Body -->
        <tr><td style="background:#f8f9fa;padding:28px 28px 8px 28px;">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                 style="border-collapse:collapse;">
            {body_content}
          </table>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:#f8f9fa;padding:16px 28px 28px 28px;
                        border-top:1px solid #e8eaed;border-radius:0 0 12px 12px;">
          <p style="font-size:12px;color:#9aa0a6;margin:0;line-height:1.6;">
            Sent by <strong>conference_fetcher</strong>.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(config: PipelineConfig, text_body: str, html_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = "Weekly conference digest"
    message["From"] = config.smtp_from
    message["To"] = config.smtp_to
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    if config.smtp_starttls:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
