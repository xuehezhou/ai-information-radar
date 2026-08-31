# AI 信息雷达数据设计

> 目标：把“新闻文章”“现实事件”“最终日报”分成三个清晰层级，避免日期污染、重复事件和不可追溯结论。

## 1. 三个核心实体

```text
Raw News（原始报道，多条）
       |
       | 聚合、去重、验证
       v
Event（现实事件，一条）
       |
       | 评分、分析、编辑
       v
Daily Report（某自然日的日报，一份）
```

一个事件可能由多篇新闻共同证明；一份日报包含多个事件；同一篇新闻原则上只能归入一个主要事件。

## 2. Raw News

Raw News 表示“某个来源发布的一篇内容”，不是现实事件本身。

### 建议结构

```json
{
  "schema_version": 1,
  "raw_news_id": "raw_sha256",
  "source": "HackerNews",
  "source_type": "community",
  "source_item_id": "optional-source-id",
  "title": "原始标题",
  "summary": "原始或清洗摘要",
  "original_url": "https://...",
  "canonical_url": "https://...",
  "published_at": "2026-08-19T23:50:00+08:00",
  "collected_at": "2026-08-20T00:10:00+08:00",
  "collect_date": "2026-08-19",
  "language": "en",
  "points": 120,
  "comments": 30,
  "tags": [],
  "content_hash": "sha256",
  "parse_status": "complete|partial|failed",
  "time_confidence": "exact|date_only|unknown"
}
```

### 强制规则

- `published_at` 是来源实际发布时间。
- `collected_at` 只是系统抓取时间。
- `collect_date` 应由可验证发布时间转换为上海自然日。
- 如果时间未知，标记 `unknown`，不能把采集时间冒充发布时间。
- `original_url` 保留来源原链接，`canonical_url` 用于去追踪参数和去重。

## 3. Event

Event 表示“现实中发生的一件事”，它可以关联多个 Raw News。

### 建议结构

```json
{
  "schema_version": 1,
  "event_id": "evt_sha256",
  "event_date": "2026-08-19",
  "title": "标准化事件标题",
  "category": "model|tool|agent|business|research|policy|hardware|product|opensource",
  "entities": ["OpenAI", "产品名"],
  "action": "release",
  "facts": [],
  "source_refs": [
    {
      "raw_news_id": "raw_...",
      "source": "来源",
      "url": "https://...",
      "published_at": "...",
      "credibility": 0.0
    }
  ],
  "first_published_at": "...",
  "last_published_at": "...",
  "dedupe_method": "url|title|entity_action|reviewed",
  "dedupe_confidence": 0.0,
  "importance_score": 0,
  "score_breakdown": {},
  "score_reason": "",
  "verification_status": "verified|partial|unverified"
}
```

### Event 合并原则

- 同一 canonical URL：确定性合并。
- 标题高度相似且日期一致：高概率合并。
- 核心实体、动作和对象一致：可合并，但要保留置信度。
- 日期不同、主体不同或动作不同：不合并。
- 不确定时保留两个 Event，避免错误合并造成漏报。

## 4. Daily Report

Daily Report 表示一个已经结束自然日的稳定编辑产物。

### 建议元数据

```json
{
  "schema_version": 1,
  "report_id": "daily_2026-08-19",
  "report_date": "2026-08-19",
  "timezone": "Asia/Shanghai",
  "status": "draft|reviewing|published|failed",
  "event_ids": ["evt_..."],
  "generated_at": "2026-08-20T00:08:00+08:00",
  "model": "configured-model-id",
  "candidate_count": 18,
  "content_path": "data/daily/2026-08-19.md",
  "quality_checks": {},
  "source_coverage": {},
  "finalized": true
}
```

当前 Markdown 文件可以继续作为正文；元数据未来可使用同名 `.json` 或统一索引保存，不要求立即迁移数据库。

## 5. 日期关系

```text
published_at
  -> 转换到 Asia/Shanghai
  -> 得到 event_date / collect_date
  -> report_date 必须等于 event_date
```

