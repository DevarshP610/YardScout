import os
import math
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "YardScout/1.0 (https://github.com/DevarshP610/YardScout)"
}
REQUEST_TIMEOUT = 18
SCRAPER_EMAIL = "scraper@auto.com"
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY")
GARAGESALEFINDER_URL = "https://garagesalefinder.com"
GARAGESALEFINDER_MAX_SALES = 25
GARAGESALEFINDER_MAX_CARDS = 50
GARAGESALEFINDER_RADIUS_KM = 80.5
EBRANDON_RADIUS_KM = 80.5
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
US_STATE_CODES = {code.casefold(): code for code in US_STATES.values()}
NORTH_AMERICA_SCAN_TARGETS = (
    ("Montgomery, Alabama, United States", 32.3668, -86.3000, "US"),
    ("Juneau, Alaska, United States", 58.3019, -134.4197, "US"),
    ("Phoenix, Arizona, United States", 33.4484, -112.0740, "US"),
    ("Little Rock, Arkansas, United States", 34.7465, -92.2896, "US"),
    ("Sacramento, California, United States", 38.5816, -121.4944, "US"),
    ("Denver, Colorado, United States", 39.7392, -104.9903, "US"),
    ("Hartford, Connecticut, United States", 41.7658, -72.6734, "US"),
    ("Dover, Delaware, United States", 39.1582, -75.5244, "US"),
    ("Washington, District of Columbia, United States", 38.9072, -77.0369, "US"),
    ("Tallahassee, Florida, United States", 30.4383, -84.2807, "US"),
    ("Atlanta, Georgia, United States", 33.7490, -84.3880, "US"),
    ("Honolulu, Hawaii, United States", 21.3099, -157.8581, "US"),
    ("Boise, Idaho, United States", 43.6150, -116.2023, "US"),
    ("Springfield, Illinois, United States", 39.7817, -89.6501, "US"),
    ("Indianapolis, Indiana, United States", 39.7684, -86.1581, "US"),
    ("Des Moines, Iowa, United States", 41.5868, -93.6250, "US"),
    ("Topeka, Kansas, United States", 39.0473, -95.6752, "US"),
    ("Frankfort, Kentucky, United States", 38.2009, -84.8733, "US"),
    ("Baton Rouge, Louisiana, United States", 30.4515, -91.1871, "US"),
    ("Augusta, Maine, United States", 44.3106, -69.7795, "US"),
    ("Annapolis, Maryland, United States", 38.9784, -76.4922, "US"),
    ("Boston, Massachusetts, United States", 42.3601, -71.0589, "US"),
    ("Lansing, Michigan, United States", 42.7325, -84.5555, "US"),
    ("Saint Paul, Minnesota, United States", 44.9537, -93.0900, "US"),
    ("Jackson, Mississippi, United States", 32.2988, -90.1848, "US"),
    ("Jefferson City, Missouri, United States", 38.5767, -92.1735, "US"),
    ("Helena, Montana, United States", 46.5884, -112.0245, "US"),
    ("Lincoln, Nebraska, United States", 40.8136, -96.7026, "US"),
    ("Carson City, Nevada, United States", 39.1638, -119.7674, "US"),
    ("Concord, New Hampshire, United States", 43.2081, -71.5376, "US"),
    ("Trenton, New Jersey, United States", 40.2171, -74.7429, "US"),
    ("Santa Fe, New Mexico, United States", 35.6870, -105.9378, "US"),
    ("Albany, New York, United States", 42.6526, -73.7562, "US"),
    ("Raleigh, North Carolina, United States", 35.7796, -78.6382, "US"),
    ("Bismarck, North Dakota, United States", 46.8083, -100.7837, "US"),
    ("Columbus, Ohio, United States", 39.9612, -82.9988, "US"),
    ("Oklahoma City, Oklahoma, United States", 35.4676, -97.5164, "US"),
    ("Salem, Oregon, United States", 44.9429, -123.0351, "US"),
    ("Harrisburg, Pennsylvania, United States", 40.2732, -76.8867, "US"),
    ("Providence, Rhode Island, United States", 41.8240, -71.4128, "US"),
    ("Columbia, South Carolina, United States", 34.0007, -81.0348, "US"),
    ("Pierre, South Dakota, United States", 44.3683, -100.3510, "US"),
    ("Nashville, Tennessee, United States", 36.1627, -86.7816, "US"),
    ("Austin, Texas, United States", 30.2672, -97.7431, "US"),
    ("Salt Lake City, Utah, United States", 40.7608, -111.8910, "US"),
    ("Montpelier, Vermont, United States", 44.2601, -72.5754, "US"),
    ("Richmond, Virginia, United States", 37.5407, -77.4360, "US"),
    ("Olympia, Washington, United States", 47.0379, -122.9007, "US"),
    ("Charleston, West Virginia, United States", 38.3498, -81.6326, "US"),
    ("Madison, Wisconsin, United States", 43.0731, -89.4012, "US"),
    ("Cheyenne, Wyoming, United States", 41.1400, -104.8202, "US"),
    ("St. John's, Newfoundland and Labrador, Canada", 47.5615, -52.7126, "CA"),
    ("Charlottetown, Prince Edward Island, Canada", 46.2382, -63.1311, "CA"),
    ("Halifax, Nova Scotia, Canada", 44.6488, -63.5752, "CA"),
    ("Fredericton, New Brunswick, Canada", 45.9636, -66.6431, "CA"),
    ("Quebec City, Quebec, Canada", 46.8139, -71.2080, "CA"),
    ("Toronto, Ontario, Canada", 43.6532, -79.3832, "CA"),
    ("Winnipeg, Manitoba, Canada", 49.8951, -97.1384, "CA"),
    ("Regina, Saskatchewan, Canada", 50.4452, -104.6189, "CA"),
    ("Edmonton, Alberta, Canada", 53.5461, -113.4938, "CA"),
    ("Victoria, British Columbia, Canada", 48.4284, -123.3656, "CA"),
    ("Whitehorse, Yukon, Canada", 60.7212, -135.0568, "CA"),
    ("Yellowknife, Northwest Territories, Canada", 62.4540, -114.3718, "CA"),
    ("Iqaluit, Nunavut, Canada", 63.7467, -68.5170, "CA"),
    ("Brandon, Manitoba, Canada", 49.8485, -99.9501, "CA"),
    ("Vancouver, British Columbia, Canada", 49.2827, -123.1207, "CA"),
    ("Calgary, Alberta, Canada", 51.0447, -114.0719, "CA"),
    ("Montreal, Quebec, Canada", 45.5019, -73.5674, "CA"),
    ("Ottawa, Ontario, Canada", 45.4215, -75.6972, "CA"),
    ("Saskatoon, Saskatchewan, Canada", 52.1332, -106.6700, "CA"),
)


