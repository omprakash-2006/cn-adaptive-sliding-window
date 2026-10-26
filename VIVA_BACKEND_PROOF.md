# Demonstrating actual backend concurrency

Open https://cn-adaptive-sliding-window.vercel.app/demo and sign in with the presenter password. Click **Run queue demo**. It starts 25 background synthetic clients (24BAD001–24BAD025) plus one tracked client (24BAD130), using real TCP sockets connected to the Python result server on loopback.

Show **Actual backend request evidence**:

- Background requests received: **25 / 25**.
- Distinct TCP connections: **26**, including the tracked client.
- Each row has its own request ID, actual TCP client address, server receive/admission timestamps, observed queue position, delivery latency and CRC/version checks.
- Queued rows become processing rows and then delivered rows as slots become available. Normal mode restores automatically.

Click **Download backend evidence (JSON)** to retain the run. On Render, open the backend service's Logs and filter **CN_EVIDENCE**. Match the run ID and request ID from the downloaded file. TCP_RECEIVED, TCP_ADMITTED and TCP_CLOSED are emitted inside the real socket handler, separately from the browser's display code. The rows are not advanced by a browser animation or timer.

The run counts a delivery as successful only when both the real server admission and the matching client's CRC/version-verified reply exist. Evidence access requires the existing presenter session. Only the latest four runs are retained in process memory; restarting the backend clears them, so download before a restart.

These are **25 simulated students making actual network requests**, not 25 humans or 25 separate physical devices. Student marks are synthetic. This bounded run demonstrates the admission window and queue behavior; it does not certify 1,000-student production capacity.
