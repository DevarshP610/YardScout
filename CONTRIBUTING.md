# Contributing to YardScout

Thanks for helping improve YardScout. Contributions should make garage-sale discovery more useful, reliable, accessible, or easier to run.

## Before opening a change

1. Search existing issues and pull requests before starting work.
2. For a larger feature, open an issue first so the approach can be discussed.
3. Do not add scrapers for sources that prohibit automated access. Prefer documented feeds, APIs, or owner-authorized pages.
4. Never include credentials, private backups, database files, or personal data in a commit.

## Local setup

YardScout requires Python 3.12 or newer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:APP_ENV = "test"
$env:SECRET_KEY = "test-secret-key-for-yardscout-tests-only-123456"
python -m pytest -q
```

The test suite uses a temporary SQLite database. It does not need production credentials or a hosted database.

## Pull requests

- Keep changes focused and explain the user impact.
- Add or update tests for behavior changes.
- Update the README or relevant documentation when setup or public behavior changes.
- Run `python -m pytest -q`, `python -m py_compile app.py`, and `git diff --check`.
- Include screenshots or a short recording for meaningful UI changes.
- Use a clear title such as `feat: add saved listing filters` or `fix: validate sale dates`.

Maintainers review correctness, privacy, source permissions, accessibility, and operational risk before merging.