def _fetch(url):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _parse_sale_date(text):
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    patterns = (
        r"\b\d{4}-\d{1,2}-\d{1,2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(0)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d %Y", "%b %d %Y", "%B %d", "%b %d"):
            try:
                parsed = datetime.strptime(value.replace(",", ""), fmt).date()
                if "%Y" not in fmt:
                    parsed = parsed.replace(year=date.today().year)
                    if parsed < date.today():
                        parsed = parsed.replace(year=parsed.year + 1)
                return parsed.isoformat()
            except ValueError:
                continue
    return None


def _geocode(query):
    if not query:
        return None
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        print(f"Geocoding failed for {query!r}: {exc}")
    finally:
        time.sleep(1.1)
    return None


def _geohash(latitude, longitude, precision=8):
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    bits = (16, 8, 4, 2, 1)
    output = []
    value = 0
    bit_index = 0
    use_longitude = True
    while len(output) < precision:
        bounds = lon_range if use_longitude else lat_range
        coordinate = longitude if use_longitude else latitude
        midpoint = (bounds[0] + bounds[1]) / 2
        if coordinate >= midpoint:
            value |= bits[bit_index]
            bounds[0] = midpoint
        else:
            bounds[1] = midpoint
        use_longitude = not use_longitude
        if bit_index < 4:
            bit_index += 1
        else:
            output.append(base32[value])
            bit_index = 0
            value = 0
    return "".join(output)


