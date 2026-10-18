# CN Campus Examination Result Portal

The student website deploys to Vercel. A single Python backend hosts the actual framed TCP server, FIFO admission window, CRC-32, Hamming status recovery, ARQ, publication revisions and SQLite result verification. This deployment keeps the existing college-style student interface and 130 synthetic registrations.

## Deployment status

Source preparation and local checks are complete. Vercel and backend account connections are required before publication. This folder is not evidence of a completed cloud deployment and does not yet have a permanent production URL.

## Deployment shortcuts

1. [Deploy the Python backend on Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fomprakash-2006%2Fcn-adaptive-sliding-window). The blueprint explicitly selects the free plan. Wait for a successful deployment and copy its HTTPS address.
2. [Deploy the student website on Vercel](https://vercel.com/clone?repository-url=https%3A%2F%2Fgithub.com%2Fomprakash-2006%2Fcn-adaptive-sliding-window&env=BACKEND_URL&envDescription=Paste%20the%20HTTPS%20address%20of%20your%20deployed%20Render%20backend). Enter the backend address as `BACKEND_URL`.

These links open account setup/deployment flows. They are not the running student website. The final student link is the actual `.vercel.app` URL returned after Vercel completes deployment.

## Why the backend runs separately

The current Python implementation maintains a single active window, waiting queue and TCP listener. Ordinary Vercel function instances can scale independently and stop when idle, so moving that in-memory controller into each function would create separate queues. The Vercel handler forwards student HTTP requests to one backend instead. The actual CN protocol continues to run on that backend, rather than being replaced with a visual simulation.

Official references:

- https://vercel.com/docs/functions
- https://vercel.com/docs/routing/rewrites
- https://render.com/docs/web-services

## Deploy the backend on Render

1. Publish this prepared source to the project repository, excluding runtime data and credentials.
2. Sign in to Render and create a Blueprint using `render.yaml`, or create a Python Web Service manually.
3. Root directory: `backend`.
4. Build command: `python -m compileall -q .`.
5. Start command: `python -u hosted_launch.py`.
6. Health check: `/healthz`.
7. Choose the **Free** service plan. Do not select a paid plan or add paid resources without approval.
8. After a successful deployment, copy the exact backend HTTPS URL shown by Render.

The hosted entry point binds HTTP to `0.0.0.0:$PORT`; the TCP listener remains on loopback. Testing, traffic injection, the student directory and publication mutation routes are unavailable on this hosted entry point.

## Deploy the student website on Vercel

1. Sign in to Vercel and import this project's repository.
2. Use the repository root as the project root and **Other** as the framework.
3. Add `BACKEND_URL` to the Vercel project's Production and Preview environment variables. Its value must be the exact backend HTTPS origin, such as the URL copied from Render, without any extra path or credentials.
4. Deploy and wait for Vercel to report success.
5. Open the actual returned Vercel URL and verify the form, query/poll flow and marksheet.

The Vercel source excludes the backend folder from its deployment bundle. Student pages and assets pass through an allowlisted proxy. The proxy blocks local administration paths and never forwards incoming administration tokens.

## Free hosting limits

The Vercel URL and backend URL remain associated with their deployed services; they do not change each time the Mac restarts. The Mac does not have to remain on after both cloud services have deployed successfully.

Render Free currently sleeps after 15 minutes without incoming traffic and can take roughly a minute to wake on the next request. It has usage limits and no guarantee of uninterrupted availability. Its local filesystem is ephemeral, so SQLite revisions reset from the bundled sample roster after a restart/redeploy. The hosted student service provides no publishing controls, so the bundled sample marks remain the baseline. Durable real publication history would require persistent storage before college integration.

For a presentation, open the hosted website a few minutes in advance. Keep the complete local demo as a backup. Official limits: https://render.com/docs/free . No 1,000-client capacity claim has been established.

## Sample input

Registration: **24BAD025**. Date: **15-05-2004**.

Valid sample registrations range from **24BAD001 through 24BAD130**. Dates receive calendar/format validation only, not real college DOB authentication. All names and marks are synthetic. No actual college database is connected.

## Verification

Run proxy checks using `npm test`. The Node runtime is 22.x on Vercel. The backend uses Python's standard library.

Local hosting checks use isolated ports and a temporary publication database. This avoids modifying the running local demo. The original local correction lab remains separate at http://127.0.0.1:8082/demo when launched with testing enabled.
