import unittest

from conference_fetcher.scraper import parse_recent_meetings


class ScraperTests(unittest.TestCase):
    def test_parse_recent_meetings_extracts_fields(self) -> None:
        data = [
            {
                "title": "Astro AI Summit 2026",
                "start": "2026-07-10",
                "end": "2026-07-12",
                "location": "Montreal, Canada",
                "web1": "https://example.com/astro-ai-2026",
                "web2": "",
                "contact": "Jane Smith",
                "email": "jane@example.com",
                "keywords": "astronomy, AI",
            }
        ]

        entries = parse_recent_meetings(data)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.title, "Astro AI Summit 2026")
        self.assertEqual(entry.dates, "2026-07-10 to 2026-07-12")
        self.assertEqual(entry.location, "Montreal, Canada")
        self.assertEqual(entry.url, "https://example.com/astro-ai-2026")
        self.assertIn("Jane Smith", entry.details)
        self.assertIn("jane@example.com", entry.details)
        self.assertIn("astronomy, AI", entry.details)

    def test_parse_recent_meetings_multiple_entries(self) -> None:
        data = [
            {
                "title": "Little Red Dots 2026",
                "start": "2026-06-22",
                "end": "2026-06-24",
                "location": "online",
                "web1": "https://sites.google.com/uniroma1.it/lrdworkshop2026/",
                "web2": "",
                "contact": "Dominik Schleicher",
                "email": "dominik.schleicher@uniroma1.it",
                "keywords": "Little Red Dots, supermassive black holes",
            },
            {
                "title": "Cosmology and galaxy astrophysics with simulations and machine learning 2027",
                "start": "2027-01-04",
                "end": "2027-01-08",
                "location": "Flatiron Institute's Center for Computational Astrophysics",
                "web1": "https://www.simonsfoundation.org/event/cosmology-2027/",
                "web2": "",
                "contact": "Abigail Creem",
                "email": "acreem@flatironinstitute.org",
                "keywords": "cosmology, large-scale structure",
            },
        ]

        entries = parse_recent_meetings(data)

        titles = [e.title for e in entries]
        self.assertIn("Little Red Dots 2026", titles)
        self.assertIn(
            "Cosmology and galaxy astrophysics with simulations and machine learning 2027",
            titles,
        )

        lrd = next(e for e in entries if e.title == "Little Red Dots 2026")
        self.assertEqual(lrd.dates, "2026-06-22 to 2026-06-24")
        self.assertEqual(lrd.location, "online")
        self.assertEqual(lrd.url, "https://sites.google.com/uniroma1.it/lrdworkshop2026/")

    def test_parse_recent_meetings_falls_back_to_web2_when_web1_missing(self) -> None:
        data = [
            {
                "title": "Fallback URL Conference",
                "start": "2026-09-01",
                "end": "2026-09-03",
                "location": "Berlin, Germany",
                "web1": "",
                "web2": "https://example.com/fallback",
                "contact": "",
                "email": "",
                "keywords": "",
            }
        ]

        entries = parse_recent_meetings(data)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].url, "https://example.com/fallback")

    def test_parse_recent_meetings_skips_entries_without_title(self) -> None:
        data = [
            {"title": "", "start": "2026-01-01", "end": "2026-01-02", "location": "Nowhere"},
            {"title": "Valid Conference", "start": "2026-03-01", "end": "2026-03-03", "location": "Paris"},
        ]

        entries = parse_recent_meetings(data)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "Valid Conference")

