# Demonstrating actual backend concurrency

Open https://cn-adaptive-sliding-window.vercel.app/demo and sign in with the presenter password. Click **Run queue demo**. It starts 25 background synthetic clients (24BAD001–24BAD025) plus one tracked client (24BAD130), using real TCP sockets connected to the Python result server on loopback.

Show **Actual backend request evidence**:

- Background requests received: **25 / 25**.
- Distinct TCP connections: **26**, including the tracked client.
- Each row has its own request ID, actual TCP client address, server receive/admission timestamps, observed queue position, delivery latency and CRC/version checks.
- Queued rows become processing rows and then delivered rows as slots become available. Normal mode restores automatically.

Click **Download backend evidence (JSON)** to retain the run. On Render, open the backend service's Logs and filter **CN_EVIDENCE**. Match the run ID and request ID from the downloaded file. TCP_RECEIVED, TCP_ADMITTED and TCP_CLOSED are emitted inside the real socket handler, separately from the browser's display code. The rows are not advanced by a browser animation or timer.

The run counts a delivery as successful only when both the real server admission and the matching client's CRC/version-verified reply exist. Evidence access requires the existing presenter session. Only the latest four runs are retained in process memory; restarting the backend clears them, so download before a restart.

## Show a separate student using the queue

Keep the signed-in testing page open. In a second tab or another device, open the student portal and prepare roll **24BAD114** with a valid date entry. Start **Run queue demo**, then submit the student's Results form while the burst is active. A new row marked **24BAD114 · Student portal** appears automatically at the top of the same evidence table, with its own real TCP request ID, queue position, receive/admission timestamps and verified delivery. The generated demo remains 26 clients; the portal request count is shown separately.

Submit the same roll again to see a new request ID and another row. Portal requests appear even when no generated demo is running. The latest 100 portal TCP requests are retained independently of demo runs and included in the protected evidence download. A cached marksheet view reuses the verified result and does not invent another TCP request. Failed TCP attempts remain failed in the table even if the student page can recover using a current published snapshot. Restarting the server clears this in-memory history.

These are **25 simulated students making actual network requests**, not 25 humans or 25 separate physical devices. Student marks are synthetic. This bounded run demonstrates the admission window and queue behavior; it does not certify 1,000-student production capacity.
