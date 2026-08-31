# AI 信息雷达技术架构规划

> 原则：保留当前 Python + Flask + 文件存储，不为规划而提前引入复杂基础设施。

## 1. 当前架构

```text
src/sources/*
      |
      v
src/collector.py
      |
      v
data/realtime/YYYY-MM-DD.json
      |
      v
src/generate_daily.py -> OpenAI Responses API
      |
      v
data/daily/YYYY-MM-DD.md
      |
      v
src/app.py -> templates/* -> Browser / 手机同步 API

Windows Task Scheduler
  -> 每 2 小时 collector.py
  -> 00:05/00:20/00:35/00:50 generate_daily.py
```

### 当前模块职责

| 模块 | 当前职责 | 主要问题 |
|---|---|---|
| `src/sources/` | 不同信源适配 | 部分来源时间缺失、页面解析脆弱 |
| `collector.py` | 采集、过滤、分类、评分、合并、落盘 | 职责较多；尚无独立 Event 层 |
| `generate_daily.py` | 日期校验、候选筛选、AI 调用、校验、写日报 | AI 调用和编辑逻辑集中在一个文件 |
| `app.py` | 页面、API、已读、任务状态和兜底启动 | Web 与部分任务控制耦合 |
| `data/` | 文件型持久化 | 简单可靠，但缺少数据版本和事件实体 |
| `templates/` | 服务端渲染页面 | 适合当前个人桌面规模 |

## 2. 当前架构评价

适合当前阶段的部分：

- 单体应用便于初学者理解和本地运行。
- 文件存储无需数据库运维。
- Windows 计划任务足以支撑每日批处理。
- 采集和 AI 生成已经分离。

需要演进的部分：

- Raw News 和 Event 尚未分离。
- 信源字段质量没有统一契约校验。
- 重要性评分存在程序规则和模型星级两套口径。
- Agent 化之前缺少稳定的输入输出接口。

## 3. 推荐目标架构

推荐的是“模块化单体”，不是微服务：

```text
任务调度层
  |
  +--> 数据采集层 --> Raw News Store
  |                         |
  |                         v
  +--> 数据处理层 --> Event Store
                            |
                            v
                     事件理解与评分层
                            |
                            v
                       AI 分析层
                            |
                            v
                     Daily Report Store
                            |
                            v
                        展示/API层

配置管理层、日志与质量指标横跨所有层
```

## 4. 分层职责

### 4.1 数据采集层

职责：连接公开信源并生成统一 Raw News。

输入：RSS、API、公开页面。

输出：标准字段、原始链接、发布时间、采集时间和抓取状态。

不负责：最终重要性、日报写作、用户展示。

### 4.2 数据处理层

职责：格式清洗、自然日归属、垃圾过滤、确定性去重和数据质量检查。

核心规则：无法确认发布时间的数据不得进入最终日期窗口。

### 4.3 事件理解层

职责：把多篇 Raw News 聚合成一个 Event，保留多个证据来源。

第一阶段应使用确定性规则和相似度；只有规则无法判断时才考虑 LLM 辅助。

### 4.4 重要性与 AI 分析层

职责：规则计算基础分，模型进行有限语义评分和深度分析。

接口应稳定为：

```text
List[EventCandidate]
  -> analysis result
  -> validated Markdown report
```

### 4.5 展示层

职责：首页、实时状态、历史日报、详情页和同步 API。

原则：首页只读取已有数据，不承担长时间采集和模型生成。

### 4.6 任务调度层

职责：全天采集、午夜结算、失败重试、日期锁和状态四态。

当前继续使用 Windows Task Scheduler + 文件锁。只有迁移到长期在线服务器或多机器执行时，才重新评估任务队列。

### 4.7 配置管理层

职责：时区、采集频率、候选上限、信源开关、模型端点和密钥。

原则：Secret 使用环境变量；非敏感业务参数未来可集中到一个配置模块，但不需要现在重构。

## 5. 推荐目录演进（未来，不是本轮执行）

```text
src/
├── app.py
├── collector.py
├── generate_daily.py
├── sources/
├── domain/
│   ├── raw_news.py
│   ├── event.py
│   └── daily_report.py
├── processing/
│   ├── normalize.py
│   ├── deduplicate.py
│   └── importance.py
├── ai/
│   ├── client.py
│   ├── editor.py
│   └── reviewer.py
└── templates/
```

这只是目标边界。每次只在真实任务需要时移动相应逻辑，禁止一次性重构到该结构。

## 6. 数据流

### 白天采集

```text
计划任务
  -> collector
  -> 并发调用 Source Adapter
  -> Raw News 标准化
  -> 日期过滤和去重
  -> 原子合并到当天实时池
  -> 更新信源健康状态
```

### 次日结算

```text
00:05 计划任务
  -> target_date = yesterday
  -> 获取日期锁
  -> 读取该日数据
  -> Event 聚合和规则评分
  -> 高价值候选
  -> 一次 AI 编辑调用
  -> Reviewer/质量闸门
  -> 原子写入该日日报
  -> 状态 success
```

### 用户阅读

```text
Browser
  -> Flask route
  -> 读取最近完成日报 + 今日实时状态
  -> 立即渲染 HTML
```

## 7. API 契约保护

当前接口 `/api/reports`、`/api/read/<date>`、`/api/update-status`、`/api/update-check`、`/api/instance` 已被页面或手机功能使用。

未来修改时必须：

- 保留已有字段或提供兼容期。
- 同时测试桌面页面和手机同步调用。
- 不把内部异常堆栈直接返回给用户。
- 公网部署前增加认证、限流和访问控制。

## 8. 技术选择与重新评估条件

| 技术 | 当前决策 | 什么时候重新评估 |
|---|---|---|
| Flask | 保留 | 出现复杂前后端交互或多用户需求 |
| JSON/Markdown 文件 | 保留 | Event 数量大、并发写入或查询明显困难 |
| Windows 计划任务 | 保留 | 部署到服务器或需要跨平台常驻调度 |
| 文件锁 | 保留 | 多机器执行同一任务 |
| Redis/队列 | 暂不引入 | 单机任务锁和调度无法满足实际并发 |
| 向量数据库 | 暂不引入 | 出现真实的长历史语义检索需求 |
| 微服务 | 暂不引入 | 模块需要独立扩缩容且单体成为已测量瓶颈 |

## 9. 架构验收原则

- 模块边界能用一句话说明。
- Raw News、Event、Daily Report 不混用。
- 日期和状态由确定性程序控制。
- LLM 不直接决定文件路径、任务状态或数据删除。
- 失败路径可定位且不破坏已有数据。
- 当前规模下无需额外服务即可运行。

