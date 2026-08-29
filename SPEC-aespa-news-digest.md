# Spec: aespa 每日新闻邮件

## 状态

已批准；核心代码已实现，真实 API 与 SMTP 冒烟测试待配置 GitHub Secrets。

## Objective

为个人用户构建一个无需常驻服务器的每日新闻摘要任务：GitHub Actions 每天 08:00（Asia/Shanghai）收集与韩国女团 aespa 相关的最新、可核实消息，使用用户指定的 OpenAI-compatible 摘要接口生成中文摘要，再通过 SMTP 发送邮件。

即使当天没有符合条件的新消息，也必须发送一封明确写有“今日暂无更新”的邮件。邮件保留原文标题、发布时间、来源名称和原文链接，方便核实。

## Assumptions

1. 当前工作区是一个需要从零创建的独立 Python 项目，不需要兼容既有应用框架。
2. 使用 Python 3.11+ 标准库完成核心逻辑，避免在 GitHub Actions 中引入不必要的运行时依赖。
3. 新闻源通过配置的 HTTPS RSS/Atom feed 提供；只接受配置的 feed 主机和可信媒体/官方来源域名。
4. 用户提供的摘要服务实现 OpenAI-compatible `POST /chat/completions`，使用 Bearer token；默认地址为 `https://a-ocnfniawgw.cn-shanghai.fcapp.run/v1`，默认模型为 `gpt-5-codex`。该协议兼容性需在用户配置 token 后通过手动 workflow 真实验证。
5. GitHub Actions 的定时触发允许出现几分钟延迟；邮件送达时间不作严格 SLA 承诺。
6. 状态文件提交到仓库，只保存文章指纹和必要的运行元数据，不保存邮件地址、token 或文章全文。

## Tech Stack

- Python 3.11+；`urllib`, `xml.etree.ElementTree`, `smtplib`, `email`, `json`, `zoneinfo` 等标准库。
- `unittest` 作为测试框架。
- GitHub Actions：`schedule` + `workflow_dispatch`，定时区为 `Asia/Shanghai`。
- JSON 配置和状态文件；不引入数据库或第三方 Python 依赖。
- 用户指定的 OpenAI-compatible Chat Completions 服务作为中文摘要提供方。

## Commands

```bash
# 运行全部测试
python -m unittest discover -s tests -v

# 本地执行一次（需要先设置环境变量；会发送邮件并更新状态）
PYTHONPATH=src python -m aespa_digest

# 本地 dry-run：抓取、筛选、生成邮件预览，但不发送邮件、不写入状态
PYTHONPATH=src python -m aespa_digest --dry-run
```

GitHub Actions 需要提供 `SUMMARY_API_KEY`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`MAIL_FROM` 和 `MAIL_TO`。非敏感的 `SUMMARY_BASE_URL`、`SUMMARY_MODEL`、`LOOKBACK_HOURS` 等通过仓库 Variables 或默认值配置。

## Project Structure

```text
src/aespa_digest/
├── __init__.py          # 包元数据
├── __main__.py          # python -m 入口
├── config.py            # 环境变量与 JSON 配置校验
├── models.py            # Article、Digest、运行结果等数据模型
├── sources.py           # HTTPS RSS/Atom 抓取和解析
├── qualification.py     # 相关性、可信来源、时间窗口和去重
├── state.py             # 原子读写 data/state.json
├── summarizer.py        # OpenAI-compatible Chat Completions 客户端
├── digest.py            # 中英文邮件文本/HTML 内容组装
├── mailer.py            # SMTP TLS/SSL 邮件发送
├── logging_utils.py     # JSON 结构化日志
└── runner.py            # 单次运行编排和错误边界

config/sources.json      # feed URL、关键词和可信域名（无秘密）
data/state.json          # 已发送文章指纹（可提交，不能含 PII/秘密）
tests/                   # 标准库单元测试和边界测试
.github/workflows/
└── daily-digest.yml     # GitHub Actions 定时和手动运行
tasks/                   # 规格批准后的计划和任务清单
```

## Code Style

- 使用 `snake_case` 函数和变量、`PascalCase` 数据模型、明确的返回类型。
- 纯逻辑优先使用小函数；网络、SMTP 和文件系统通过可注入边界隔离，方便测试。
- 不在业务模块中读取秘密；所有外部输入先校验，再进入业务逻辑。
- 失败信息面向操作者，日志使用稳定的 JSON `event` 字段，不记录 token、邮件地址或文章全文。

