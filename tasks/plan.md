# Implementation Plan: aespa 每日新闻邮件

## Overview

构建一个独立的 Python 3.11+ 命令行任务：从配置的 HTTPS RSS/Atom 来源抓取 aespa 新闻，按可信来源、关键词和时间窗口筛选并去重，调用用户提供的 OpenAI-compatible Chat Completions 接口生成中文摘要，通过 SMTP 发送每日邮件，并由 GitHub Actions 每天 08:00（Asia/Shanghai）触发。

## Architecture Decisions

- **标准库优先**：使用 Python 标准库，避免空工作区引入依赖、安装脚本和供应链风险。
- **RSS/Atom 优先**：首版只读取配置的 feed 摘要，不抓取任意网页正文；文章来源域名由 allowlist 控制。
- **可替换摘要客户端**：以 `SUMMARY_BASE_URL`、`SUMMARY_MODEL` 和 `SUMMARY_API_KEY` 配置 OpenAI-compatible Chat Completions，默认使用用户提供的地址和 `gpt-5-codex`。没有真实 token 时只做请求结构测试。
- **JSON 状态**：GitHub Runner 是临时环境，使用可审阅的 `data/state.json` 保存文章指纹；发送成功后才写入，独立 job 提交状态。
- **显式失败策略**：全部 feed 失败或 SMTP/配置失败时任务失败，避免发送虚假的“暂无更新”；部分 feed 失败继续运行并在邮件和日志中告警；摘要 API 单条失败时使用明确标注的原文摘要 fallback。
- **最小权限**：主 job 使用 `contents: read`；状态提交 job 单独使用 `contents: write`，并通过并发组避免状态竞争。

## Dependency Graph

```text
models/config
    ├── source ingestion ──┐
    ├── state store ───────┼── qualification ── summarizer ── digest/mailer
    └──────────────────────┴──────────────────────────────────────┬
                                                                   └── runner/CLI
                                                                        └── GitHub Actions
```

## Task List

### Phase 1: Foundation

- [x] Task 1: Establish project skeleton, configuration contract, and test harness
- [x] Task 2: Implement RSS/Atom ingestion and article qualification
- [x] Task 3: Implement durable sent-item state and idempotency

### Checkpoint: Foundation

- [x] Focused tests for Tasks 1–3 pass
- [x] `python -m compileall -q src tests` passes
- [x] No network or secret is needed by the foundation tests

### Phase 2: Digest Delivery

- [x] Task 4: Implement the OpenAI-compatible summary adapter
- [x] Task 5: Implement digest rendering and SMTP delivery
- [x] Task 6: Implement single-run orchestration, CLI, and structured logs

### Checkpoint: Core Features

- [x] Full local test suite passes
- [x] A fake feed + fake summarizer + fake mailer exercise the end-to-end runner
- [x] Failed delivery leaves sent state unchanged

### Phase 3: Automation and Handoff

- [x] Task 7: Add GitHub Actions schedule, manual trigger, permissions, concurrency, and state persistence
- [x] Task 8: Add source configuration, setup documentation, and operational checklist

### Checkpoint: Complete

- [x] `python -m unittest discover -s tests -v` passes
- [x] `python -m compileall -q src tests` passes
- [x] Workflow YAML references only Secrets/Variables for runtime credentials
- [x] Manual GitHub Actions run is documented as the final real API/SMTP verification

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| GitHub schedule delay or dropped run | Medium | Keep `workflow_dispatch`, use an explicit timezone, log run ID, and document approximate delivery time |
| Feed format or source changes | Medium | Support RSS and Atom by local-name parsing, isolate per-feed failures, keep URLs configurable |
| Third-party endpoint is not fully Chat Completions compatible | High | Isolate the HTTP adapter, make base URL/model configurable, add a manual smoke test, and fail with actionable errors |
| Duplicate email after rerun | High | Persist bounded article fingerprints only after successful SMTP delivery; serialize workflow runs |
| Malicious feed/model text in email | Medium | Treat external text as untrusted, cap sizes, strip input HTML, and escape HTML output |
| Secret leakage | High | GitHub Secrets/environment variables only; never log request headers or credentials; keep workflow permissions minimal |
| All feeds unavailable but email says no updates | High | Fail when every configured feed fails; only send “暂无更新” after at least one source succeeds |

## Open Questions

- 默认可信来源名单会以 `config/sources.json` 提供，用户可在 GitHub 中修改后提交；首版不自动发现新来源。
- 真实 SMTP 服务商、收件地址和摘要 token 由用户在 GitHub 仓库中配置，不写入本地项目。
