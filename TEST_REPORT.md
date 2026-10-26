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

## Full audit — 19 October 2026

Confirmed and fixed:
- A valid current snapshot for a different student could pass the cache guard. A regression seeded the wrong student's record and failed before the fix. The gate now binds the record to the requested registration, including cache delivery-source classification.
- Student queue polling ran every 70 ms even while a prior request was pending, accepted malformed/error responses, and could wait indefinitely or issue an extra result request on failure. Polling now waits for each response, pauses 500 ms, validates responses, retries the existing session at most twice on consecutive failures, and shows a recovery link.
- Queue progress no longer calls queue movement a percentage of processing or labels an already queued student as instant admission.
- Cloud status polling cannot overlap itself, and burst controls remain disabled while a demonstration is running.

Automated verification on the final code: **37 tests passed** (22 protocol/publication/HTTP tests, 2 cloud integration tests, 13 proxy/browser-script tests).

Coverage includes 130 simultaneous TCP clients with peak active work bounded by W=10; 130 result lookups using 45 HTTP workers; 25 concurrent browser queue sessions with W=3; matching registration and version; all 130 records' grades, status and SGPA; CRC retransmission and Hamming recovery; stale-version rejection; correction during delivery; disconnected waiter removal; unknown registration; authority outage; cache fallback; malformed/non-200 browser responses; double submission; protected cloud actions; real 26-client cloud-demo integration and automatic normal-mode restoration.

Manual browser checks used an isolated local database: 390px mobile homepage and result, real date validation (31 February rejected), whitespace/lowercase registration normalization, loaded images, no document-level horizontal overflow, scrollable marks table, back navigation, and every local correction/failure/traffic button. A student visibly queued at #48 during a 50-request burst and received the matching marksheet. Print-button activation was attempted; native PDF export could not be fully inspected through the browser automation surface. The external college circular returned HTTP 200 / application/pdf.

These bounded tests do not establish 1,000-user cloud capacity or guarantee zero bugs. Free hosting cold starts remain possible. DOB is a format/calendar check on synthetic records, not student authentication. Public sample marks remain unchanged by this audit.

## Per-request backend evidence — 26 October 2026

The protected cloud demonstration now records a bounded ledger from the actual TCP socket handler for the 25 background clients and one tracked client. Every row includes a unique request ID, peer address, server receive/admission times, observed queue status, completion latency, and client CRC/version checks. The JSON download is presenter-authenticated and uncached. The same run/request identifiers appear in independent `CN_EVIDENCE` log lines emitted by the TCP handler.

A request counts as delivered only when the matching TCP client verified its result and the server ledger confirms its admission. Evidence is limited to the most recent four explicitly registered demo runs; ordinary student requests are not added to the ledger. The student portal UI remains unchanged.

Validation: 22 protocol/publication/concurrency tests, 2 real HTTP/TCP integration tests, and 15 proxy/UI-script tests passed (39 total). The integration test verified 26 distinct real TCP connections, all 25 background registrations, distinct request IDs, admission timestamps, matching CRC/version-verified replies, and receive/admit/close log entries matching each downloaded evidence row. Unauthenticated evidence download returned 401. Normal W=10 was restored after the run.

See VIVA_BACKEND_PROOF.md for demonstration steps and the precise distinction between synthetic students and real socket traffic.