示例风格：

```python
def is_relevant(article: Article, keywords: tuple[str, ...]) -> bool:
    searchable_text = f"{article.title} {article.summary}".casefold()
    return any(keyword.casefold() in searchable_text for keyword in keywords)
```

## Testing Strategy

以快速、无网络副作用的单元测试为主，并在边界处使用 fake/stub：

- RSS/Atom 解析：RSS、Atom、命名空间、缺少字段、非法/非 HTTPS 链接。
- 资格筛选：aespa 关键词、可信域名、时间窗口、跨 feed 去重、未来时间和空内容。
- 状态：首次运行、重复运行、发送失败不写入已发送状态、损坏 JSON 拒绝启动、原子写入。
- 摘要客户端：请求 URL、Bearer header、响应解析、空响应、超时和服务错误；测试不调用真实 API。
- 邮件：无更新和有更新两种正文、HTML 转义、链接校验和邮件头注入防护；测试不连接真实 SMTP。
- 编排：成功发送后才持久化；部分 feed 失败可告警继续；所有 feed 失败时不发送“暂无更新”假消息。
- GitHub Actions：静态检查 workflow 中的时区、手动触发、权限、并发控制和 Secrets 引用。

验收前运行完整命令：

```bash
python -m unittest discover -s tests -v
```

真实端到端验证需要用户在 GitHub 仓库配置 Secrets 后手动触发 workflow；该验证不在本地测试中伪造为已完成。

## Boundaries

- **Always**：只通过 HTTPS 抓取外部 feed；验证 URL、时间、来源和响应大小；对文章内容和模型输出做长度限制和转义；发送成功后才更新状态；使用结构化日志；测试不访问真实邮件/API。
- **Ask first**：增加新的第三方服务、改变摘要模型、改变可信来源策略、保存新的个人数据、修改 GitHub Actions 写权限或状态持久化方式。
- **Never**：提交 token/SMTP 密码；把秘密打印到日志；向任意用户提供的 URL 发起请求；把未经转义的文章或模型输出作为 HTML；在发送失败时标记文章为已发送；为了通过检查而跳过或删除测试。

## Security and Reliability Decisions

- feed URL 和文章链接使用 HTTPS；feed 主机与文章来源域名采用 allowlist，降低 SSRF 和恶意来源风险。
- 每个 feed 设置请求超时、响应大小上限和有限重试；单个来源失败不阻断其他来源，但全部来源失败时运行失败。
- 摘要 prompt 明确把文章文本视为数据而非指令；模型返回只作为文本使用，经过长度限制后再放入纯文本/HTML 邮件。
- GitHub Actions 默认 `contents: read`；独立的状态持久化 job 才使用 `contents: write`。workflow 使用并发组避免两次运行同时覆盖状态。
- 摘要 API 失败时，邮件仍可包含中文故障说明和原始 feed 摘要；这类 fallback 会记录 warning，避免用户完全失去当天邮件。配置缺失或邮件发送失败则运行失败，状态不更新。

## Success Criteria

1. GitHub Actions 支持手动触发和每天 08:00（Asia/Shanghai）触发。
2. 每次运行只处理可信来源、最近时间窗口内且与 aespa 相关的消息，并在跨来源重复时只保留一条。
3. 有新消息时，邮件包含中文摘要、原文标题、来源、发布时间和 HTTPS 链接。
4. 没有新消息时，邮件明确包含“今日暂无更新”。
5. 同一文章在后续运行中不会重复发送；SMTP 失败不会消耗其已发送状态。
6. token、SMTP 凭据和收件地址均不进入源码、状态文件或日志。
7. 本地完整测试通过，且 workflow 可在用户配置 Secrets 后通过手动运行完成一次真实验证。

## Open Questions

- 可信来源的默认 allowlist 将以配置文件形式提供，用户可以自行增删；首次版本不抓取任意网页正文，只读取 RSS/Atom 摘要。
- GitHub 仓库需要由用户创建或提供；本地工作区只负责生成可推送的项目文件，不能代替用户配置仓库 Secrets。
