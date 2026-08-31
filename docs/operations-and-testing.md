# 运行、测试与验收手册

> 面向日常使用、开发调试和版本验收。所有命令默认在项目根目录执行。

## 1. 主开发目录

```text
D:\Allclaude\AI信息雷达-便携版
```

所有开发、测试、Git 和源码运行都应围绕这个目录。旧 EXE 只作为历史发布物，不应作为开发入口。

## 2. 环境要求

- Windows 10/11。
- Python 3.10+。
- `flask>=3.0`。
- `markdown>=3.5`。
- 日报生成需要可用的 OpenAI 兼容 API。

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 3. 安全配置

真实凭证只放在 Windows 用户环境变量：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
```

查看是否存在时只能检查“存在/不存在”，不要输出真实 Key。

项目安全规则：

- 不把 Key 写入代码。
- 不把 Key 写入 `.env.example`。
- 不把 Key 写入 README、日志、JSON 或日报。
- `.env`、日志和任务状态已经配置为不提交 Git。
- Key 曾经在聊天或其他地方明文出现时，应立即在服务端撤销并更换。

## 4. 启动桌面源码版

推荐双击根目录：

```text
打开AI信息雷达.bat
```

或在 PowerShell 运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_source.ps1
```

开发调试时也可以：

```powershell
python src/app.py
```

访问地址：

```text
http://127.0.0.1:8899
```

确认运行的是主源码实例：

```powershell
Invoke-RestMethod http://127.0.0.1:8899/api/instance
```

预期：

```json
{
  "edition": "source",
  "project_id": "ai-radar-portable-source"
}
```

## 5. 安装自动任务

运行一次：

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_schedule.ps1
```

会创建：

| 任务 | 时间 | 行为 |
|---|---|---|
| `AIRadarCollectEvery2Hours` | 每天 00:00、02:00……22:00 | 采集当天信息池，不调用 GPT |
| `AIRadarDailyFinalize` | 每天 00:05、00:20、00:35、00:50 | 结算一期待补日报；昨天优先，其余按最早缺口 |

任务配置了“错过后尽快运行”。电脑关机期间无法采集，开机后只能补跑当时可获得的内容。

安装完成后必须反查，不能只相信脚本输出：

```powershell
Get-ScheduledTask -TaskName AIRadarCollectEvery2Hours
Get-ScheduledTask -TaskName AIRadarDailyFinalize
Get-ScheduledTaskInfo -TaskName AIRadarDailyFinalize
```

脚本会排除临时 Python 和 WindowsApps，实际导入 `flask`、`markdown` 后再选择解释器。失败会返回非零退出码，不会再出现“注册失败却显示成功”。

## 6. 常用手动命令

### 采集

```powershell
# 正常采集今天并保存
python src/collector.py

# 显示每个过滤步骤和信源健康度
python src/collector.py --verbose

# 只测试信源
python src/collector.py --test-sources

# 试运行，不保存
python src/collector.py --dry-run
```

### 日报结算

```powershell
# 结算昨天
python src/generate_daily.py --finalize-yesterday

# 结算指定的已结束日期
python src/generate_daily.py --finalize-date 2026-08-19

