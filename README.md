# YardScout

YardScout helps people find current and upcoming garage, yard, moving, and estate sales on a map. Users can add their own sales after signing in with Google. The private admin area provides location-based scraper controls and listing moderation.

## Features

- Browse, search, and map active listings
- Sign in with Google to post and delete your own sales
- Admin-only tools at `/admin` for location searches, run history, and listing moderation
- Public-source scraper adapters for eBrandon (Brandon, Manitoba) and Craigslist city feeds
- Original-source links on imported listings

The live-tested eBrandon adapter only covers Brandon, Manitoba. Craigslist city feeds can reject requests or have no matching city host; the admin run history reports those sources as unavailable rather than pretending the scrape succeeded. The scraper only publishes listings with a detectable current/upcoming date and a mappable location.

Facebook prohibits automated collection without its express permission. YardScout does not log in, access private groups, or bypass those controls. Connecting through Meta's official API would require separate Meta app credentials and access permissions, and is not part of this free-source version.

## Run locally

1. Install Python 3.10+ and PostgreSQL, then install dependencies:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Set environment variables in the terminal (or your deployment dashboard):

   ```text
   DATABASE_URL=postgresql://...
   SECRET_KEY=a-long-random-value
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ADMIN_EMAIL=devarshp610@gmail.com
   ```

   If `DATABASE_URL` is omitted, the app uses a local SQLite database at `DATABASE_PATH` (default `garage_sale_finder.db`). This is for development only; many free hosts erase local files when instances restart or redeploy.

3. Start the app:

   ```powershell
   python app.py
   ```

   Open `http://127.0.0.1:8080`. Add this callback URL to the Google OAuth client:
   `http://127.0.0.1:8080/auth/callback`.

## Free deployment starting point

For a no-trial web deployment, one option is a Render free web service connected to a Neon free PostgreSQL database. Both have recurring free tiers, but the service may sleep, first requests can be slow, usage/storage limits apply, and the database should be backed up. Render's free PostgreSQL database expires, so use an external persistent database such as Neon and configure `DATABASE_URL`.

GitHub Pages only serves static files; it cannot run this Flask app, its API, Google sign-in callbacks, or scraper. Keep the source in GitHub and connect the repository to Render to run the full app. A static-only version on Pages would need a separate backend and would not provide the current features by itself.

Free plans and quotas change. Review the providers' current terms before deploying:

- [Render free instance limits](https://render.com/docs/free)
- [Neon pricing and free plan](https://neon.com/pricing)
- [Neon scale-to-zero](https://neon.com/docs/introduction/scale-to-zero)

Set `SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `ADMIN_EMAIL` in the host's environment settings. Set the Google OAuth callback to `https://YOUR-HOST/auth/callback`. The scraper runs in the web process after an admin starts a job; it is not a durable scheduled worker, and a sleeping/restarted free instance can interrupt a run.

The included [Render Blueprint](./render.yaml) sets up the free web service. Create a Neon database separately, then provide its connection string and Google OAuth credentials when Render prompts for them.

## Project layout

- `app.py` — Flask routes, persistence, Google sign-in, admin authorization
- `scraper.py` — Public listing source adapters and import/deduplication
- `templates/index.html` — Public map and listing interface
- `templates/admin.html` — Private scraper and moderation dashboard
