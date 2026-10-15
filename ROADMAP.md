# YardScout roadmap

Planning baseline: one student working about 4–6 focused hours each week, keeping recurring costs at $0. Estimates are solo development time, not calendar promises; school, testing, provider approvals, and changing free-tier limits can extend them.

Small, reviewable commits should each leave the project in a testable state. Commit counts below are ranges, not a quota.

| Order | Milestone | Definition of done | Estimated effort | Micro-commits |
|---|---|---|---:|---:|
| 1 | Hosting and data safety | Use a persistent free external PostgreSQL service for the hosted app; provide an admin-only backup download and a guarded restore tool; verify a restore before trusting the hosted database. | 3–5 hours | 3–4 |
| 2 | Automated checks | Run tests and syntax checks on pushes and pull requests; require passing checks before merging to `main`. | 3–4 hours | 2–3 |
| 3 | Scraper run quality | Report per-source outcomes, errors, progress, and retry state; test interrupted and repeated runs without overstating coverage. | 5–7 hours | 4–5 |
| 4 | Canadian sources | Research one source at a time; add only a free feed/API or source with clearly approved access, relevant sale events, and testable examples. Budget 2–3 hours for source research and 3–6 hours per accepted adapter. | 5–9+ hours | 2–4 per adapter |
| 5 | Map and listing search | Add date, distance, and keyword filters that affect the actual results; validate map/list synchronization. | 5–7 hours | 4–5 |
| 6 | Listing quality | Add user reports, admin review actions, and duplicate/stale listing checks where source data permits. | 4–6 hours | 3–4 |
| 7 | Saved sales | Let users bookmark listings and return to them without adding a paid service. | 3–4 hours | 2–3 |
| 8 | Mobile and accessibility | Check keyboard navigation, focus, contrast, reduced motion, map controls, and narrow layouts; fix and retest issues found. | 3–5 hours | 3–4 |
| 9 | Release and feedback | Add a simple issue-reporting path, clear privacy/source coverage notes, and a repeatable release checklist. | 2–3 hours | 2–3 |

## Suggested sequence

- **Week 1:** Finish the persistence and recovery setup described in the hosting section of `README.md`.
- **Week 2:** Add CI so every push runs the existing tests.
- **Weeks 3–4:** Improve scraper reporting and failure recovery.
- **Weeks 5–6:** Research Canadian sources and implement only the first source that passes access and relevance checks.
- **Weeks 7–8:** Add useful map filters and listing-quality feedback.
- **Weeks 9–10:** Add favorites, address accessibility/mobile issues, then release and collect feedback.

At two focused hours per week, expect the baseline to take roughly 17–25 weeks. The milestones total about 33–50 focused hours and 25–35 micro-commits, including research and the first approved source adapter. Each additional approved adapter adds about 3–6 hours and 2–4 commits. Stop at completed milestones when school gets busy rather than leaving unfinished features on `main`.

## Guardrails

- The current 70-hub regional sweep checks enabled sources only; it does not cover every North American town or website. Do not describe it as an exhaustive crawl.
- Keep wide scans manual and resumable until hosting can reliably run background work at no cost.
- Verify provider pricing, free-tier caps, and data-retention policies before committing to a service; free offers can change.
- A public web page is not automatically permission to collect and republish its listings. Require a suitable official API/feed or clear authorization.
- Keep credentials and downloaded backup data out of GitHub. Store at least one backup outside the hosting provider.
