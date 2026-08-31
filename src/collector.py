# -*- coding: utf-8 -*-
"""
AI信息雷达 · 实时信息采集引擎

独立的采集模块 —— 从 9 个信源并发抓取 AI 资讯，
经过去重→质量过滤→时效过滤→营销过滤→分类→评分，存入 data/realtime/<date>.json。

用法：
  python src/collector.py                    采集今天
  python src/collector.py --date 2026-08-07  指定日期
  python src/collector.py --dry-run          试运行（仅输出统计，不写文件）
  python src/collector.py --verbose          详细输出

作为模块导入：
  from src.collector import collect_today
  items = collect_today()  # 返回 NewsItem 列表
"""

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Windows 控制台 GBK → UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 将项目根目录加入 sys.path（支持直接运行或导入）
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.sources.base import NewsItem, source_request_health
from src.sources.hackernews import HackerNewsSource
from src.sources.techcrunch import TechCrunchSource
from src.sources.venturebeat import VentureBeatSource
from src.sources.reddit_ml import RedditMLSource
from src.sources.arxiv import ArxivSource
from src.sources.github_trending import GitHubTrendingSource
from src.sources.producthunt import ProductHuntSource
from src.sources.qwen_blog import QwenBlogSource, DeepSeekUpdatesSource

# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------
REALTIME_DIR = BASE_DIR / "data" / "realtime"
REALTIME_DIR.mkdir(parents=True, exist_ok=True)

MAX_AGE_HOURS = 24  # 超过此时间的资讯被过滤
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def current_collect_date(now=None) -> date:
    """返回项目时区中的当前自然日。"""
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    return current.astimezone(LOCAL_TZ).date()

# 分类关键词映射
CATEGORY_KEYWORDS = {
    "model": [
        "model", "LLM", "GPT", "Claude", "Gemini", "DeepSeek", "Qwen", "Mistral",
        "Llama", "开源模型", "大模型", "language model", "transformer",
        "fine-tun", "pretrain", "benchmark", "参数", "weights", "release",
        "发布", "open source model", "foundation model",
    ],
    "tool": [
        "tool", "CLI", "IDE", "plugin", "extension", "framework", "SDK",
        "library", "API", "platform", "工作流", "workflow", "editor",
        "playground", "sandbox", "开发工具", "dev tool",
    ],
    "agent": [
        "agent", "智能体", "bot", "assistant", "copilot", "cowork",
        "autonomous", "browser-use", "computer use", "tool call",
        "function call", "multi-agent",
    ],
    "opensource": [
        "open source", "开源", "GitHub", "repo", "git clone", "weights",
        "Apache", "MIT", "GPL", "社区",
    ],
    "business": [
        "funding", "融资", "acqui", "收购", "IPO", "revenue", "partnership",
        "合作", "CEO", "CTO", "hire", "layoff", "裁员", "depart",
        "billion", "million", "invest", "投资",
    ],
    "research": [
        "paper", "论文", "arXiv", "research", "study", "survey", "benchmark",
        "SOTA", "state-of-the-art", "accuracy", "F1", "BLEU",
        "experiment", "ablation",
    ],
    "product": [
        "product", "产品", "app", "launch", "上线", "feature", "update",
        "release", "UI", "UX", "user", "subscription", "pricing",
    ],
    "policy": [
        "regulation", "监管", "policy", "政策", "EU AI", "law", "legal",
        "copyright", "版权", "privacy", "隐私", "ethics", "伦理",
        "ban", "禁止", "compliance", "合规",
    ],
    "hardware": [
        "GPU", "chip", "芯片", "Nvidia", "AMD", "Intel", "TPU", "NPU",
        "算力", "compute", "server", "cloud", "infrastructure",
        "data center", "H100", "B200",
    ],
}