def _is_ebrandon_area(location, country_code, latitude, longitude):
    if country_code != "CA":
        return False
    parts = [part.strip().casefold() for part in location.split(",")]
    if not any(part in {"manitoba", "mb"} for part in parts):
        return False
    if latitude is None or longitude is None:
        return parts[0] == "brandon"
    return _distance_km(latitude, longitude, 49.8485, -99.9501) <= EBRANDON_RADIUS_KM


def _scrape_ebrandon(location, country_code, latitude=None, longitude=None):
    if not _is_ebrandon_area(location, country_code, latitude, longitude):
        return []

    category_url = "https://www.ebrandon.ca/browseads.aspx?cat_id=81"
    soup = BeautifulSoup(_fetch(category_url).text, "html.parser")
    item_links = []
    for anchor in soup.select('a[href*="ItemView.aspx?item_id="]'):
        href = anchor.get("href", "")
        if isinstance(href, str) and "cat_id=81" in href and href not in item_links:
            item_links.append(href)

    listings = []
    for href in item_links[:30]:
        item_url = urljoin(category_url, href)
        try:
            item_soup = BeautifulSoup(_fetch(item_url).text, "html.parser")
        except requests.RequestException as exc:
            print(f"eBrandon listing fetch failed for {item_url}: {exc}")
            time.sleep(1.0)
            continue
        time.sleep(1.0)

        title_element = item_soup.find("meta", property="og:title")
        title_value = title_element.get("content", "") if title_element else ""
        title = title_value if isinstance(title_value, str) else ""
        title = re.sub(r",\s*eBrandon Classifieds$", "", title, flags=re.IGNORECASE).strip()
        if not title or not re.search(r"garage|yard|moving|estate|sale", title, re.I):
            continue

        dates_panel = item_soup.find(id="pnlDates")
        details_text = dates_panel.get_text(" ", strip=True) if dates_panel else ""
        sale_date = _parse_sale_date(details_text)
        if not sale_date or sale_date < date.today().isoformat():
            continue

        location_label = next(
            (
                element for element in item_soup.find_all("strong")
                if element.get_text(" ", strip=True).casefold() == "location"
            ),
            None,
        )
        location_text = (
            location_label.parent.get_text(" ", strip=True)
            if location_label and location_label.parent
            else ""
        )
        address = location_text.partition(":")[2].strip(" :,-")
        address = re.sub(r"(?:,\s*|\s+)Brandon(?:\s*,?\s*Brandon)?$", "", address, flags=re.IGNORECASE).strip(" ,")
        coordinates = _geocode(f"{address}, Brandon, Manitoba" if address else "Brandon, Manitoba")
        if not coordinates:
            continue
        if latitude is not None and longitude is not None and _distance_km(
            latitude,
            longitude,
            coordinates[0],
            coordinates[1],
        ) > EBRANDON_RADIUS_KM:
            continue

        description = ""
        item_body = item_soup.select_one(".item_wrap")
        if item_body:
            paragraphs = [
                paragraph.get_text(" ", strip=True)
                for paragraph in item_body.find_all("p")
            ]
            description = max(paragraphs, key=len, default="")
            description = re.split(r"\s+Warning\s*:", description, maxsplit=1)[0].strip()
        if not address:
            description = f"Approximate location: Brandon, Manitoba. {description}".strip()
        listings.append({
            "title": title[:250],
            "date": sale_date,
            "description": description[:2000],
            "lat": coordinates[0],
            "lng": coordinates[1],
            "source_name": "eBrandon",
            "source_url": item_url,
        })
    return listings


