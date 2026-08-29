# aespa 每日新闻邮件

这是一个无常驻服务器的每日新闻摘要程序：GitHub Actions 每天 08:00（北京时间）读取配置的 RSS/Atom，筛选可信来源中的 aespa 更新，经用户指定的 OpenAI-compatible Chat Completions 接口生成中文摘要，再通过 SMTP 发邮件。

即使没有符合条件的新文章，也会发送包含“今日暂无更新”的邮件。只有至少一个来源成功读取、且没有符合条件的新文章时，才会发送这封无更新邮件；如果所有来源都失败，任务会失败并避免发送误导性邮件。

## 当前默认配置

- 摘要地址：`https://a-ocnfniawgw.cn-shanghai.fcapp.run/v1`
- 模型：`gpt-5-codex`
- 来源：Soompi、Billboard、The Korea Herald K-pop、Yonhap News English、韩联社中文文娱体育 RSS
- 时间窗：最近 36 小时，并允许最多 2 小时的未来时间容差
- 每次最多发送 20 条去重后的文章

来源和可信域名在 [`config/sources.json`](config/sources.json) 中维护。程序只接受 HTTPS feed 和 HTTPS 原文链接，不抓取任意网页正文。

## GitHub Actions 部署

1. 在 GitHub 创建一个新仓库，把本项目推送到默认分支。
2. 在仓库 `Settings → Secrets and variables → Actions` 的 **Secrets** 中添加：

   - `SUMMARY_API_KEY`：摘要服务 token
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `MAIL_FROM`
   - `MAIL_TO`

   不要把 token 或 SMTP 密码写进代码、Issue、日志、状态文件或聊天消息。

3. 如需覆盖非敏感默认值，可在 **Variables** 中添加 `SUMMARY_BASE_URL`、`SUMMARY_MODEL`、`SMTP_SECURITY`、`LOOKBACK_HOURS`、`MAX_ARTICLES` 或 `REQUEST_TIMEOUT_SECONDS`。不设置时使用上面的默认值。
4. 打开 `Actions → aespa daily news digest`，先选择 **Run workflow** 做一次真实验证。成功后，运行会把仅含文章指纹和时间戳的 `data/state.json` 提交回仓库。

定时定义在 [`.github/workflows/daily-digest.yml`](.github/workflows/daily-digest.yml) 中：`0 8 * * *` 配合 `Asia/Shanghai`。GitHub 的定时任务可能因负载出现几分钟延迟；手动运行可用于首次验证摘要接口和 SMTP 配置。默认工作流只给抓取/发送 job `contents: read`，只有状态提交 job 使用 `contents: write`。

## 本地运行

Python 3.11+、标准库即可：

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python -m aespa_digest --dry-run
PYTHONPATH=src python -m aespa_digest
```

本地运行前，先把 `.env.example` 复制为 `.env` 并用 shell 或其他安全的方式导出环境变量；程序本身不自动读取 `.env` 文件。`--dry-run` 会抓取 feed 并调用摘要接口，但不会发送邮件，也不会写入状态。

## 幂等与失败策略

- 文章通过规范化 HTTPS 链接和标题生成 SHA-256 指纹；已经成功投递的文章不会再次投递。
- 邮件发送失败时不更新状态；状态仅在 SMTP 成功后原子写入。
- 摘要接口单篇失败时，邮件会保留来源摘要并标注 AI 摘要暂不可用，同时在 Actions 日志中记录计数和错误类型。
- 单个 feed 失败会告警并继续；所有 feed 失败会让 workflow 失败。
- 日志只输出运行计数、feed 名称和错误类型，不输出 token、密码、邮箱或文章全文。

摘要服务的协议兼容性按用户提供的地址和模型配置为 OpenAI-compatible `POST /chat/completions`；仓库中的单元测试使用假 HTTP 响应。配置 Secrets 后，必须通过 GitHub Actions 的手动运行完成一次真实验证。