# ------------------------------------------------------------------
# 过滤管道
# ------------------------------------------------------------------
def filter_duplicates(items: list) -> list:
    """去重：URL 精确匹配 + 标题相似度 > 85%"""
    seen_urls = set()
    seen_titles = []  # [(title, item)]
    unique = []

    for item in items:
        url_key = item.link.strip().rstrip("/")
        if url_key and url_key in seen_urls:
            item.duplicate_of = url_key
            continue
        if url_key:
            seen_urls.add(url_key)

        # 标题相似度检查
        title = item.title.strip().lower()
        is_dup = False
        for seen_title, seen_item in seen_titles:
            ratio = difflib.SequenceMatcher(None, title, seen_title).ratio()
            if ratio > 0.85:
                item.duplicate_of = seen_item.link
                is_dup = True
                break

        if is_dup:
            continue

        seen_titles.append((title, item))
        unique.append(item)

    return unique


def filter_quality(items: list, verbose: bool = False) -> list:
    """质量过滤：按信源类型设最低评分阈值"""
    thresholds = {
        "HackerNews": 10,
        "Reddit": 5,
        "ProductHunt": 10,
        "GitHub": 20,
        "arXiv": 0,    # arXiv 论文无评分，保留
        "TechCrunch": 0,
        "VentureBeat": 0,
        "QwenBlog": 0,
        "DeepSeek": 0,
    }
    filtered = []
    for item in items:
        threshold = thresholds.get(item.source, 0)
        if item.points >= threshold:
            filtered.append(item)
        elif verbose:
            print(f"  [过滤-质量] {item.source} {item.title[:60]}... ({item.points} < {threshold})")
    return filtered


def _item_local_date(item: NewsItem):
    """把信源时间转换为项目时区日期，确保 00:00 后进入新信息池。"""
    timestamp = (item.timestamp or "").strip()
    if not timestamp:
        return None

    parsed = None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            parsed = parsedate_to_datetime(timestamp)
        except (TypeError, ValueError):
            return None

    if parsed.tzinfo is None:
        # Hacker News 返回 UTC 但没有时区后缀；其他无时区信源按本地时间处理。
        assumed_tz = timezone.utc if item.source == "HackerNews" else LOCAL_TZ
        parsed = parsed.replace(tzinfo=assumed_tz)
    return parsed.astimezone(LOCAL_TZ).date()


def filter_age(items: list, target_date: str, verbose: bool = False) -> list:
    """按项目本地自然日过滤，不把 00:00 后的信息混入前一天。"""
    target = date.fromisoformat(target_date)
    filtered = []

    for item in items:
        item_date = _item_local_date(item)
        if item_date is None and target == current_collect_date():
            # 今日实时池可暂存未知发布时间；最终日报结算会严格排除。
            filtered.append(item)
            continue

        if item_date == target:
            filtered.append(item)
        elif verbose:
            print(f"  [过滤-日期] {item.source} {item.title[:60]}... ({item.timestamp})")

    return filtered


def _item_from_dict(raw: dict) -> NewsItem:
    """从已有信息池恢复 NewsItem，兼容旧版缺失字段。"""
    return NewsItem(
        title=str(raw.get("title", "")),
        source=str(raw.get("source", "")),
        source_type=str(raw.get("source_type", "unknown")),
        timestamp=str(raw.get("published_at") or raw.get("timestamp", "")),
        link=str(raw.get("link", "")),
        summary=str(raw.get("summary", "")),
        category=str(raw.get("category", "")),
        importance=str(raw.get("importance", "")),
        impact_analysis=str(raw.get("impact_analysis", "")),
        tags=raw.get("tags", []) if isinstance(raw.get("tags", []), list) else [],
        points=int(raw.get("points", 0) or 0),
        comments=int(raw.get("comments", 0) or 0),
        collected_at=str(raw.get("collected_at", "")),
        duplicate_of=raw.get("duplicate_of"),
    )


def _load_existing_items(path: Path) -> list:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [_item_from_dict(item) for item in payload.get("items", [])]
    except (OSError, ValueError, TypeError) as exc:
        print(f"  [警告] 读取已有信息池失败，将保留原文件并使用本轮数据: {exc}")
        return []


