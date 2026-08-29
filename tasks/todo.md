# Task List: aespa 每日新闻邮件

## Phase 1: Foundation

- [x] Task 1: Establish project skeleton, configuration contract, and test harness
  - Acceptance: Python package imports from `src`; environment/config validation rejects missing required values and unsafe URLs; focused tests exist.
  - Verify: `python -m unittest tests.test_config -v` and `python -m compileall -q src tests`
  - Files: `pyproject.toml`, `.gitignore`, `src/aespa_digest/config.py`, `src/aespa_digest/models.py`, `tests/test_config.py`
  - Dependencies: None
  - Estimated scope: Medium

- [x] Task 2: Implement RSS/Atom ingestion and article qualification
  - Acceptance: RSS and Atom entries normalize to the same `Article` model; only relevant, trusted, recent HTTPS articles remain; duplicates collapse deterministically; partial feed errors are represented.
  - Verify: `python -m unittest tests.test_sources -v`
  - Files: `src/aespa_digest/sources.py`, `src/aespa_digest/qualification.py`, `tests/test_sources.py`
  - Dependencies: Task 1
  - Estimated scope: Medium

- [x] Task 3: Implement durable sent-item state and idempotency
  - Acceptance: Missing state loads empty; invalid state fails closed; writes are atomic and bounded; state changes only after successful delivery in the runner contract.
  - Verify: `python -m unittest tests.test_state -v`
  - Files: `src/aespa_digest/state.py`, `tests/test_state.py`
  - Dependencies: Task 1
  - Estimated scope: Small

## Checkpoint: Foundation

- [x] Tasks 1–3 focused tests pass
- [x] Compile check passes
- [x] No secrets or live network calls are present in tests

## Phase 2: Digest Delivery

- [x] Task 4: Implement the OpenAI-compatible summary adapter
  - Acceptance: Client sends a bounded JSON Chat Completions request with Bearer authentication, parses a non-empty text response, and surfaces timeout/HTTP/malformed-response errors without logging secrets.
  - Verify: `python -m unittest tests.test_summarizer -v`
  - Files: `src/aespa_digest/summarizer.py`, `tests/test_summarizer.py`
  - Dependencies: Task 1
  - Estimated scope: Medium

- [x] Task 5: Implement digest rendering and SMTP delivery
  - Acceptance: New-item and no-update emails render Chinese text plus title/source/time/HTTPS link; HTML is escaped; SMTP supports STARTTLS/SSL; header injection is rejected.
  - Verify: `python -m unittest tests.test_digest_mailer -v`
  - Files: `src/aespa_digest/digest.py`, `src/aespa_digest/mailer.py`, `tests/test_digest_mailer.py`
  - Dependencies: Tasks 1, 2, 4
  - Estimated scope: Medium

- [x] Task 6: Implement single-run orchestration, CLI, and structured logs
  - Acceptance: Runner sends a daily digest, sends an explicit no-update email after a successful source pass, persists state only after mail success, supports `--dry-run`, and emits JSON logs with a run ID and counts.
  - Verify: `python -m unittest tests.test_runner -v` and `PYTHONPATH=src python -m aespa_digest --help`
  - Files: `src/aespa_digest/logging_utils.py`, `src/aespa_digest/runner.py`, `src/aespa_digest/__main__.py`, `tests/test_runner.py`
  - Dependencies: Tasks 2–5
  - Estimated scope: Medium

## Checkpoint: Core Features

- [x] Full test suite passes
- [x] Fake end-to-end run covers both new articles and no-update email
- [x] Failed mail send leaves state unchanged

## Phase 3: Automation and Handoff

- [x] Task 7: Add GitHub Actions automation
  - Acceptance: Workflow runs on `schedule` at 08:00 Asia/Shanghai and `workflow_dispatch`; uses concurrency; runtime secrets are referenced from Secrets; state persistence is isolated to a write-permission job.
  - Verify: inspect YAML and run `python -m unittest discover -s tests -v`
  - Files: `.github/workflows/daily-digest.yml`, `data/state.json`
  - Dependencies: Task 6
  - Estimated scope: Medium

- [x] Task 8: Add source configuration and setup documentation
  - Acceptance: A user can create a GitHub repository, configure required Secrets/Variables, run the workflow manually, and understand the unverified real-provider smoke test.
  - Verify: `git diff --check` and review every documented command against the project files
  - Files: `config/sources.json`, `.env.example`, `README.md`
  - Dependencies: Tasks 1, 2, 6, 7
  - Estimated scope: Medium

## Checkpoint: Complete

- [x] `python -m unittest discover -s tests -v`
- [x] `python -m compileall -q src tests`
- [x] `git diff --check`
- [x] No secrets in tracked files
- [ ] Real GitHub Actions API/SMTP run remains pending until the user adds Secrets