def _garage_sale_finder_location_slug(location, country_code):
    if not isinstance(country_code, str) or country_code.upper() != "US":
        return None
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) < 2:
        return None

    state_code = None
    for part in parts[1:]:
        normalized_part = part.casefold()
        state_code = US_STATES.get(normalized_part) or US_STATE_CODES.get(normalized_part)
        if state_code:
            break
    if not state_code:
        return None

    city = unicodedata.normalize("NFKD", parts[0]).encode("ascii", "ignore").decode("ascii")
    city_slug = re.sub(r"[^a-z0-9]+", "-", city.casefold()).strip("-")
    if not city_slug:
        return None
    return f"{city_slug}-{state_code.casefold()}"


def _parse_garagesalefinder_date(value):
    for date_format in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def _distance_km(latitude_a, longitude_a, latitude_b, longitude_b):
    earth_radius_km = 6371.0088
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    latitude_delta = lat_b - lat_a
    longitude_delta = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(min(haversine, 1.0)))


def _scrape_garagesalefinder(location, latitude, longitude, country_code):
    location_slug = _garage_sale_finder_location_slug(location, country_code)
    if not location_slug:
        return []

    city_url = f"{GARAGESALEFINDER_URL}/yard-sales/{location_slug}/"
    soup = BeautifulSoup(_fetch(city_url).text, "html.parser")
    listings = []
    geocoded_locations = {}
    today = date.today()

    for title_element in soup.select("#city-sale-list a.sale-url")[:GARAGESALEFINDER_MAX_CARDS]:
        if len(listings) >= GARAGESALEFINDER_MAX_SALES:
            break
        href = title_element.get("href")
        if not isinstance(href, str) or not href:
            continue
        source_url = urljoin(city_url, href)
        parsed_source_url = urlsplit(source_url)
        if parsed_source_url.scheme != "https" or parsed_source_url.hostname != "garagesalefinder.com":
            continue

        card = title_element.find_parent("div", class_="row")
        if card is None:
            continue
        address_element = card.select_one(".sale-address")
        date_element = card.select_one(".sale-date")
        title = title_element.get_text(" ", strip=True)
        address = address_element.get_text(" ", strip=True) if address_element else ""
        if not title or not address or not re.search(r"\b\d{5}(?:-\d{4})?\b", address):
            continue
        if date_element is None:
            continue

        start_date = _parse_garagesalefinder_date(date_element.get("data-date-from", ""))
        end_date = _parse_garagesalefinder_date(date_element.get("data-date-to", ""))
        if start_date is None or end_date is None or end_date < today:
            continue
        sale_date = max(start_date, today)

        if address not in geocoded_locations:
            geocoded_locations[address] = _geocode(address)
        coordinates = geocoded_locations[address]
        if not coordinates:
            continue
        sale_latitude, sale_longitude = coordinates
        if not (-90 <= sale_latitude <= 90 and -180 <= sale_longitude <= 180):
            continue
        if _distance_km(latitude, longitude, sale_latitude, sale_longitude) > GARAGESALEFINDER_RADIUS_KM:
            continue

        description_element = card.select_one(".sale-desc")
        description = description_element.get_text(" ", strip=True) if description_element else ""
        date_note = f"Sale dates: {start_date.isoformat()} to {end_date.isoformat()}."
        location_note = f"Approximate location from postal code: {address}."
        description = " ".join(part for part in (description, date_note, location_note) if part)
        listings.append({
            "title": title[:250],
            "date": sale_date.isoformat(),
            "description": description[:2000],
            "lat": sale_latitude,
            "lng": sale_longitude,
            "source_name": "GarageSaleFinder",
            "source_url": source_url,
        })
    return listings


