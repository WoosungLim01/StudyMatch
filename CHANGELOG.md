# Changelog

All notable changes to StudyMatch. Dates are when the change landed in the repository.

## [0.1.0] - 2026-11-17 · Fall 2026 prototype

The first tagged version: the app as deployed at the end of the DS 440 capstone semester.

### Security
- Admin page and every `/api/admin/*` route are now behind a shared admin password (`ADMIN_PASSWORD`, with a temporary fallback until it is set on the host). Student names, emails and group names are escaped on the admin page.

### Added
- Product README with demo video, research summary, roadmap and a section for universities.
- `LICENSE` (AGPL-3.0), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and pull request templates.
- `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/KNOWN_LIMITATIONS.md` and `docs/RESEARCH.md`, split out of the old README.

## November 2026
- Confirmed meetings show on a Home calendar.
- README redesign with feature screenshots and dark-mode variants.

## October 2026
- Meeting-time polls in group chat rooms.
- Dark mode with a system, light or dark choice in Account.
- Softer lavender-gray restyle and a login hero image.
- Image, video and file attachments in group chat; admin groups kept separate from matching.
- Group chat for each study group.
- Google sign-in; email verification with a 6-digit code sent through Resend; deletion notices.
- Account page; Turso-hosted database; Python pinned to 3.10 for Render.
- Synthetic data calibrated on real survey datasets.

## September 2026
- Group formation with an integer program (OR-Tools CP-SAT) and theory-based study types, with a study-type map on the admin page.
- 24-item survey informed by the MSLQ, scored on six study-style axes.
- New visual design.
- Login, survey and home flow; intake survey and admin web app.
- First prototype, sample data generator and SQLite database.
