# Security Policy

## Supported Versions

This project is early-stage. Security fixes target the current `main` branch.

## Reporting a Vulnerability

Please open a private security advisory if the repository host supports it. If
not, contact the maintainer privately before publishing details.

Include:

- affected version or commit;
- deployment shape;
- steps to reproduce;
- impact;
- whether secrets, local files, or remote execution are involved.

## Operational Guidance

- Do not expose the web console directly to the internet.
- Put the console behind a trusted reverse proxy or VPN if remote access is
  needed.
- Keep `.env`, Bazarr config, queue files, and logs out of public issues.
- Use read-only mounts for Bazarr config where possible.
- Rotate Gemini, TMDB, and Bazarr API keys if they are accidentally logged or
  committed.

The worker intentionally does not implement user authentication yet. Treat it as
a LAN/admin tool.
