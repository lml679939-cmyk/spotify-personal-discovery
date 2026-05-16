# Security Policy

## Supported Versions

This is a personal project. Only the latest version on the `main` branch is actively maintained.

| Version | Supported |
| ------- | --------- |
| latest (main) | Yes |
| older commits | No |

## Reporting a Vulnerability

Please **do not** open a public GitHub Issue for security vulnerabilities.

Instead, report them via one of the following:

- **GitHub Private Advisory**: [Security → Report a vulnerability](../../security/advisories/new)
- **Email**: lml679939@gmail.com

Include as much detail as possible:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

You can expect an initial response within **7 days**.

## Scope

This app handles:
- Spotify OAuth tokens (stored in memory only, never persisted to disk)
- Gemini API key (loaded from environment variables / Streamlit secrets)
- User-uploaded images (processed in-memory, sent to Google Gemini)
- IP-based geolocation (sent to ip-api.com when auto-detect is enabled)

Out of scope: vulnerabilities in third-party services (Spotify, Google, Streamlit Cloud).
