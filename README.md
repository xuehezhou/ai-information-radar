# 📡 AI信息雷达（ai-radar）

每日AI行业资讯查看应用。首页为新闻门户风格，每期《AI信息雷达日报》可点击打开全文阅读。

面向用户：AI应用开发者（非算法工程师），关注最新模型、AI工具、AI Agent、创业机会与行业趋势。

## 项目文档

第一次了解项目，建议按以下顺序阅读：

1. [项目指南](docs/project-guide.md)：目标、架构、数据、API 和术语。
2. [信息来源与评分说明](docs/data-sources-and-scoring.md)：9 个信源、A/B/C 初筛、候选分和 1～5 星的真实逻辑。
3. [日报生成流程](docs/daily-workflow.md)：全天采集、次日结算和日期隔离。
4. [运行、测试与验收手册](docs/operations-and-testing.md)：启动、定时任务、排错和验收清单。
5. [开发计划](docs/development-plan.md)：P0～P3 和 V1.16～V2.0 路线图。
6. [AI 开发约束](AI_DEVELOPMENT_RULES.md)：所有智能体和开发者必须遵守的长期规则。
7. [系统体检与优化 Backlog](docs/SYSTEM_AUDIT_AND_OPTIMIZATION_BACKLOG.md)：21 维体检、P0～P3、优化批次和真实验收。
8. [面试讲解材料](docs/INTERVIEW_NOTES.md)：每轮优化的技术难点、Debug 和面试表达。

## 功能

- **首页（新闻门户）**：报纸刊头 + 头条区（最新一期一句话总结）+ 日报卡片列表（日期倒序，含事件/模型/机会统计）
- **日报详情页**：Markdown 全文渲染（表格、星级、引用块），支持上一篇/下一篇导航
- **已读/未读追踪**：阅读后自动标记，首页未读（红边）/已读（降权）分区展示
- **全天采集、次日结算**：每 2 小时采集当天信息池；次日 00:05 读取前一天完整信息，经过规则筛选、事件去重后只调用一次模型生成最终日报
- **刷新与跨午夜兜底**：首页显示日报连续性；刷新会选择一期可恢复缺口（昨天优先），一次只运行一个日期任务，生成期间继续展示最近一期完整日报
- **手机版（Android APK，离线优先）**：日报打包进 App，打开即看、断网可用；连电脑 Wi-Fi 可同步最新日报，见 [android/README.md](android/README.md)
- **日报生成脚本**：读取前一天完整信息池 → 规则筛选和事件去重 → 调用 OpenAI Responses API 生成日报
- **信源健康透明化**：首页显示可用、部分成功、失败和暂无返回的信源，不把“抓到部分信息”误写成“全部信源正常”

## 环境要求

- Python 3.10+
- Flask、markdown（本项目零额外依赖，均常见已装）
- OpenAI API Key（通过环境变量 `OPENAI_API_KEY` 配置）——自动生成日报时需要

## 快速开始

```bash
# 1. 启动应用（默认端口8899，被占用时自动顺延）
python src/app.py

# 2. 浏览器打开
# http://127.0.0.1:8899
```

Windows 桌面快捷方式必须指向项目根目录的 `start.bat`，不要直接指向旧版 EXE。`start.bat` 会验证 8899 的实例身份；源码更新后会重启旧源码进程，发现旧 EXE 会停止它，发现未知程序占用端口则明确报错，避免静默打开错误版本。需要重新安装快捷方式时运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/make_shortcut.ps1
```

## 每日更新日报

### OpenAI 配置

程序只从环境变量读取密钥，不会从代码、日报、JSON 或日志读取密钥。
请在 Windows 用户环境变量中配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`，可选配置 `OPENAI_MODEL`。
项目中的 `.env.example` 只是配置示例，不能直接作为真实配置使用。

PowerShell 示例（不会把密钥写入项目文件）：

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的新Key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://stariver.top/v1", "User")
```

设置后请重新打开 PowerShell 或 Codex，使新环境变量生效。

### 方式零：全自动（推荐）

运行一次下面的脚本，会注册两个 Windows 计划任务：

- `AIRadarCollectEvery2Hours`：每天 00:00、02:00、04:00……22:00 采集当天信息池，不调用大模型。
- `AIRadarDailyFinalize`：每天 00:05、00:20、00:35、00:50 选择一期待补日报；昨天优先，其余按最早缺口；失败有次数和冷却限制。

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_schedule.ps1
```

脚本会排除临时 Python 和 WindowsApps，实际验证 `flask`、`markdown` 后再注册任务。也可显式指定：

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_schedule.ps1 -PythonExe D:\anaconda3\python.exe
```

计划任务的运行账户必须能读取 `OPENAI_API_KEY` 用户环境变量。若电脑在计划时间关机，任务配置为开机后尽快补跑。

- 采集日志：`data/logs/collect.log`
- 结算日志：`data/logs/daily-finalize.log`
- 管理：Win+R → `taskschd.msc` 查看；或重新运行 `powershell tools/setup_schedule.ps1` 重建

### 手动方式

```bash
# 方式一：手动结算昨天的信息池（消耗一次 token）
python src/generate_daily.py --finalize-yesterday

# 方式二：只抓素材，由 Claude Code 手动精修生成（不消耗 token）
python src/generate_daily.py --no-api

