# Deployment and cloud-demo checks

All records are synthetic; no real college database is connected.

## Existing live deployment — 18 October 2026

- Vercel student website and Render Python/TCP backend deployed successfully.
- Browser lookup for 24BAD025 displayed the expected marksheet through Vercel.
- 25 concurrent Vercel query-start/poll sessions returned correctly matched data, all with CRC and publication-version verification. One delivery recovered using ARQ. No waiting position was captured in that run.
- Legacy demo, telemetry, burst-control and source-data URLs returned 404 publicly.

## Protected queue-demo update

- Five Node proxy tests pass: private/source path restrictions, preserved query parameters, restricted cookies/headers, secure-cookie forwarding, same-origin POST enforcement, request-size bounds and backend errors.
- Two Python HTTP/TCP integration tests pass on disposable local ports/database. Tests cover unauthenticated controls, missing Origin, wrong passwords, tampered sessions, blocked legacy controls, invalid actions and overlapping bursts.
- The integrated queue run observed actual waiting, completed 26/26 CRC/version-verified deliveries, tracked 24BAD130 in the queue, automatically restored W=10 and verified a subsequent normal student lookup.
- The page's embedded JavaScript passes Node syntax checking.
- Hosted presenter login additionally requires a private CN_DEMO_PASSWORD in Render. The owner must set this credential; it is not included in the source.

No 1,000-client capacity test has been performed. Local integration results do not establish cloud capacity or uninterrupted uptime. The backend free plan can sleep after inactivity and its SQLite files are ephemeral.