def _write_pool(path: Path, target_date: str, items: list,
                source_health: dict = None) -> None:
    """原子写入当天完整信息池，避免采集过程中留下半个 JSON。"""
    by_source, by_category = {}, {}
    by_importance = {"A": 0, "B": 0, "C": 0}
    for item in items:
        by_source[item.source] = by_source.get(item.source, 0) + 1
        by_category[item.category] = by_category.get(item.category, 0) + 1
        by_importance[item.importance] = by_importance.get(item.importance, 0) + 1

    now_iso = datetime.now(LOCAL_TZ).isoformat()
    health = source_health or {}
    health_summary = {
        status: sum(1 for item in health.values() if item.get("status") == status)
        for status in ("ok", "partial", "failed", "empty")
    }
    health_summary["total"] = len(health)
    health_summary["available"] = health_summary["ok"] + health_summary["partial"]

    payload = {
        "date": target_date,
        "collect_date": target_date,
        "collected_at": now_iso,
        "total": len(items),
        "stats": {
            "by_source": by_source,
            "by_category": by_category,
            "by_importance": by_importance,
            "source_health": health,
            "source_health_summary": health_summary,
        },
        "items": [item.to_dict() for item in items],
    }
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


# 营销/垃圾关键词黑名单
SPAM_KEYWORDS = [
    "best deal", "discount code", "sponsored", "buy now", "limited offer",
    "cheap price", "on sale", "click here", "subscribe now", "free trial",
    "casino", "crypto exchange", "earn money", "make money fast",
    "SEO tool", "affiliate link", "get rich",
]


def filter_spam(items: list, verbose: bool = False) -> list:
    """营销/垃圾过滤"""
    filtered = []
    for item in items:
        title_lower = item.title.lower()
        summary_lower = item.summary.lower()
        combined = f"{title_lower} {summary_lower}"

        is_spam = any(kw in combined for kw in SPAM_KEYWORDS)
        is_too_short = len(item.title) < 15 and not item.link

        if is_spam or is_too_short:
            if verbose:
                print(f"  [过滤-营销] {item.source} {item.title[:60]}...")
            continue

        filtered.append(item)
    return filtered


# ------------------------------------------------------------------
# 分类与评分
# ------------------------------------------------------------------
def classify_item(item: NewsItem) -> str:
    """根据标题+摘要自动分类"""
    text = f"{item.title} {item.summary} {item.tags}".lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw.lower() in text)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "model"  # 默认归入 model


def score_importance(item: NewsItem) -> str:
    """自动评分 A/B/C

    A级：高热度 + 高信源权威 + 重大关键词
    B级：中等热度 或 有用信源
    C级：其他
    """
    title_lower = item.title.lower()
    summary_lower = item.summary.lower()
    combined = f"{title_lower} {summary_lower}"

    # A级信号
    a_signals = [
        "release", "launch", "announce", "breakthrough", "发布", "开源",
        "funding", "融资", "acquisition", "收购", "CEO", "CTO",
        "billion", "SOTA", "state-of-the-art", "first", "首次",
        "official", "正式",
    ]
    # B级信号
    b_signals = [
        "update", "update", "更新", "new feature", "beta", "preview",
        "benchmark", "comparison", "tutorial", "教程", "how to",
        "best practice", "case study",
    ]

    score = 0
    # 热度分
    if item.points >= 200:
        score += 3
    elif item.points >= 100:
        score += 2
    elif item.points >= 50:
        score += 1

    # 信源权威分
    if item.source in ("HackerNews", "QwenBlog", "DeepSeek", "arXiv"):
        score += 1
    if item.source_type == "official":
        score += 2

    # 关键词分
    a_count = sum(1 for s in a_signals if s.lower() in combined)
    b_count = sum(1 for s in b_signals if s.lower() in combined)
    score += a_count * 2 + b_count

    if score >= 5 or a_count >= 2:
        return "A"
    elif score >= 2:
        return "B"
    else:
        return "C"


def generate_impact(item: NewsItem) -> str:
    """生成简单的 Impact Analysis（A级事件）"""
    cat = item.category or classify_item(item)
    title = item.title[:80]

    if cat == "model":
        return f"新模型发布可能影响当前技术选型和API成本"
    elif cat == "tool":
        return f"新工具可能提升开发效率，值得评估引入"
    elif cat == "agent":
        return f"新Agent产品可能改变相关工作流"
    elif cat == "business":
        return f"行业格局变化可能影响创业方向和投资选择"
    elif cat == "research":
        return f"学术突破可能在1-2年内转化为可用技术"
    elif cat == "hardware":
        return f"算力变化影响AI应用的成本结构"
    else:
        return f"建议进一步了解详情以评估影响"


