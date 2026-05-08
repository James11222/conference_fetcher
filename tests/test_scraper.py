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

    def test_parse_recent_meetings_details_summary_structure(self) -> None:
        """CADC page uses <details>/<summary> accordion elements for each conference."""
        html = """
        <html><body>
          <header>
            <h2>Language selection</h2>
            <nav><ul><li><a href="/fr/">Français</a></li></ul></nav>
          </header>
          <nav id="wb-bc"><h2>You are here:</h2><ol><li>Home</li></ol></nav>
          <main>
            <h1>Meetings</h1>
            <h2>Meetings added within the last three weeks</h2>
            <details>
              <summary><a href="https://example.com/lrd2026">Little Red Dots 2026</a></summary>
              <dl>
                <dt>Conference Dates:</dt>
                <dd>Monday, 22 June 2026 - Wednesday, 24 June 2026</dd>
                <dt>Location:</dt>
                <dd>Cambridge, UK</dd>
              </dl>
            </details>
            <details>
              <summary>Cosmology and galaxy astrophysics with simulations and machine learning 2027</summary>
              <dl>
                <dt>Conference Dates:</dt>
                <dd>Monday, 4 January 2027 - Friday, 8 January 2027</dd>
                <dt>Location:</dt>
                <dd>Garching, Germany</dd>
              </dl>
            </details>
            <aside>
              <h2>Section menu</h2>
              <ul>
                <li><a href="/en/meetings/recent/">Meetings</a></li>
              </ul>
            </aside>
          </main>
          <footer><h2>Government of Canada</h2></footer>
        </body></html>
        """

        entries = parse_recent_meetings(html)

        titles = [e.title for e in entries]
        self.assertIn("Little Red Dots 2026", titles)
        self.assertIn(
            "Cosmology and galaxy astrophysics with simulations and machine learning 2027",
            titles,
        )
        # Navigation headings must NOT appear as conference entries
        self.assertNotIn("Language selection", titles)
        self.assertNotIn("You are here:", titles)
        self.assertNotIn("Section menu", titles)
        self.assertNotIn("Government of Canada", titles)
        self.assertNotIn("Meetings added within the last three weeks", titles)

        lrd = next(e for e in entries if e.title == "Little Red Dots 2026")
        self.assertEqual(lrd.dates, "Monday, 22 June 2026 - Wednesday, 24 June 2026")
        self.assertEqual(lrd.location, "Cambridge, UK")
        self.assertEqual(lrd.url, "https://example.com/lrd2026")

        cosmo = next(
            e
            for e in entries
            if e.title == "Cosmology and galaxy astrophysics with simulations and machine learning 2027"
        )
        self.assertEqual(cosmo.dates, "Monday, 4 January 2027 - Friday, 8 January 2027")
        self.assertEqual(cosmo.location, "Garching, Germany")

    def test_parse_recent_meetings_ignores_navigation_headings(self) -> None:
        """Standalone headings outside entry containers must not become entries."""
        html = """
        <html><body>
          <h2>Language selection</h2>
          <h2>Search</h2>
          <h2>You are here:</h2>
          <h2>Menus</h2>
          <h2>Sign-on information</h2>
          <h2>About this site</h2>
          <details>
            <summary>Real Conference 2026</summary>
            <p>Conference Dates: October 1-3, 2026</p>
          </details>
        </body></html>
        """

        entries = parse_recent_meetings(html)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "Real Conference 2026")
