import re
import time
from datetime import date, datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "YardScout/1.0 (https://github.com/DevarshP610/Garage-Sale-Finder)"
}
REQUEST_TIMEOUT = 18
SCRAPER_EMAIL = "scraper@auto.com"


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


def _source_city(location):
    city = location.split(",", 1)[0].strip()
    return re.sub(r"[^a-z0-9-]", "", city.casefold().replace(" ", "-"))


def _scrape_ebrandon(location):
    if "brandon" not in location.casefold():
        return []

    category_url = "https://www.ebrandon.ca/browseads.aspx?cat_id=81"
    soup = BeautifulSoup(_fetch(category_url).text, "html.parser")
    item_links = []
    for anchor in soup.select('a[href*="ItemView.aspx?item_id="]'):
        href = anchor.get("href", "")
        if "cat_id=81" in href and href not in item_links:
            item_links.append(href)

    listings = []
    for href in item_links[:30]:
        item_url = requests.compat.urljoin(category_url, href)
        try:
            item_soup = BeautifulSoup(_fetch(item_url).text, "html.parser")
        except requests.RequestException as exc:
            print(f"eBrandon listing fetch failed for {item_url}: {exc}")
            time.sleep(1.0)
            continue
        time.sleep(1.0)

        title_element = item_soup.find("meta", property="og:title")
        title = title_element.get("content", "") if title_element else ""
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


def _scrape_craigslist(location):
    city = _source_city(location)
    if not city:
        return []
    url = f"https://{city}.craigslist.org/search/gms?query={quote('garage sale')}&format=rss"
    try:
        response = _fetch(url)
    except requests.RequestException as exc:
        raise requests.RequestException(f"Craigslist is unavailable for {location!r}: {exc}") from exc

    soup = BeautifulSoup(response.content, "xml")
    listings = []
    for item in soup.find_all("item")[:30]:
        title = item.title.get_text(" ", strip=True) if item.title else ""
        description = item.description.get_text(" ", strip=True) if item.description else ""
        sale_date = _parse_sale_date(f"{title} {description}")
        if not sale_date or sale_date < date.today().isoformat():
            continue

        point = item.find("georss:point") or item.find("point")
        coordinates = None
        if point:
            try:
                lat, lng = map(float, point.get_text(strip=True).split())
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    coordinates = lat, lng
            except ValueError:
                coordinates = None
        if not coordinates:
            coordinates = _geocode(location)
        if not coordinates:
            continue

        link = item.link.get_text(strip=True) if item.link else ""
        listings.append({
            "title": title[:250],
            "date": sale_date,
            "description": description[:2000],
            "lat": coordinates[0],
            "lng": coordinates[1],
            "source_name": "Craigslist",
            "source_url": link,
        })
        time.sleep(0.25)
    return listings


def _save_listings(listings):
    from app import USE_SQLITE, get_db

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
                        (*values[:6], values[7], values[8], existing["id"]),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE sales SET title = %s, date = %s, description = %s, lat = %s, lng = %s,
                            source_name = %s, user_email = %s, user_name = %s
                        WHERE id = %s
                        """,
                        (*values[:6], values[7], values[8], existing["id"]),
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


def run_location_scrape(location):
    listings = []
    source_results = []

    try:
        ebrandon = _scrape_ebrandon(location)
        listings.extend(ebrandon)
        if "brandon" in location.casefold():
            source_results.append(f"eBrandon: {len(ebrandon)} current/upcoming sale(s)")
        else:
            source_results.append("eBrandon: skipped (only covers Brandon, Manitoba)")
    except requests.RequestException as exc:
        source_results.append(f"eBrandon: unavailable ({exc})")

    try:
        craigslist = _scrape_craigslist(location)
        listings.extend(craigslist)
        source_results.append(f"Craigslist: {len(craigslist)} current/upcoming sale(s)")
    except requests.RequestException as exc:
        source_results.append(f"Craigslist: unavailable ({exc})")
    source_results.append(
        "Facebook: not scanned; public listings are not reliably accessible without Meta API access."
    )

    saved = _save_listings(listings)
    return saved, "; ".join(source_results)
