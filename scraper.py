import os
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "YardScout/1.0 (https://github.com/DevarshP610/YardScout)"
}
REQUEST_TIMEOUT = 18
SCRAPER_EMAIL = "scraper@auto.com"
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY")


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


def _scrape_ebrandon(location, country_code):
    if country_code != "CA" or location.split(",", 1)[0].casefold() != "brandon":
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

    try:
        ebrandon = _scrape_ebrandon(location, country_code)
        listings.extend(ebrandon)
        if country_code == "CA" and location.split(",", 1)[0].casefold() == "brandon":
            source_results.append(f"eBrandon: {len(ebrandon)} current/upcoming sale(s)")
        else:
            source_results.append("eBrandon: skipped (only covers Brandon, Manitoba)")
    except requests.RequestException as exc:
        source_results.append(f"eBrandon: unavailable ({exc})")

    if latitude is None or longitude is None:
        coordinates = _geocode(location)
        if coordinates:
            latitude, longitude = coordinates

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
        "Kijiji: no verified public listing API/feed; not scanned.",
        "Facebook: requires approved Meta access; not scanned.",
        "eBay: item ads are not garage-sale events; not imported as events.",
    ))

    saved = _save_listings(listings)
    return saved, "; ".join(source_results)
