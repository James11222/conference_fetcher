import unittest

from conference_fetcher.scraper import parse_recent_meetings


class ScraperTests(unittest.TestCase):
    def test_parse_recent_meetings_extracts_fields(self) -> None:
        html = """
        <html><body>
          <h1>Recent meetings</h1>
          <article class="views-row">
            <h2><a href="/en/meetings/example-1/">Astro AI Summit 2026</a></h2>
            <p>Conference dates: July 10-12, 2026</p>
            <p>Location: Montreal, Canada</p>
            <p>Registration deadline: May 20, 2026</p>
            <p>Pre-registration deadline: May 1, 2026</p>
            <p>Abstract submission deadline: April 15, 2026</p>
          </article>
        </body></html>
        """

        entries = parse_recent_meetings(html)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.title, "Astro AI Summit 2026")
        self.assertEqual(entry.dates, "July 10-12, 2026")
        self.assertEqual(entry.location, "Montreal, Canada")
        self.assertEqual(entry.registration_deadline, "May 20, 2026")
        self.assertEqual(entry.preregistration_deadline, "May 1, 2026")
        self.assertEqual(entry.abstract_deadline, "April 15, 2026")
        self.assertEqual(
            entry.url,
            "https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/meetings/example-1/",
        )
