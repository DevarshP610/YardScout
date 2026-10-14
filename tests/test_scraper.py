from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scraper


class ScraperTests(unittest.TestCase):
    @staticmethod
    def _garage_sale_card(sale_id, title, address, start_date, end_date, description=""):
        return f"""
            <div class="row collapse record">
                <div class="small-12 columns text-left">
                    <div class="sale-address"><strong>{address}</strong></div>
                    <div class="sale-date"
                         data-date-from="{start_date.strftime('%m/%d/%Y')}"
                         data-date-to="{end_date.strftime('%m/%d/%Y')}">
                        {start_date.strftime('%a, %b %d')} - {end_date.strftime('%a, %b %d')}
                    </div>
                    <div class="sale-title text-left">
                        <h2><a class="sale-url"
                               href="https://garagesalefinder.com/s/{sale_id}/seattle-wa-98134">{title}</a></h2>
                    </div>
                    <div class="sale-desc">{description}</div>
                </div>
            </div>
        """

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

    def test_ebrandon_covers_nearby_manitoba_places_only(self):
        self.assertTrue(
            scraper._is_ebrandon_area(
                "Virden, Manitoba, Canada",
                "CA",
                49.85,
                -100.93,
            )
        )
        self.assertFalse(
            scraper._is_ebrandon_area(
                "Winnipeg, Manitoba, Canada",
                "CA",
                49.8951,
                -97.1384,
            )
        )
        self.assertFalse(
            scraper._is_ebrandon_area(
                "Regina, Saskatchewan, Canada",
                "CA",
                50.4452,
                -104.6189,
            )
        )

    def test_location_scrape_checks_ebrandon_nearby_in_manitoba(self):
        with (
            patch.object(scraper, "_scrape_ebrandon", return_value=[]) as ebrandon,
            patch.object(scraper, "_scrape_garagesalefinder") as garage_sale_finder,
            patch.object(
                scraper,
                "_scrape_ticketmaster",
                return_value=([], "Ticketmaster: skipped (no API key)"),
            ),
            patch.object(scraper, "_save_listings", return_value=0),
        ):
            count, message = scraper.run_location_scrape(
                "Virden, Manitoba, Canada",
                latitude=49.85,
                longitude=-100.93,
                country_code="CA",
            )

        self.assertEqual(count, 0)
        self.assertIn("eBrandon: 0 current/upcoming sale(s) in its local coverage area", message)
        ebrandon.assert_called_once_with("Virden, Manitoba, Canada", "CA", 49.85, -100.93)
        garage_sale_finder.assert_not_called()

    def test_north_america_targets_cover_every_state_and_canadian_region(self):
        targets = scraper.NORTH_AMERICA_SCAN_TARGETS
        us_targets = [target for target in targets if target[3] == "US"]
        canada_targets = [target for target in targets if target[3] == "CA"]

        self.assertEqual(len(us_targets), 51)
        self.assertEqual(len(canada_targets), 19)
        self.assertEqual(len(targets), 70)
        self.assertEqual(
            {target[3] for target in targets},
            {"US", "CA"},
        )
        self.assertTrue(
            all(
                scraper._garage_sale_finder_location_slug(target[0], target[3])
                for target in us_targets
            )
        )

    def test_north_america_scan_reports_resumable_progress(self):
        first_remaining = scraper.NORTH_AMERICA_SCAN_TARGETS[-2:]
        progress_updates = []

        def record_progress(*values):
            progress_updates.append(values)

        with patch.object(scraper, "run_location_scrape", return_value=(2, "source status")) as scrape:
            saved = scraper.run_north_america_scan(
                record_progress,
                start_index=len(scraper.NORTH_AMERICA_SCAN_TARGETS) - len(first_remaining),
                initial_count=4,
            )

        self.assertEqual(saved, 8)
        self.assertEqual(scrape.call_count, 2)
        self.assertEqual([update[0] for update in progress_updates], [69, 70])
        self.assertEqual([update[2] for update in progress_updates], [6, 8])

    def test_garagesalefinder_parses_current_and_upcoming_sales(self):
        today = date.today()
        fixture_page = '<div id="city-sale-list">' + "".join((
            self._garage_sale_card(
                "current",
                "Seattle Neighborhood Garage Sale",
                "Seattle, WA 98134",
                today - timedelta(days=2),
                today + timedelta(days=2),
                "Tools and household items.",
            ),
            self._garage_sale_card(
                "upcoming",
                "Bellevue Yard Sale",
                "Bellevue, WA 98004",
                today + timedelta(days=4),
                today + timedelta(days=5),
            ),
            self._garage_sale_card(
                "expired",
                "Past Sale",
                "Seattle, WA 98134",
                today - timedelta(days=5),
                today - timedelta(days=3),
            ),
        )) + "</div>"

        with (
            patch.object(scraper, "_fetch", return_value=SimpleNamespace(text=fixture_page)),
            patch.object(
                scraper,
                "_geocode",
                side_effect=[(47.592, -122.324), (47.6101, -122.2015)],
            ) as geocode,
        ):
            listings = scraper._scrape_garagesalefinder(
                "Seattle, Washington, United States",
                47.6062,
                -122.3321,
                "US",
            )

        self.assertEqual([listing["title"] for listing in listings], [
            "Seattle Neighborhood Garage Sale",
            "Bellevue Yard Sale",
        ])
        self.assertEqual(listings[0]["date"], today.isoformat())
        self.assertEqual(listings[1]["date"], (today + timedelta(days=4)).isoformat())
        self.assertEqual(listings[0]["source_name"], "GarageSaleFinder")
        self.assertEqual(listings[0]["lat"], 47.592)
        self.assertIn("Approximate location from postal code: Seattle, WA 98134.", listings[0]["description"])
        self.assertEqual(geocode.call_count, 2)

    def test_garagesalefinder_location_routes_are_us_only(self):
        self.assertEqual(
            scraper._garage_sale_finder_location_slug("Seattle, Washington, United States", "US"),
            "seattle-wa",
        )
        self.assertEqual(
            scraper._garage_sale_finder_location_slug("St. Louis, Missouri, United States", "US"),
            "st-louis-mo",
        )
        self.assertIsNone(
            scraper._garage_sale_finder_location_slug("Regina, Saskatchewan, Canada", "CA")
        )

    def test_location_scrape_runs_garagesalefinder_for_us_places(self):
        listing = {
            "title": "Seattle Yard Sale",
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "description": "",
            "lat": 47.6,
            "lng": -122.3,
            "source_name": "GarageSaleFinder",
            "source_url": "https://garagesalefinder.com/s/example/seattle-wa-98134",
        }
        with (
            patch.object(scraper, "_scrape_ebrandon", return_value=[]),
            patch.object(scraper, "_scrape_garagesalefinder", return_value=[listing]) as gsf,
            patch.object(
                scraper,
                "_scrape_ticketmaster",
                return_value=([], "Ticketmaster: skipped (no API key)"),
            ),
            patch.object(scraper, "_save_listings", return_value=1) as save_listings,
        ):
            count, message = scraper.run_location_scrape(
                "Seattle, Washington, United States",
                latitude=47.6062,
                longitude=-122.3321,
                country_code="US",
            )

        self.assertEqual(count, 1)
        self.assertIn("GarageSaleFinder: 1 current/upcoming sale(s)", message)
        gsf.assert_called_once_with(
            "Seattle, Washington, United States",
            47.6062,
            -122.3321,
            "US",
        )
        save_listings.assert_called_once_with([listing])

    def test_unverified_sources_are_reported_but_not_called(self):
        with (
            patch.object(scraper, "_scrape_ebrandon", return_value=[]),
            patch.object(scraper, "_scrape_garagesalefinder") as garage_sale_finder,
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
        self.assertIn("GarageSaleFinder: skipped (US city/state pages only; no Canadian listing coverage)", message)
        self.assertIn("Used.ca: not scanned; its robots.txt excludes search routes", message)
        self.assertIn("Facebook: not scanned; Meta requires separate express written permission", message)
        self.assertIn("Kijiji: not scanned; no verified public event feed", message)
        garage_sale_finder.assert_not_called()
        save_listings.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
