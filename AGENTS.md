# Project: aespa Daily News Digest

## Tech Stack

- Python 3.11+ standard library only
- `unittest` for tests
- GitHub Actions for the daily scheduled job
- JSON for source configuration and persistent sent-item state

## Commands

- Test: `python -m unittest discover -s tests -v`
- Compile check: `python -m compileall -q src tests`
- Local dry-run: `PYTHONPATH=src python -m aespa_digest --dry-run`
- Local run: `PYTHONPATH=src python -m aespa_digest`

## Code Conventions

- Use `snake_case` for functions and variables, `PascalCase` for data models, and type annotations on public functions.
- Keep pure parsing, filtering, rendering, and validation functions separate from network, SMTP, and file-system boundaries.
- Use dependency injection for external calls so tests never need a real API, feed, or SMTP account.
- Treat feed content and model output as untrusted text; bound lengths and escape HTML output.

## Boundaries

- Never commit API tokens, SMTP passwords, or real `.env` files.
- Read secrets only from environment variables or GitHub Secrets.
- Only fetch configured HTTPS feed hosts and only emit HTTPS article links.
- Do not mark articles as sent until the email send succeeds.
- Do not skip, weaken, or delete tests to make a check pass.
- Keep GitHub Actions permissions read-only except for the isolated state-persistence job.

## Verification

Every behavior change needs a test. Run the focused test during each implementation slice, then run the full test suite and compile check before handoff. Real API and SMTP smoke tests require user-provided GitHub Secrets and must be reported separately from local tests.