# 方式三：手动把 markdown 文件放入 data/daily/，命名为已结束的 YYYY-MM-DD.md
```

参数说明：

| 参数 | 作用 |
|------|------|
| `--date YYYY-MM-DD` | 指定素材日期（默认今天，不直接生成最终日报） |
| `--force` | 覆盖已存在的日报 |
| `--material-only` | 只抓素材不调用模型 |
| `--no-api` | 抓素材后提示手动生成，不消耗token |
| `--include-realtime` | 合并 `data/realtime/<date>.json` 采集数据作为增强素材 |
| `--finalize-date YYYY-MM-DD` | 只读取指定日期信息池，生成该日期最终日报，不重新采集 |
| `--finalize-yesterday` | 只结算昨天完整信息池，供计划任务使用 |
| `--finalize-pending` | 自动选择一期可恢复缺口；昨天优先，其余按最早日期；自动限次重试 |

### 实时信息采集（独立模块）

```bash
# 采集今天所有AI资讯（不依赖日报生成）
python src/collector.py

# 试运行（仅统计，不保存）
python src/collector.py --dry-run

# 测试各信源连通性
python src/collector.py --test-sources
```

采集引擎从 9 个信源并发抓取，经过去重→质量过滤→时效过滤→营销过滤→分类→自动评分后合并存入 `data/realtime/YYYY-MM-DD.json`。采集数据独立于日报生成，次日结算时会先做规则初筛和事件去重，再把高价值候选交给模型。

指定过去日期时，采集器只使用支持精确时间范围查询的 Hacker News 历史接口，并按 `Asia/Shanghai` 自然日过滤。只能返回最新内容的 RSS 不参与历史补采，避免把今天的新闻写进历史日报。

数据日期严格区分：`published_at` 是实际发布时间，`collected_at` 是系统采集时间，`collect_date` 是实时信息池日期，`report_date` 是最终日报归属日期。今天只能进入实时信息池，不能生成最终日报。

首页自动显示当日采集状态（"今日已采集 N 条AI资讯 · X 条A级事件"）。首页不会等待采集或模型分析；当天日报在次日结算成功后出现，未生成时继续展示最近一期历史日报。

首页“刷新 / 检查更新”调用 `GET /api/update-status` 和 `POST /api/update-check`。状态分为 `not_started`、`running`、`success`、`failed`；响应同时包含完成期数、缺失日期、可恢复日期和缺少信息池日期。按钮不触发信源采集，计划任务与手动检查共用 `data/update_status/` 中的日期级任务锁，因此连续点击不会产生重复模型调用。失败后旧日报仍可阅读，并可通过按钮重试。

## 手机阅读（Android APK，离线可用）

把 `android/dist/ai-radar.apk` 传到手机安装，**打开就能看全部日报**——
日报已打包进 App，断网/电脑关机也能看，不需要输网址。

- 手机与电脑连**同一 Wi-Fi** 时，App 内点「同步」可拉取电脑上最新日报（示例地址 `http://192.168.1.100:8899`，请在 App「设置」中改为电脑实际局域网 IP）
- 完整说明：**[android/README.md](android/README.md)**
- 重新打包（含最新日报）：`android/build.bat`

## 目录结构

```
ai-radar/
├── README.md              本文件
├── requirements.txt       依赖清单
├── rules.md               日报内容规范（分析师模板）
├── todo.md                当前任务
├── changelog.md           修改记录
├── src/
│   ├── app.py             Flask 主应用（首页 + 详情页 + 已读追踪；正常启动不触发采集/AI）
│   ├── generate_daily.py  日报生成编排脚本
│   ├── collector.py       实时信息采集引擎（独立模块）
│   ├── sources/           信源适配器包（9个信源）
│   ├── templates/         页面模板（base/index/daily/404）
│   └── static/            样式与图标
├── android/               手机版 APK 源码与构建工具
│   ├── dist/ai-radar.apk  安装包（成品）
│   ├── build.bat          一键打包脚本
│   └── README.md          手机安装说明
├── data/
│   ├── daily/             日报正文（YYYY-MM-DD.md，即数据库）
│   ├── raw/               每日抓取的原始素材 JSON
│   ├── realtime/          实时采集数据（YYYY-MM-DD.json）
│   └── read_status.json   已读状态记录
└── docs/
    ├── project-guide.md              项目整体指南
    ├── data-sources-and-scoring.md   信息来源与评分说明
    ├── daily-workflow.md             日报生成流程详解
    ├── operations-and-testing.md     运行、测试与验收手册
    └── development-plan.md           收益驱动开发路线图
```

## 日报内容规范

每期日报固定包含六个板块，详见 [rules.md](rules.md)：

1. 今日重要AI事件（A/B/C级筛选）
2. 新模型观察
3. AI工具发现
4. AI新名词解释
5. 创造机会分析
6. 学习建议

## 注意事项

- 日报数据全部存于 `data/daily/` 纯文本文件，可直接用 Git 管理版本
- 为保护隐私，Git 默认忽略整个 `data/` 运行目录；日报、实时池、已读状态、日志和任务状态不会上传 GitHub。
- 文件读写统一 UTF-8，Windows 下无乱码
- 自动生成的日报建议人工检查后再发布展示
- 素材信源为公开 RSS/API，仅供个人学习研究使用
