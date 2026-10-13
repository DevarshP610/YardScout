from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scraper


class ScraperTests(unittest.TestCase):
    def test_ebrandon_parses_upcoming_sale(self):
        sale_date = (date.today() + timedelta(days=7)).strftime("%B %d %Y")
        category_page = """
            <a href="ItemView.aspx?item_id=123&cat_id=81">Community sale</a>
        """
        listing_page = f"""
            <meta property="og:title" content="Community Yard Sale, eBrandon Classifieds">
            <div id="pnlDates">Date(s): {sale_date}</div>
            <div><strong>Location</strong>: West End, Brandon</div>
            <div class="item_wrap"><p>Furniture, tools, and household items.</p></div>
        """

        with (
            patch.object(
                scraper,
                "_fetch",
                side_effect=[
                    SimpleNamespace(text=category_page),
                    SimpleNamespace(text=listing_page),
                ],
            ),
            patch.object(scraper, "_geocode", return_value=(49.8, -99.95)) as geocode,
            patch.object(scraper.time, "sleep"),
        ):
            listings = scraper._scrape_ebrandon("Brandon, Manitoba", "CA")

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["title"], "Community Yard Sale")
        self.assertEqual(listings[0]["date"], (date.today() + timedelta(days=7)).isoformat())
        self.assertEqual(listings[0]["source_name"], "eBrandon")
        self.assertEqual(listings[0]["lat"], 49.8)
        self.assertEqual(listings[0]["lng"], -99.95)
        geocode.assert_called_once_with("West End, Brandon, Manitoba")

    def test_unverified_sources_are_reported_but_not_called(self):
        with (
            patch.object(scraper, "_scrape_ebrandon", return_value=[]),
            patch.object(
                scraper,
                "_scrape_ticketmaster",
                return_value=([], "Ticketmaster: skipped (no API key)"),
            ),
            patch.object(scraper, "_save_listings", return_value=0) as save_listings,
        ):
            count, message = scraper.run_location_scrape(
                "Regina, Saskatchewan",
                latitude=50.4452,
                longitude=-104.6189,
                country_code="CA",
            )

        self.assertEqual(count, 0)
        self.assertIn("GarageSaleFinder: not scanned; its terms prohibit automated data collection.", message)
        self.assertIn("Used.ca: not scanned; its robots.txt excludes search routes", message)
        self.assertIn("Facebook: not scanned; Meta requires separate express written permission", message)
        self.assertIn("Kijiji: not scanned; no verified public event feed", message)
        save_listings.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