# ------------------------------------------------------------------
# 主采集流程
# ------------------------------------------------------------------
def _source_health_result(source, items, request_health, duration_ms, error=None):
    failed_requests = request_health.get("failed_requests", 0)
    if error is not None:
        status = "failed"
    elif items and failed_requests:
        status = "partial"
    elif items:
        status = "ok"
    elif failed_requests:
        status = "failed"
    else:
        status = "empty"
    errors = list(request_health.get("errors", []))
    if error is not None:
        error_text = f"{type(error).__name__}: {error}"[:200]
        if error_text not in errors:
            errors.append(error_text)
    return {
        "status": status,
        "items": len(items),
        "requests": request_health.get("requests", 0),
        "failed_requests": failed_requests,
        "duration_ms": duration_ms,
        "error": "；".join(errors[:3]),
    }


def _fetch_source_with_health(source, historical=False, target_date=None):
    started = time.perf_counter()
    with source_request_health(source.name) as request_health:
        try:
            if historical and isinstance(source, HackerNewsSource):
                items = source.fetch_for_date(target_date)
            else:
                items = source.fetch()
            error = None
        except Exception as exc:
            items = []
            error = exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    return items, _source_health_result(
        source,
        items,
        request_health,
        duration_ms,
        error=error,
    )


def collect_all(verbose: bool = False, target_date: str = None,
                with_health: bool = False):
    """并发采集所有信源，返回 NewsItem 列表"""
    all_sources = [
        HackerNewsSource(),
        TechCrunchSource(),
        VentureBeatSource(),
        RedditMLSource(),
        ArxivSource(),
        GitHubTrendingSource(),
        ProductHuntSource(),
        QwenBlogSource(),
        DeepSeekUpdatesSource(),
    ]

    historical = bool(
        target_date and date.fromisoformat(target_date) < current_collect_date()
    )
    sources = all_sources[:1] if historical else all_sources

    all_items = []
    max_workers = min(len(sources), 6)  # 并发数

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for source in sources:
            future = executor.submit(
                _fetch_source_with_health,
                source,
                historical,
                target_date,
            )
            futures[future] = source
        source_health = {}
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, health = future.result()
                source_health[source.name] = health
                if verbose:
                    print(
                        f"  {health['status']:7s} {source.name:20s} → "
                        f"{len(items):3d} 条 / {health['duration_ms']}ms"
                    )
                all_items.extend(items)
            except Exception as e:
                source_health[source.name] = {
                    "status": "failed",
                    "items": 0,
                    "requests": 0,
                    "failed_requests": 0,
                    "duration_ms": 0,
                    "error": f"{type(e).__name__}: {e}"[:200],
                }
                print(f"  ✗ {source.name:20s} 异常: {e}")

    return (all_items, source_health) if with_health else all_items