例子：

- 2026-08-18 23:50 发布，19 日 00:10 抓到：仍属于 18 日。
- 2026-08-19 00:01 发布：只能属于 19 日。
- 没有发布时间：不能安全进入任何最终日报，等待补全或人工确认。

## 6. 为什么历史日报曾全部变成最新一天

根因不是 Markdown 文件本身，而是当时缺少强制数据契约：

```text
生成某个历史文件名
  但采集/读取逻辑仍取得最新数据
  -> target_date 只影响输出文件名
  -> 没有约束输入数据日期
  -> 最新数据被写入多个历史日报
```

正确契约必须是：

```text
target_date
  -> 只加载 collect_date == target_date 的数据集
  -> 再检查每条 published_at 的本地日期 == target_date
  -> 只生成 report_date == target_date 的日报
  -> 只写 data/daily/target_date.md
```

文件名、输入数据日期、事件日期和报告日期四者必须一致，任何不一致都应失败，而不是自动猜测。

## 7. importance_score 设计

统一输出 0～100 分：

| 维度 | 权重 | 主要判断 |
|---|---:|---|
| 时间与时效性 | 10 | 是否属于目标日期、是否是新进展 |
| 来源可信度 | 20 | 官方、权威媒体、论文、社区传闻及多源验证 |
| 影响范围 | 15 | 影响单一工具、开发者群体还是整个行业 |
| 新颖性 | 15 | 是否是真正新事件，还是旧闻重述 |
| 用户价值 | 20 | 对 AI 应用开发、产品或创业是否可行动 |
| 行业影响 | 20 | 是否改变能力边界、成本、生态、政策或竞争格局 |
| 合计 | 100 | 作为排序依据，不等于事实可信度 |

### 程序负责的部分

- 日期是否合法。
- 来源类型基础分。
- 热度和评论数的封顶加分。
- 是否有原始链接和发布时间。
- 多来源数量。
- 重复度和是否是旧闻。
- 关键词、组织和事件类型等确定性信号。

### GPT 负责的部分

- 新颖性语义判断。
- 影响范围判断。
- 对目标用户的实际价值。
- 行业影响和理由。
- 相似事件是否存在语义差异的辅助判断。

GPT 应返回结构化分项分数和理由，程序负责限制范围、计算总分和验证字段。GPT 不能直接决定发布日期、文件路径或任务状态。

### 建议等级映射

| importance_score | 等级 | 建议星级 |
|---:|---|---|
| 85～100 | A+ | 5 星 |
| 70～84 | A | 4 星 |
| 50～69 | B | 3 星 |
| 30～49 | C | 2 星 |
| 0～29 | 低优先 | 1 星或不进入日报 |

该映射是规划，尚未修改当前 Prompt 和代码。实施前需用真实日报样本校准。

## 8. 存储演进

### 当前阶段

继续使用日期 JSON + Markdown，增加 `schema_version` 和 Event 文件即可：

```text
data/raw/YYYY-MM-DD.json
data/events/YYYY-MM-DD.json
data/realtime/YYYY-MM-DD.json
data/daily/YYYY-MM-DD.md
data/daily/YYYY-MM-DD.meta.json
```

### 什么时候考虑 SQLite

只有出现以下真实问题再迁移：

- 跨日期搜索明显困难。
- 多个进程频繁更新同一文件。
- Event 与来源关系难以维护。
- 数据量使整文件读写成为已测量瓶颈。

当前不需要 PostgreSQL、Redis 或向量数据库。

## 9. 数据验收

- 每条 Raw News 有稳定 ID、来源和链接。
- 最终候选的 `published_at` 可解析率达到目标。
- 每个 Event 至少一个来源，重要事件优先两个独立来源。
- Event 日期与所有采用来源的日期一致，冲突要显式记录。
- Daily Report 的 `event_ids` 全部属于 `report_date`。
- 重建某日只改变该日 Event 和日报。
- 历史数据迁移必须可回滚并保留原文件。