# 自动选择一期可恢复缺口；昨天优先，自动限次重试
python src/generate_daily.py --finalize-pending
```

不要用 `--force` 随意覆盖历史日报。需要重建时，先确认目标日期、素材池和影响范围。

## 7. 运行状态在哪里看

| 内容 | 位置 |
|---|---|
| 首页服务日志 | `data/logs/source-server.stdout.log`、`source-server.stderr.log` |
| 定时采集日志 | `data/logs/collect.log` |
| 日报结算日志 | `data/logs/daily-finalize.log` |
| 当天信息池 | `data/realtime/YYYY-MM-DD.json` |
| 日报任务状态 | `data/update_status/YYYY-MM-DD.json` |
| 日期任务锁 | `data/update_status/YYYY-MM-DD.lock` |
| 最终日报 | `data/daily/YYYY-MM-DD.md` |

`GET /api/update-status` 还会返回 `continuity`：

- `completed_count`：已完成期数。
- `missing_dates`：全部缺失日期。
- `recoverable_dates`：已有合法信息池、可直接结算的日期。
- `missing_pool_dates`：缺少信息池，不能安全生成的日期。
- `active_target_date`：当前唯一正在结算的日期。

自动失败最多尝试 4 次，每次至少间隔 15 分钟；手动按钮仍可重试。陈旧锁会在下一次领取该日期任务时安全回收。

## 8. 日常验收清单

### 白天采集验收

- [ ] 首页可以立即打开。
- [ ] “今日实时雷达”日期等于今天。
- [ ] 信息条数会在采集后更新。
- [ ] 页面显示“信源可用 N/9”。
- [ ] 失败信源名称与 JSON 中的健康状态一致。
- [ ] 今天不会出现“今日最终日报”。

### 次日 00:05 结算验收

- [ ] `target_date` 等于昨天。
- [ ] 只读取昨天的实时池。
- [ ] 同一日期只有一个任务锁。
- [ ] 成功后生成 `data/daily/昨天.md`。
- [ ] 日报标题日期正确。
- [ ] 重要事件包含来源、发布时间和原始链接。
- [ ] 今天的数据没有混入昨天日报。
- [ ] 失败时旧日报仍能阅读。

### 页面和 API 验收

- [ ] 首页 `/` 返回 200。
- [ ] 最近日报详情页返回 200。
- [ ] `/api/reports` 返回全部日报。
- [ ] `/api/update-status` 返回 `not_started/running/success/failed` 之一。
- [ ] `/api/instance` 返回主源码身份。
- [ ] 未读日报数 + 已读日报数 = 全部日报数。

## 9. 自动化测试

运行全部测试：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

当前基线为 30 个测试，覆盖：

- 候选相关性和来源配额。
- 同一事件去重。
- 高价值事件回补。
- 上海自然日和历史日期隔离。
- 日报日期、章节、链接和最小长度校验。
- AI 失败时保留旧日报。
- 00:06 生成中兜底。
- 10 次并发只启动一个任务。
- 历史详情、日报 API 和已读同步。
- 信源健康状态和代理回退隔离。

语法检查：

```powershell
python -m py_compile src/app.py src/collector.py src/generate_daily.py
```

## 10. 常见故障

| 现象 | 首先检查 | 处理原则 |
|---|---|---|
| 首页打不开 | 8899 是否监听、`source-server.stderr.log` | 不要同时启动旧 EXE |
| 页面内容和源码不一致 | `/api/instance`、桌面快捷方式 | 统一使用主目录启动器 |
| 所有信源失败 | 网络、代理、`--verbose` 输出 | 不要直接改所有适配器 |
| 单个信源 403 | 站点限制或入口变化 | 单信源修复，其他结果继续保留 |
| 今日池有内容但日报没有 | `published_at` 是否缺失或跨日 | 不要用采集时间冒充发布时间 |
| 日报生成失败 | API 环境变量、结算日志、状态 JSON | 保留旧日报，修复后重试 |
| 连续刷新担心重复调用 | 状态接口和 `.lock` 文件 | 刷新与计划任务共用日期锁 |
| 00:06 昨日日报未出现 | `/api/update-status` 是否 `running` | 继续显示上一期，等待完成后刷新 |

## 11. 发布前检查

- [ ] 完整自动测试通过。
- [ ] 真实采集至少一次，并记录信源状态。
- [ ] 真实日报结算至少一次。
- [ ] 首页、详情页和 API 正常。
- [ ] 历史日报数量和文件哈希没有意外变化。
- [ ] `.env`、Key、日志、已读数据未进入版本库。
- [ ] README 和开发计划已更新。
- [ ] 桌面快捷方式指向源码启动器或本次正式构建产物。
- [ ] 如果重新打包 EXE/APK，明确记录源码版本和构建日期。

## 12. 出错时的正确处理顺序

```text
记录用户看到的现象
  -> 确认运行实例
  -> 查看对应日志和状态文件
  -> 复现单一失败步骤
  -> 判断环境问题还是代码问题
  -> 最小修复
  -> 自动测试
  -> 真实环境复验
  -> 更新文档和修改记录
```

不要通过删除信息池、覆盖历史日报或关闭日期检查来掩盖错误。
