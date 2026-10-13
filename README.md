# YardScout

YardScout is a garage-sale discovery project: browse local listings on a map, search by keyword, and add a sale after signing in.

**Live site:** https://yardscout.onrender.com

## What it demonstrates

- A map-based interface built with Leaflet and OpenStreetMap
- A Flask application with JSON endpoints and Google sign-in
- Persistent listing storage with PostgreSQL, with SQLite available for local experimentation
- A restricted admin area for reviewing listings and starting location-based searches
- Public-source listing imports with source links and date/location checks

## Project tour

Use the repository to explore how the pieces fit together:

1. Start with `templates/index.html` to see the public map, listing form, search, and browser-side API calls.
2. Follow those requests into `app.py` to see route handling, authentication, database operations, and admin access checks.
3. Read `scraper.py` to see how supported public sources are queried, listings are parsed, and results are saved.
4. Review `templates/admin.html` for the separate admin interface.

The location picker uses Photon with OpenStreetMap data to suggest US and Canadian cities and towns; it is not limited to a hardcoded list of 50 markets. That expands place selection, not listing-source coverage. The verified garage-sale source is eBrandon for Brandon, Manitoba. An optional `TICKETMASTER_API_KEY` enables exact-phrase searches through Ticketmaster's official event API, but Ticketmaster is not a general garage-sale feed and may return no relevant events.

Other sites are deliberately not scraped: GarageSaleFinder's terms prohibit automated collection; Used.ca's `robots.txt` excludes search routes; Meta requires separate express written permission for automated collection; and no verified Kijiji public event feed is available. Kijiji search results can be ordinary item ads rather than dated garage-sale events. Craigslist is not searched without authorization, and eBay item ads are not treated as sale events. Admins can review a public listing themselves and add it with its source link through the existing manual-entry tools.

Admins can also create a listing from a screenshot in the admin page. Text recognition runs in the admin's browser with Tesseract.js; the image is not uploaded to YardScout or sent to an OCR service. The OCR library and language data are loaded from a public CDN. Review the extracted title, date, details, and location before saving. Add the original listing link manually when available.

## Run and deploy

This is a learning project, not a one-click distribution package. Running your own instance requires setting up your own database, OAuth client, admin account, and hosting, then configuring each service for your own domain. Do not reuse another operator's credentials or deployment configuration.

For local experimentation, install the packages listed in `requirements.txt` and run the Flask app with your own environment configuration. The repository includes a Render Blueprint as a deployment example; review its settings and the host's current limits before using it. GitHub Pages cannot run Flask or the scraper.

## License and reuse

YardScout is published under the **PolyForm Noncommercial License 1.0.0**. You may inspect, study, and use the code for permitted noncommercial purposes, subject to the license. Commercial use requires separate permission from the copyright holder.

This is a **source-available** project, not an OSI-approved open-source project. The source is visible because this GitHub repository is public; a license does not technically prevent people from downloading or copying files. It sets the terms under which they may use and distribute them. If you need the source itself hidden, the repository must be private.

See [LICENSE](./LICENSE) for the complete terms. For permission to use the project commercially, contact the repository owner through GitHub.