def _scrape_ticketmaster(location, latitude, longitude, country_code):
    if not TICKETMASTER_API_KEY:
        return [], "Ticketmaster: skipped (set TICKETMASTER_API_KEY to enable its official API)"

    events_by_id = {}
    errors = []
    for keyword in ("garage sale", "yard sale"):
        try:
            response = requests.get(
                "https://app.ticketmaster.com/discovery/v2/events.json",
                params={
                    "apikey": TICKETMASTER_API_KEY,
                    "keyword": keyword,
                    "geoPoint": _geohash(latitude, longitude),
                    "radius": 50,
                    "unit": "miles",
                    "countryCode": country_code,
                    "startDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sort": "date,asc",
                    "size": 100,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Ticketmaster returned an invalid response.")
            embedded = payload.get("_embedded")
            if not isinstance(embedded, dict):
                continue
            events = embedded.get("events", [])
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_id = event.get("id")
                if isinstance(event_id, (str, int)):
                    events_by_id[event_id] = event
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if isinstance(status_code, int):
                detail = f"HTTP {status_code}"
            elif isinstance(exc, requests.Timeout):
                detail = "request timed out"
            else:
                detail = "request failed"
            errors.append(f"{keyword}: {detail}")
        except ValueError:
            errors.append(f"{keyword}: invalid API response")
    if errors and not events_by_id:
        raise requests.RequestException("; ".join(errors))

    listings = []
    for event in events_by_id.values():
        name = event.get("name")
        dates = event.get("dates")
        start = dates.get("start") if isinstance(dates, dict) else None
        event_date = start.get("localDate") if isinstance(start, dict) else None
        if not isinstance(name, str) or not isinstance(event_date, str):
            continue
        try:
            event_date = date.fromisoformat(event_date).isoformat()
        except ValueError:
            continue
        if event_date < date.today().isoformat():
            continue

        event_embedded = event.get("_embedded")
        venues = event_embedded.get("venues", []) if isinstance(event_embedded, dict) else []
        venue = venues[0] if isinstance(venues, list) and venues and isinstance(venues[0], dict) else {}
        venue_location = venue.get("location")
        if not isinstance(venue_location, dict):
            continue
        raw_latitude = venue_location.get("latitude")
        raw_longitude = venue_location.get("longitude")
        if raw_latitude is None or raw_longitude is None:
            continue
        try:
            event_latitude = float(raw_latitude)
            event_longitude = float(raw_longitude)
        except (TypeError, ValueError):
            continue
        if not (-90 <= event_latitude <= 90 and -180 <= event_longitude <= 180):
            continue

        info = event.get("info") or event.get("pleaseNote") or ""
        venue_name = venue.get("name")
        if isinstance(venue_name, str) and venue_name:
            info = f"{venue_name}. {info}".strip()
        source_url = event.get("url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            continue
        listings.append({
            "title": name[:250],
            "date": event_date,
            "description": str(info)[:2000],
            "lat": event_latitude,
            "lng": event_longitude,
            "source_name": "Ticketmaster",
            "source_url": source_url,
        })
    summary = f"Ticketmaster: {len(listings)} current/upcoming event(s) near {location}"
    if errors:
        summary += f" (some searches unavailable: {'; '.join(errors)})"
    return listings, summary


def _save_listings(listings):
    from app import USE_SQLITE, get_db, row_as_dict

    conn = get_db()
    cur = conn.cursor()
    saved = 0
    try:
        for listing in listings:
            if USE_SQLITE:
                cur.execute("SELECT id FROM sales WHERE source_url = ?", (listing["source_url"],))
            else:
                cur.execute("SELECT id FROM sales WHERE source_url = %s", (listing["source_url"],))
            existing = cur.fetchone()
            existing_id = row_as_dict(existing)["id"] if existing else None
            values = (
                listing["title"],
                listing["date"],
                listing["description"],
                listing["lat"],
                listing["lng"],
                listing["source_name"],
                listing["source_url"],
                SCRAPER_EMAIL,
                "YardScout",
            )
            if existing:
                if USE_SQLITE:
                    cur.execute(
                        """
                        UPDATE sales SET title = ?, date = ?, description = ?, lat = ?, lng = ?,
                            source_name = ?, user_email = ?, user_name = ?
                        WHERE id = ?
                        """,
                        (*values[:6], values[7], values[8], existing_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE sales SET title = %s, date = %s, description = %s, lat = %s, lng = %s,
                            source_name = %s, user_email = %s, user_name = %s
                        WHERE id = %s
                        """,
                        (*values[:6], values[7], values[8], existing_id),
                    )
            elif USE_SQLITE:
                cur.execute(
                    """
                    INSERT INTO sales
                        (title, date, description, lat, lng, source_name, source_url, user_email, user_name, user_picture)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                    """,
                    values,
                )
            else:
                cur.execute(
                    """
                    INSERT INTO sales
                        (title, date, description, lat, lng, source_name, source_url, user_email, user_name, user_picture)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')
                    """,
                    values,
                )
            saved += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return saved


def run_location_scrape(location, latitude=None, longitude=None, country_code=None):
    listings = []
    source_results = []

    if latitude is None or longitude is None:
        coordinates = _geocode(location)
        if coordinates:
            latitude, longitude = coordinates

    try:
        ebrandon = _scrape_ebrandon(location, country_code, latitude, longitude)
        listings.extend(ebrandon)
        if _is_ebrandon_area(location, country_code, latitude, longitude):
            source_results.append(f"eBrandon: {len(ebrandon)} current/upcoming sale(s) in its local coverage area")
        else:
            source_results.append("eBrandon: skipped (covers Brandon and nearby southwest Manitoba only)")
    except requests.RequestException as exc:
        source_results.append(f"eBrandon: unavailable ({exc})")

    if _garage_sale_finder_location_slug(location, country_code):
        try:
            if latitude is None or longitude is None:
                raise requests.RequestException("Could not resolve the selected location coordinates.")
            garage_sale_finder = _scrape_garagesalefinder(
                location,
                latitude,
                longitude,
                country_code,
            )
            listings.extend(garage_sale_finder)
            source_results.append(
                f"GarageSaleFinder: {len(garage_sale_finder)} current/upcoming sale(s) near {location}"
            )
        except requests.RequestException as exc:
            source_results.append(f"GarageSaleFinder: unavailable ({exc})")
    else:
        source_results.append("GarageSaleFinder: skipped (US city/state pages only; no Canadian listing coverage)")

    try:
        if latitude is None or longitude is None:
            raise requests.RequestException("Could not resolve the selected location coordinates.")
        ticketmaster, ticketmaster_summary = _scrape_ticketmaster(
            location,
            latitude,
            longitude,
            country_code or "US",
        )
        listings.extend(ticketmaster)
        source_results.append(ticketmaster_summary)
    except requests.RequestException as exc:
        source_results.append(f"Ticketmaster: unavailable ({exc})")
    source_results.extend((
        "Craigslist: not scanned; its terms prohibit unlicensed automated searching.",
        "Kijiji: not scanned; no verified public event feed, and search results include ordinary item ads.",
        "Used.ca: not scanned; its robots.txt excludes search routes and no event feed is verified.",
        "Facebook: not scanned; Meta requires separate express written permission for automated collection.",
        "eBay: item ads are not garage-sale events; not imported as events.",
    ))

    saved = _save_listings(listings)
    return saved, "; ".join(source_results)


def run_north_america_scan(progress_callback, start_index=0, initial_count=0):
    total_steps = len(NORTH_AMERICA_SCAN_TARGETS)
    if not 0 <= start_index <= total_steps:
        raise ValueError("The scan progress is outside the available target range.")

    saved = initial_count
    for index, (location, latitude, longitude, country_code) in enumerate(
        NORTH_AMERICA_SCAN_TARGETS[start_index:],
        start=start_index,
    ):
        count, _ = run_location_scrape(
            location,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
        )
        saved += count
        progress_callback(
            index + 1,
            total_steps,
            saved,
            location,
        )
    return saved
