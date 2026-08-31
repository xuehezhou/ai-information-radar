# 日报生成流程详解

## 整体流程

```
全天公开信源（9 个适配器）
        │  每 2 小时采集一次
        ▼
data/realtime/YYYY-MM-DD.json   （当天完整信息池）
        │  次日 00:05：规则初筛 → 事件去重 → 候选排序
        ▼
OpenAI Responses API  （HTTPS）
        │  GPT-5.6 Luna 生成最终日报
        ▼
data/daily/YYYY-MM-DD.md   （日报正文，应用直接读取展示）
```

## 三种使用模式

| 命令 | 用途 | 消耗token |
|------|------|----------|
| `python src/collector.py` | 采集当天信息池 | 否 |
| `python src/generate_daily.py --finalize-yesterday` | 结算昨天完整信息池 | 是 |
| `python src/generate_daily.py --finalize-date YYYY-MM-DD` | 结算指定日期 | 是 |
| `python src/generate_daily.py --no-api` | 抓素材后交给 Claude Code 手动精修 | 否 |
| `python src/generate_daily.py --material-only` | 只抓素材存档 | 否 |

## 推荐工作流（质量优先）

1. 计划任务每 2 小时运行 `python src/collector.py`，把新信息合并到当天信息池。
2. 次日 00:05 运行 `python src/generate_daily.py --finalize-yesterday`。
3. 结算脚本只读取前一天的信息池，先做程序规则筛选和事件级去重，再把最多 24 条候选一次性发送给模型。
4. 模型成功返回非空 Markdown 后，脚本原子写入 `data/daily/YYYY-MM-DD.md`；失败时保留旧日报和完整信息池。
5. 首页先展示最近一期已完成日报；“刷新 / 检查更新”只检查状态，目标日报缺失且没有任务运行时，00:05 后才非阻塞启动一次结算，不触发信源采集。

## 刷新与跨午夜兜底

- `GET /api/update-status` 返回昨日日报目标日期、四态状态和最近已完成日报日期。
- `POST /api/update-check` 在必要时启动后台结算；`not_started`、`running`、`success`、`failed` 分别表示未开始、运行中、成功和失败。
- Windows 00:05 计划任务与首页按钮共用 `data/update_status/YYYY-MM-DD.lock`。原子日期锁保证同一日期最多只有一个生成任务，连续点击不会增加模型调用。
- 00:06 目标日报仍在生成时，首页继续显示最近一期已完成日报；成功后前端再次检查会切换到新日报，失败时保留旧日报并提供重试。
- 运行状态写入 `data/update_status/YYYY-MM-DD.json`，该目录是本机运行数据，不提交 Git。

## OpenAI 调用细节

- 端点：`POST {OPENAI_BASE_URL}/responses`，当前中转站示例为 `https://stariver.top/v1/responses`
- API Key：环境变量 `OPENAI_API_KEY`，不会写入代码、Prompt、JSON 或日志
- 模型：默认使用 `gpt-5.6-luna`，可用环境变量 `OPENAI_MODEL` 覆盖
- 超时：300秒；失败时保留信息池并明确报错，不覆盖已有日报。计划任务会在 00:20、00:35、00:50 重试。

## 采集和结算的边界

- 信息按 `Asia/Shanghai` 本地自然日归档；00:00 之后的新信息进入新日期的信息池。
- 结算前会再次按 `Asia/Shanghai` 校验 `published_at`；只有发布时间明确落在目标自然日内的信息才能进入最终日报，时间缺失或无法解析的信息不会进入最终日报。
- `collected_at` 只表示系统何时抓到信息，不能决定日报归属；`collect_date` 标识信息池日期，`report_date` 由结算任务明确指定。
- 今天和未来日期禁止生成最终日报。今天只维护 `today_realtime`，次日 00:05 才生成对应的 `daily_report`。
- `data/realtime/YYYY-MM-DD.json` 是当天采集阶段的完整池，日报是否已经存在不会停止后续采集。
- `data/daily/YYYY-MM-DD.md` 是结算产物，不是采集是否继续的开关。
- 每次采集会按 URL 和标题相似度合并去重；结算时再次做事件级去重，避免同一事件因多个来源重复进入日报。
- 规则评分综合程序重要性、信源类型、热度、摘要、链接和发布时间；模型只负责对候选事件进行最终重要性判断和深度分析。
- 最终日报的每条重要事件必须保留信源、原始发布时间和原始链接。
- 每轮采集会记录信源的 `ok`、`partial`、`failed`、`empty` 状态；首页展示可用数量和异常名称。
- 当前 GitHub、Product Hunt、Qwen、DeepSeek 适配器可能缺少可靠发布时间；无法确认目标自然日的内容会被最终结算排除，不能用采集时间冒充发布时间。

评分细节见 [data-sources-and-scoring.md](data-sources-and-scoring.md)。

## Windows 计划任务

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_schedule.ps1
```

注册后可在任务计划程序中查看 `AIRadarCollectEvery2Hours` 和 `AIRadarDailyFinalize`。自动结算依赖运行账户能够读取用户环境变量 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和可选的 `OPENAI_MODEL`。

## 故障排查

| 现象 | 原因与解决 |
|------|-----------|
| 调用 OpenAI 失败 | 检查 `OPENAI_API_KEY` 是否存在，以及 `OPENAI_MODEL` 是否为账户可用模型 |
| 所有信源抓取失败 | 运行 `python src/collector.py --verbose`，检查网络、代理和每个信源的具体错误 |
| 实时池有内容但日报未采用 | 检查该信息是否有可解析的 `published_at`，以及是否属于目标自然日 |
| 首页不显示某期 | 文件名不是 `YYYY-MM-DD.md`，或日期仍是今天/未来，尚未到最终日报结算时间 |
| 详情页404 | 日期不存在或格式非法 |
