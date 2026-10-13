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

The scraper currently has limited source and location coverage. It only imports listings when it can identify a future sale date and a usable location. Automated collection from Facebook is not included.

## Run and deploy

This is a learning project, not a one-click distribution package. Running your own instance requires setting up your own database, OAuth client, admin account, and hosting, then configuring each service for your own domain. Do not reuse another operator's credentials or deployment configuration.

For local experimentation, install the packages listed in `requirements.txt` and run the Flask app with your own environment configuration. The repository includes a Render Blueprint as a deployment example; review its settings and the host's current limits before using it. GitHub Pages cannot run Flask or the scraper.

## License and reuse

YardScout is published under the **PolyForm Noncommercial License 1.0.0**. You may inspect, study, and use the code for permitted noncommercial purposes, subject to the license. Commercial use requires separate permission from the copyright holder.

This is a **source-available** project, not an OSI-approved open-source project. The source is visible because this GitHub repository is public; a license does not technically prevent people from downloading or copying files. It sets the terms under which they may use and distribute them. If you need the source itself hidden, the repository must be private.

See [LICENSE](./LICENSE) for the complete terms. For permission to use the project commercially, contact the repository owner through GitHub.
