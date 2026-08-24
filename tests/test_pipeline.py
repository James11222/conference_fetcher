import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from conference_fetcher.llm import GitHubCopilotLLMClient, GitHubModelsLLMClient, LLMClient, create_llm_client_from_env
from conference_fetcher.scraper import parse_recent_meetings
from conference_fetcher.pipeline import PipelineConfig, format_email, format_email_html, read_cache, run_pipeline


class StaticLLMClient(LLMClient):
    def __init__(self, selected_titles: set[str]) -> None:
        self.selected_titles = selected_titles

    def select_conferences(self, entries, preferences):
        return [
            type(entry)(**{**entry.__dict__, "llm_reason": "Matches astronomy preferences"})
            for entry in entries
            if entry.title in self.selected_titles
        ]


class FailingLLMClient(LLMClient):
    def select_conferences(self, entries, preferences):
        raise RuntimeError("GitHub Copilot request was rejected (HTTP 404).")


class PipelineTests(unittest.TestCase):
    def test_create_llm_client_uses_github_copilot_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {"GH_TOKEN": "token", "GH_MODEL": "gpt-4.1-mini"},
            clear=True,
        ):
            client = create_llm_client_from_env()

        self.assertIsInstance(client, GitHubCopilotLLMClient)
        self.assertEqual(client.model, "gpt-4.1-mini")

    def test_github_models_llm_client_is_alias(self) -> None:
        self.assertIs(GitHubModelsLLMClient, GitHubCopilotLLMClient)

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
            json_data = [
                {
                    "title": "Astro AI Summit 2026",
                    "start": "2026-07-10",
                    "end": "2026-07-12",
                    "location": "Montreal, Canada",
                    "web1": "https://example.com/astro-ai-2026",
                    "web2": "",
                    "contact": "Jane Smith",
                    "email": "jane@example.com",
                    "keywords": "",
                },
                {
                    "title": "Quantum Networking Workshop",
                    "start": "2026-08-02",
                    "end": "2026-08-05",
                    "location": "Berlin, Germany",
                    "web1": "",
                    "web2": "",
                    "contact": "",
                    "email": "",
                    "keywords": "",
                },
            ]
            sent_messages = []

            def fake_sender(_config, text_body, html_body):
                sent_messages.append((text_body, html_body))

            selected = run_pipeline(
                config=config,
                llm_client=StaticLLMClient({"Astro AI Summit 2026"}),
                fetch_data=lambda: json_data,
                email_sender=fake_sender,
                now=datetime(2026, 5, 8, tzinfo=timezone.utc),
            )

            self.assertEqual([entry.title for entry in selected], ["Astro AI Summit 2026"])
            self.assertEqual(len(sent_messages), 1)
            text_body, html_body = sent_messages[0]
            self.assertIn("Astro AI Summit 2026", text_body)
            self.assertNotIn("Quantum Networking Workshop", text_body)
            self.assertIn("Astro AI Summit 2026", html_body)
            self.assertNotIn("Quantum Networking Workshop", html_body)
            self.assertIn("<!DOCTYPE html>", html_body)
            self.assertIn("Conference Digest", html_body)
            self.assertEqual(len(read_cache(config.cache_path)), 1)

    def test_run_pipeline_sends_friendly_message_when_everything_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "preferences.md").write_text("- anything\n", encoding="utf-8")
            cache_path = root / "cache.md"
            json_data = [
                {
                    "title": "Astro AI Summit 2026",
                    "start": "2026-07-10",
                    "end": "2026-07-12",
                    "location": "Montreal, Canada",
                    "web1": "",
                    "web2": "",
                    "contact": "",
                    "email": "",
                    "keywords": "",
                }
            ]
            entry = parse_recent_meetings(json_data)[0]
            cache_path.write_text(
                "# Conference notification cache\n\nConferences listed here have already been included in an email notification.\n\n"
                f"- `{entry.cache_key}` | Astro AI Summit 2026 | 2026-07-10 to 2026-07-12 | Montreal, Canada | notified 2026-05-01\n",
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
                fetch_data=lambda: json_data,
                email_sender=lambda _config, text_body, html_body: sent_messages.append((text_body, html_body)),
                now=datetime(2026, 5, 8, tzinfo=timezone.utc),
            )

            self.assertEqual(len(sent_messages), 1)
            text_body, html_body = sent_messages[0]
            self.assertIn("There are no new conferences", text_body)
            self.assertIn("No new conferences this week", html_body)

    def test_run_pipeline_falls_back_to_local_preferences_when_llm_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "preferences.md").write_text(
                "# Conference preferences\n\n"
                "I'm interested in the following topics\n"
                "- Cosmology\n"
                "- Machine learning in the context of astronomy and cosmology\n\n"
                "I am not interested in conferences on the following topics\n"
                "- exoplanets\n",
                encoding="utf-8",
            )
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
            json_data = [
                {
                    "title": "Cosmology and machine learning workshop",
                    "start": "2026-07-10",
                    "end": "2026-07-12",
                    "location": "Montreal, Canada",
                    "web1": "https://example.com/cosmology-ml",
                    "web2": "",
                    "contact": "",
                    "email": "",
                    "keywords": "cosmology, machine learning",
                },
                {
                    "title": "Exoplanet atmospheres summit",
                    "start": "2026-08-02",
                    "end": "2026-08-05",
                    "location": "Berlin, Germany",
                    "web1": "https://example.com/exoplanets",
                    "web2": "",
                    "contact": "",
                    "email": "",
                    "keywords": "exoplanets",
                },
            ]
            sent_messages = []

            selected = run_pipeline(
                config=config,
                llm_client=FailingLLMClient(),
                fetch_data=lambda: json_data,
                email_sender=lambda _config, text_body, html_body: sent_messages.append((text_body, html_body)),
                now=datetime(2026, 5, 8, tzinfo=timezone.utc),
            )

            self.assertEqual([entry.title for entry in selected], ["Cosmology and machine learning workshop"])
            self.assertIn("Fallback preference match", selected[0].llm_reason)
            self.assertEqual(len(sent_messages), 1)
            text_body, html_body = sent_messages[0]
            self.assertIn("Cosmology and machine learning workshop", text_body)
            self.assertNotIn("Exoplanet atmospheres summit", text_body)
            self.assertIn("Cosmology and machine learning workshop", html_body)
            self.assertEqual(len(read_cache(config.cache_path)), 1)

    def test_format_email_uses_fallback_text_for_missing_fields(self) -> None:
        body = format_email([])
        self.assertIn("There are no new conferences", body)

    def test_format_email_html_empty_returns_no_conferences_message(self) -> None:
        html_body = format_email_html([])
        self.assertIn("<!DOCTYPE html>", html_body)
        self.assertIn("No new conferences this week", html_body)
        self.assertIn("Conference Digest", html_body)

    def test_format_email_html_with_entries_includes_all_fields(self) -> None:
        from conference_fetcher.models import ConferenceEntry

        entry = ConferenceEntry(
            title="Test Astronomy Meeting 2026",
            dates="2026-09-01 to 2026-09-05",
            location="Paris, France",
            registration_deadline="2026-07-15",
            preregistration_deadline="2026-06-01",
            abstract_deadline="2026-06-30",
            details="Contact: test@example.com",
            url="https://example.com/test",
            llm_reason="Matches astronomy preferences",
        )
        html_body = format_email_html([entry])
        self.assertIn("<!DOCTYPE html>", html_body)
        self.assertIn("Test Astronomy Meeting 2026", html_body)
        self.assertIn("Paris, France", html_body)
        self.assertIn("2026-09-01 to 2026-09-05", html_body)
        self.assertIn("https://example.com/test", html_body)
        self.assertIn("Matches astronomy preferences", html_body)
        self.assertIn("Why it matched", html_body)
        self.assertIn("Conference Digest", html_body)