def collect_today(target_date: str = None, dry_run: bool = False,
                  verbose: bool = False) -> list:
    """完整的采集 → 过滤 → 分类 → 存储流程

    返回处理后的 NewsItem 列表。
    """
    if target_date is None:
        target_date = current_collect_date().isoformat()

    print(f"📡 开始采集 {target_date} 的AI资讯")

    # 第1步：今天走完整信源；历史日期只调用支持精确范围查询的信源。
    historical = date.fromisoformat(target_date) < current_collect_date()
    if historical:
        print("第1步：历史补采（Hacker News 精确自然日查询）...")
    else:
        print("第1步：并发采集 9 个信源...")
    raw, source_health = collect_all(
        verbose=verbose,
        target_date=target_date,
        with_health=True,
    )
    print(f"  原始数据: {len(raw)} 条")
    health_counts = {
        status: sum(1 for item in source_health.values() if item["status"] == status)
        for status in ("ok", "partial", "failed", "empty")
    }
    print(
        "  信源健康: "
        f"正常 {health_counts['ok']} / 部分成功 {health_counts['partial']} / "
        f"失败 {health_counts['failed']} / 暂无返回 {health_counts['empty']}"
    )
    failed_sources = [
        name for name, item in source_health.items() if item["status"] == "failed"
    ]
    if failed_sources:
        print("  失败信源: " + "、".join(sorted(failed_sources)))

    # 第2步：过滤管道
    print("第2步：过滤管道（去重→质量→时效→营销）...")
    step1 = filter_duplicates(raw)
    if verbose:
        print(f"  去重后: {len(step1)} 条（移除 {len(raw) - len(step1)} 条重复）")

    step2 = filter_quality(step1, verbose=verbose)
    if verbose:
        print(f"  质量过滤后: {len(step2)} 条（移除 {len(step1) - len(step2)} 条低质）")

    step3 = filter_age(step2, target_date, verbose=verbose)
    if verbose:
        print(f"  时效过滤后: {len(step3)} 条（移除 {len(step2) - len(step3)} 条过时）")

    step4 = filter_spam(step3, verbose=verbose)
    if verbose:
        print(f"  营销过滤后: {len(step4)} 条（移除 {len(step3) - len(step4)} 条垃圾）")

    # 第3步：分类与评分
    print("第3步：分类与重要性评分...")
    for item in step4:
        item.category = classify_item(item)
        item.importance = score_importance(item)
        if item.importance == "A":
            item.impact_analysis = generate_impact(item)

    # 统计
    by_source = {}
    by_category = {}
    by_importance = {"A": 0, "B": 0, "C": 0}
    for item in step4:
        by_source[item.source] = by_source.get(item.source, 0) + 1
        by_category[item.category] = by_category.get(item.category, 0) + 1
        by_importance[item.importance] = by_importance.get(item.importance, 0) + 1

    print(f"  结果: {len(step4)} 条有效资讯")
    print(f"  按信源: {dict(sorted(by_source.items()))}")
    print(f"  按分类: {dict(sorted(by_category.items()))}")
    print(f"  按重要: A={by_importance['A']} B={by_importance['B']} C={by_importance['C']}")

    # 第4步：存储
    if not dry_run:
        out_path = REALTIME_DIR / f"{target_date}.json"

        # 每次采集都并入当天信息池，日报是否存在不影响后续采集。
        now_iso = datetime.now(LOCAL_TZ).isoformat()
        for item in step4:
            item.collected_at = now_iso
        existing_items = _load_existing_items(out_path)
        same_day_items = filter_age(existing_items + step4, target_date)
        merged_items = filter_duplicates(same_day_items)
        _write_pool(
            out_path,
            target_date,
            merged_items,
            source_health=source_health,
        )
        print(f"✅ 已保存当天信息池: {out_path}（新增候选 {len(step4)}，累计 {len(merged_items)}）")

    return step4


def load_realtime(target_date: str = None) -> dict | None:
    """读取已采集的实时数据"""
    if target_date is None:
        target_date = current_collect_date().isoformat()
    path = REALTIME_DIR / f"{target_date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="AI信息雷达 · 实时信息采集引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python src/collector.py                    采集今天的AI资讯
  python src/collector.py --date 2026-08-07  采集指定日期
  python src/collector.py --dry-run          试运行（仅统计，不保存）
  python src/collector.py --verbose          详细模式（显示过滤信息）
  python src/collector.py --test-sources     测试各信源连通性
        """,
    )
    parser.add_argument("--date", default=current_collect_date().isoformat(),
                        help="采集日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--dry-run", action="store_true",
                        help="试运行，仅输出统计不写文件")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出过滤过程")
    parser.add_argument("--test-sources", action="store_true",
                        help="测试各信源连通性后退出")
    args = parser.parse_args()

    if args.test_sources:
        print("🔍 测试信源连通性...\n")
        sources = [
            HackerNewsSource(), TechCrunchSource(), VentureBeatSource(),
            RedditMLSource(), ArxivSource(), GitHubTrendingSource(),
            ProductHuntSource(), QwenBlogSource(), DeepSeekUpdatesSource(),
        ]
        for s in sources:
            try:
                items = s.fetch(max_items=5)
                status = f"✓ {len(items)} 条" if items else "⚠ 0 条（可能无新内容）"
                print(f"  {s.name:20s} → {status}")
            except Exception as e:
                print(f"  {s.name:20s} → ✗ 失败: {e}")
        return

    collect_today(target_date=args.date, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
