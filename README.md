# YardScout

Find upcoming garage sales on a map, search listings, or submit a sale.

**Live site:** https://yardscout.onrender.com

## Features and coverage

- Public map and listing search, built with Flask, Leaflet, and OpenStreetMap.
- Separate admin tools for moderation, manual entry, screenshot text extraction, and scraper runs.
- Scraper sources: eBrandon around Brandon, Manitoba; owner-authorized GarageSaleFinder pages in the U.S.; optional Ticketmaster event lookup.
- The resumable regional sweep checks 70 hubs, not every town or website. Facebook, Kijiji, Craigslist, and other sources are not scanned without approved access.

## Run locally

Install `requirements.txt`, configure your own database and Google OAuth credentials, then run the Flask app. Never reuse or publish another operator's credentials. GitHub Pages cannot host this Flask app.

Main files: `app.py` (routes and database), `scraper.py` (source adapters), `templates/index.html` (public site), and `templates/admin.html` (admin tools).

## Hosting and data safety

Render's free web service has ephemeral storage. Use PostgreSQL for hosted data; SQLite is for local development and can be lost on Render restarts or deploys. The app's admin **Data safety** panel shows the selected database and provides a private JSON backup.

For a no-cost hobby setup, Render plus a free external PostgreSQL plan may work, but check current provider limits and retention before relying on it. Render's free PostgreSQL databases expire after 30 days.

Before switching databases:

1. Download a backup from **Admin → Data safety** and keep it private.
2. Create an empty PostgreSQL database; set its connection string as `DATABASE_URL` in Render. Never commit or share the value.
3. Restore locally from the repository root:

   ```powershell
   $env:DATABASE_URL = Read-Host "Paste the database connection string"
   try {
     .\.venv\Scripts\python.exe scripts\restore_backup.py .\yardscout-backup-YYYYMMDDTHHMMSSZ.json
   } finally {
     Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
   }
   ```

   The restore tool refuses to overwrite a non-empty database unless `--replace` is explicitly supplied.
4. Set the same `DATABASE_URL` in Render, redeploy, confirm the admin panel reports PostgreSQL, and download a fresh backup.

Keep a backup outside the hosting provider. YardScout does not back up data automatically or guarantee recovery from an inaccessible service.

## Roadmap timeline

Planning estimate: **33–50 focused hours**, about **6–13 working weeks at 4–6 hours per week**. The schedule below allows 10 weeks; school, testing, and source permissions can shift it. A further approved source adapter adds 3–6 hours and 2–4 commits.

| When | Work | Estimate |
|---|---|---:|
| Weeks 1–2 | Finish persistent database setup and recovery checks; add automated tests on pushes and pull requests. | 6–9 hours |
| Weeks 3–4 | Improve scraper source-level reporting, retries, and interrupted-run handling. | 5–7 hours |
| Weeks 5–6 | Research Canadian sources; build the first adapter only if access and listing quality are verified. | 5–9+ hours |
| Weeks 7–8 | Add map filters and listing-quality feedback, including duplicate and stale checks. | 9–13 hours |
| Weeks 9–10 | Add saved sales, address mobile/accessibility issues, and prepare a release and feedback path. | 8–12 hours |

Work in small, testable commits; keep unfinished work off `main`. See [ROADMAP.md](./ROADMAP.md) for milestone details and project guardrails.

## License

Licensed under the [PolyForm Noncommercial License 1.0.0](./LICENSE). Commercial use requires permission from the copyright holder. This is source-available, not OSI-approved open source; see the license for terms.
