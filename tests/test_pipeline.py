import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from conference_fetcher.llm import GitHubModelsLLMClient, LLMClient, create_llm_client_from_env
from conference_fetcher.scraper import parse_recent_meetings
from conference_fetcher.pipeline import PipelineConfig, format_email, read_cache, run_pipeline


class StaticLLMClient(LLMClient):
    def __init__(self, selected_titles: set[str]) -> None:
        self.selected_titles = selected_titles

    def select_conferences(self, entries, preferences):
        return [
            type(entry)(**{**entry.__dict__, "llm_reason": "Matches astronomy preferences"})
            for entry in entries
            if entry.title in self.selected_titles
        ]


class PipelineTests(unittest.TestCase):
    def test_create_llm_client_uses_github_models_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "token", "GITHUB_MODEL": "openai/gpt-4.1-mini"},
            clear=True,
        ):
            client = create_llm_client_from_env()

        self.assertIsInstance(client, GitHubModelsLLMClient)
        self.assertEqual(client.model, "openai/gpt-4.1-mini")

    def test_run_pipeline_sends_selected_entries_and_updates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "preferences.md").write_text("- astronomy conferences in Canada\n", encoding="utf-8")
            config = PipelineConfig(
                repo_root=root,
                preferences_path=root / "preferences.md",
                cache_path=root / "cache.md",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="user",
                smtp_password="pass",
                smtp_from="from@example.com",
                smtp_to="to@example.com",
            )
            html = """
            <article>
              <h2>Astro AI Summit 2026</h2>
              <p>Conference dates: July 10-12, 2026</p>
              <p>Location: Montreal, Canada</p>
              <p>Registration deadline: May 20, 2026</p>
              <p>Pre-registration deadline: May 1, 2026</p>
              <p>Abstract submission deadline: April 15, 2026</p>
            </article>
            <article>
              <h2>Quantum Networking Workshop</h2>
              <p>Dates: August 2-5, 2026</p>
              <p>Location: Berlin, Germany</p>
            </article>
            """
            sent_messages = []

            def fake_sender(_config, body):
                sent_messages.append(body)

            selected = run_pipeline(
                config=config,
                llm_client=StaticLLMClient({"Astro AI Summit 2026"}),
                fetch_html=lambda: html,
                email_sender=fake_sender,
                now=datetime(2026, 5, 8, tzinfo=timezone.utc),
            )

            self.assertEqual([entry.title for entry in selected], ["Astro AI Summit 2026"])
            self.assertEqual(len(sent_messages), 1)
            self.assertIn("Astro AI Summit 2026", sent_messages[0])
            self.assertNotIn("Quantum Networking Workshop", sent_messages[0])
            self.assertEqual(len(read_cache(config.cache_path)), 1)

    def test_run_pipeline_sends_friendly_message_when_everything_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "preferences.md").write_text("- anything\n", encoding="utf-8")
            cache_path = root / "cache.md"
            html = """
            <article>
              <h2>Astro AI Summit 2026</h2>
              <p>Conference dates: July 10-12, 2026</p>
              <p>Location: Montreal, Canada</p>
            </article>
            """
            entry = parse_recent_meetings(html)[0]
            cache_path.write_text(
                "# Conference notification cache\n\nConferences listed here have already been included in an email notification.\n\n"
                f"- `{entry.cache_key}` | Astro AI Summit 2026 | July 10-12, 2026 | Montreal, Canada | notified 2026-05-01\n",
                encoding="utf-8",
            )
            config = PipelineConfig(
                repo_root=root,
                preferences_path=root / "preferences.md",
                cache_path=cache_path,
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="user",
                smtp_password="pass",
                smtp_from="from@example.com",
                smtp_to="to@example.com",
            )
            sent_messages = []

            run_pipeline(
                config=config,
                llm_client=StaticLLMClient({"Astro AI Summit 2026"}),
                fetch_html=lambda: html,
                email_sender=lambda _config, body: sent_messages.append(body),
                now=datetime(2026, 5, 8, tzinfo=timezone.utc),
            )

            self.assertEqual(len(sent_messages), 1)
            self.assertIn("There are no new conferences", sent_messages[0])

    def test_format_email_uses_fallback_text_for_missing_fields(self) -> None:
        body = format_email([])
        self.assertIn("There are no new conferences", body)
