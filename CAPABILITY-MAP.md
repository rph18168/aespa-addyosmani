# 能力地图：aespa 每日新闻邮件

状态：已确认（GitHub Actions + 可配置的 OpenAI-compatible 摘要服务）

## 模块

| 模块 id | 职责 | 依赖 |
|---|---|---|
| `state-store` | 使用可审阅的 JSON 文件保存已发送文章标识和幂等状态，并在 GitHub Actions 中持久化 | — |
| `source-ingestion` | 从配置的 HTTPS RSS/Atom 来源抓取文章，并规范化标题、摘要、发布时间、链接和来源 | — |
| `article-qualification` | 按 aespa 相关性、来源可信度和发布时间筛选文章；去重并写入状态 | `state-store`, `source-ingestion` |
| `summary-generation` | 为筛选后的文章生成中文摘要，同时保留原文标题和来源链接 | `article-qualification` |
| `digest-delivery` | 组装“有更新/今日暂无更新”邮件，并通过 SMTP 发送 | `summary-generation` |
| `schedule-and-runner` | 提供单次运行命令，并由 GitHub Actions 每天 08:00（Asia/Shanghai）执行，同时支持手动触发；输出结构化运行日志 | `state-store`, `article-qualification`, `summary-generation`, `digest-delivery` |

## 构建顺序

`state-store` + `source-ingestion` → `article-qualification` → `summary-generation` → `digest-delivery` → `schedule-and-runner`

## 运行平台决策

- 使用 GitHub Actions 的 `schedule` 和 `workflow_dispatch`，定时 workflow 只在默认分支运行。
- 使用 `timezone: Asia/Shanghai` 表达北京时间 08:00；接受 GitHub Actions 调度和外部来源响应造成的几分钟延迟。
- Runner 是临时环境；仅保存文章指纹和运行元数据的 JSON 状态文件提交回仓库，避免引入外部数据库。
- 摘要服务通过 `SUMMARY_BASE_URL`、`SUMMARY_MODEL` 和 `SUMMARY_API_KEY` 配置；当前默认值分别为用户提供的接口地址和 `gpt-5-codex`，API key 只放在 GitHub Secrets。
- workflow 默认使用最小的 `contents: read` 权限；仅状态持久化 job 使用 `contents: write`。

## 跨模块约束

- 外部文章内容是不可信输入；只允许配置的 HTTPS 来源，设置请求超时和响应大小上限。
- SMTP 凭据、收件地址和摘要服务凭据只从环境变量读取，不进入源码或日志。
- 邮件正文使用纯文本和经过转义的 HTML；文章链接只接受 HTTPS。
- 运行必须幂等：重复执行不会重复发送已发送过的文章。
- 每次运行记录抓取数量、筛选数量、摘要数量、发送结果和关联运行 ID，但不记录邮件地址、凭据或文章全文。
