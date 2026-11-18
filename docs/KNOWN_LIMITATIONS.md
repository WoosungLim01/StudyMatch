# Known limitations

What the current version does not do yet, or does on purpose in a limited way. The plan for closing the important ones is in the README's Roadmap.

- **The admin password is a temporary `1234` until `ADMIN_PASSWORD` is set on Render.** Anyone who reads this repo can open the admin page until then.
- **Real students can be placed with synthetic students.** The live database still holds the 36 synthetic seed students, and a real sign-up in a course with seed groups can join one of them (EC-01 in the DS 440 Report 5 edge-case tests).
- **Sign-up says the code was emailed even when sending failed** (EC-04). The student waits for a code that never arrives.
- **Admin access is one shared password.** It's simple, but the app can't tell which teammate did what, and the wrong-password counter is kept in memory, so it resets when the server restarts.
- Group chat has no read receipts, notifications, editing, or deleting your own messages. There's no per-user send or upload rate limit, and each poll syncs with Turso, which is fine at the current scale.
- Attachments are capped at 10 MB, which fits photos and short clips but not most phone videos. Every upload also counts against the Turso plan's storage. Larger files would need object storage such as Cloudflare R2.
- No forgot-password flow, and no way to change a password. The 6-character minimum is deliberate.
- Survey answers can't be retaken or edited after submission.
- Verification codes don't expire. A code stays valid until it's used or replaced. The wrong-code lockout is kept in memory and resets when the server restarts.
- Matching is homogeneous by design, which can create echo-chamber effects over time. This is tracked as a future outcome metric rather than constrained away.
- No balancing across groups, and no per-student axis weights or dealbreakers.
- Response-quality flags catch straight-lining and contradictory answers, but not random clicking (about 3% of responses are flagged).
- The feedback loop is not built. `group_feedback` is collected but doesn't change matching.
- `session_mode` and `collaboration` are calibrated against Big Five proxies, not measures of those constructs. See [`docs/SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md).
