# Deployment preparation checks

These checks use the existing CN project and synthetic records, with no real college connection.

- The hosted Python entry point starts its actual TCP admission server and returns a successful health check.
- 25 concurrent direct backend queries returned correctly matched, version-verified results.
- 25 concurrent sessions completed the full Vercel-compatible proxy, query-start, queue-poll and framed TCP delivery path, with correctly matched and version-verified results.
- The college-style HTML, background image and sample marksheet passed through the proxy successfully.
- Three automated proxy tests passed, covering blocked administration/source paths, preserved query parameters, restricted forwarded headers and safe handling of missing/unreachable backend configuration.
- Hosted and proxy routes reject the correction lab and traffic controls.

No 1,000-client test was performed. No cloud deployment has been verified yet. The Vercel account and backend-hosting account still need an authenticated deployment connection. The configuration uses the free backend plan, with cold-start and ephemeral-storage limits described in README.md.
