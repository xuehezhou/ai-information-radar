# -*- coding: utf-8 -*-
"""
AI信息雷达 · 日报生成脚本

流程：
  1. 抓取素材（Hacker News / TechCrunch / VentureBeat）→ data/raw/<date>.json
  2. 调用 OpenAI Responses API 生成日报
  3. 写入 data/daily/<date>.md

用法：
  python src/generate_daily.py --finalize-yesterday  结算昨天的完整信息池
  python src/generate_daily.py --finalize-date YYYY-MM-DD  结算指定日期
  python src/generate_daily.py --material-only 只抓素材不生成
  python src/generate_daily.py --no-api        只准备素材并提示手动生成

注意：
  - 需要配置 OPENAI_API_KEY；可用 OPENAI_MODEL 覆盖默认模型
  - 生成结果建议人工检查后再作为正式日报
"""

import argparse
import difflib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Windows 控制台默认 GBK，无法输出 emoji/部分中文 → 强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"
RAW_DIR = BASE_DIR / "data" / "raw"

DEFAULT_OPENAI_BASE_URL = "https://stariver.top/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
FINALIZED_MARKER = "<!-- AI_RADAR_FINALIZED:{date} -->"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
UPDATE_STATUS_DIR = BASE_DIR / "data" / "update_status"
LOCK_STALE_SECONDS = 30 * 60
AUTOMATIC_RETRY_LIMIT = 4
AUTOMATIC_RETRY_COOLDOWN_SECONDS = 15 * 60
STATUS_NOT_STARTED = "not_started"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
HEADERS = {"Content-Type": "application/json", "User-Agent": "ai-radar/1.0"}
CANDIDATE_LIMIT = 24
CANDIDATE_SOURCE_TYPE_LIMITS = {
    "academic": 8,
    "community": 10,
    "official": 4,
    "rss": 8,
}
HIGH_VALUE_BACKFILL_SCORE = 10
MIN_CANDIDATE_SCORE = 7
AI_RELEVANCE_TERMS = (
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "language model", "language models", "foundation model", "foundation models",
    "llm", "gpt", "openai",
    "anthropic", "claude", "gemini", "deepseek", "qwen", "llama",
    "mistral", "hugging face", "huggingface", "agent", "agents", "agentic",
    "reasoning", "inference", "embedding", "embeddings", "vector search",
    "transformer", "transformers", "neural", "text-to-image", "gpu", "gpus",
    "cerebras", "nvidia", "cursor", "mojo",
    "coding assistant", "coding agent", "data center", "算力", "模型",
    "人工智能", "机器学习", "深度学习", "智能体", "推理", "向量检索",
)
HIGH_IMPACT_TERMS = (
    "launch", "launches", "launched", "release", "releases", "released",
    "open source", "acquisition", "acquires", "acquired", "funding",
    "billion", "outage", "breach", "safeguard", "safeguards", "benchmark",
    "benchmarks",
    "frontier model", "chip", "cluster", "valuation", "发布", "开源",
    "收购", "融资", "安全", "宕机", "芯片", "集群",
)
DEVELOPER_VALUE_TERMS = (
    "api", "developer", "developers", "coding", "agent", "agents", "workflow",
    "workflows", "open source", "tool", "tools", "hosting", "vector search",
    "inference", "framework", "frameworks", "sdk",
    "开发者", "编程", "工作流", "工具", "推理", "框架",
)
MAJOR_AI_ORG_TERMS = (
    "openai", "anthropic", "claude", "google", "gemini", "deepmind",
    "microsoft", "meta", "nvidia", "deepseek", "qwen", "alibaba",
    "cerebras", "mistral", "xai", "字节", "百度", "腾讯", "华为",
)
REPORT_MIN_CHARS = 600
REQUIRED_REPORT_SECTIONS = (
    "今日AI一句话总结",
    "今日重要AI事件",
    "新模型观察",
    "AI工具发现",
    "AI智能体推荐",
    "AI新名词解释",
    "创造机会分析",
    "学习建议",
)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}


def project_today(now=None) -> date:
    """返回项目时区中的当前自然日，避免依赖服务器默认时区。"""
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    return current.astimezone(LOCAL_TZ).date()


def previous_report_date(now=None) -> str:
    """00:05 结算任务的目标永远是项目时区中的昨天。"""
    return (project_today(now) - timedelta(days=1)).isoformat()


def ensure_report_date_closed(target_date, now=None) -> None:
    """禁止为今天或未来日期生成最终日报。"""
    target = date.fromisoformat(target_date)
    if target >= project_today(now):
        raise RuntimeError(
            f"{target_date} 仍处于采集窗口，最终日报只能在次日 00:05 后生成"
        )


def _task_paths(target_date):
    return (
        UPDATE_STATUS_DIR / f"{target_date}.json",
        UPDATE_STATUS_DIR / f"{target_date}.lock",
    )


def _report_path(target_date):
    return DAILY_DIR / f"{target_date}.md"


def _report_exists(target_date):
    path = _report_path(target_date)
    return path.exists() and path.stat().st_size > 0


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_task_status(target_date, status, error="", started_at=""):
    UPDATE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    status_path, _ = _task_paths(target_date)
    previous = _read_json(status_path)
    now_iso = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    payload = {
        "target_date": target_date,
        "status": status,
        "started_at": started_at or previous.get("started_at", ""),
        "updated_at": now_iso,
        "completed_at": now_iso if status == STATUS_SUCCESS else "",
        "error": str(error)[:300] if error else "",
        "attempt_count": (
            int(previous.get("attempt_count") or 0) + 1
            if status == STATUS_RUNNING
            else int(previous.get("attempt_count") or 0)
        ),
    }
    tmp_path = status_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(status_path)
    return payload


def _date_names(directory, suffix):
    """读取合法日期文件名；运行数据损坏时只忽略坏文件名。"""
    if not directory.exists():
        return set()
    names = set()
    for path in directory.glob(f"*{suffix}"):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        names.add(path.stem)
    return names


def _pool_ready(target_date):
    """只判断信息池能否用于结算，不修改数据。"""
    path = BASE_DIR / "data" / "realtime" / f"{target_date}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    items = payload.get("items")
    collect_date = payload.get("collect_date") or payload.get("date")
    return bool(isinstance(items, list) and items and collect_date in {None, target_date})


def get_report_continuity(now=None):
    """返回已结束自然日的日报连续性，不触发采集或模型调用。"""
    report_dates = _date_names(DAILY_DIR, ".md")
    realtime_dir = BASE_DIR / "data" / "realtime"
    pool_dates = _date_names(realtime_dir, ".json")
    closed_end = previous_report_date(now)

    configured_start = os.environ.get("AI_RADAR_REPORT_START_DATE", "").strip()
    known_dates = sorted(report_dates | pool_dates)
    start_date = configured_start or (known_dates[0] if known_dates else closed_end)
    try:
        cursor = date.fromisoformat(start_date)
    except ValueError:
        cursor = date.fromisoformat(known_dates[0] if known_dates else closed_end)
        start_date = cursor.isoformat()
    end = date.fromisoformat(closed_end)

    expected = []
    while cursor <= end:
        expected.append(cursor.isoformat())
        cursor += timedelta(days=1)

    missing = [item for item in expected if item not in report_dates]
    recoverable = [item for item in missing if _pool_ready(item)]
    missing_pool = [item for item in missing if item not in recoverable]
    task_states = {
        item: get_finalization_status(item)
        for item in missing
    }
    running = [
        item for item in missing
        if task_states[item]["status"] == STATUS_RUNNING
    ]
    failed = [
        item for item in missing
        if task_states[item]["status"] == STATUS_FAILED
    ]
    return {
        "start_date": start_date,
        "closed_end_date": closed_end,
        "expected_count": len(expected),
        "completed_count": len(expected) - len(missing),
        "missing_dates": missing,
        "recoverable_dates": recoverable,
        "missing_pool_dates": missing_pool,
        "running_dates": running,
        "failed_dates": failed,
        "task_states": task_states,
    }


def _automatic_retry_due(status, now=None):
    """自动重试有次数和冷却限制，避免失败时反复消耗模型费用。"""
    if int(status.get("attempt_count") or 0) >= AUTOMATIC_RETRY_LIMIT:
        return False
    updated_at = status.get("updated_at")
    if not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=LOCAL_TZ)
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    return (
        current.astimezone(LOCAL_TZ) - updated.astimezone(LOCAL_TZ)
    ).total_seconds() >= AUTOMATIC_RETRY_COOLDOWN_SECONDS


def find_pending_report_date(now=None, automatic=False, continuity=None):
    """选择一次只结算的一期：昨天优先，其余按最早缺口补齐。"""
    continuity = continuity or get_report_continuity(now)
    if continuity["running_dates"]:
        return None

    yesterday = continuity["closed_end_date"]
    recoverable = continuity["recoverable_dates"]
    ordered = ([yesterday] if yesterday in recoverable else []) + [
        item for item in recoverable if item != yesterday
    ]
    for target_date in ordered:
        status = continuity["task_states"][target_date]
        state = status["status"]
        if state == STATUS_NOT_STARTED:
            return target_date
        if state == STATUS_FAILED and (
            not automatic or _automatic_retry_due(status, now)
        ):
            return target_date
    return None


def _lock_is_stale(lock_path):
    try:
        return time.time() - lock_path.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


def get_finalization_status(target_date):
    """读取跨进程任务状态，不触发采集或模型调用。"""
    status_path, lock_path = _task_paths(target_date)
    saved = _read_json(status_path)

    if _report_exists(target_date):
        return {
            **saved,
            "target_date": target_date,
            "status": STATUS_SUCCESS,
            "error": "",
        }

    if lock_path.exists() and not _lock_is_stale(lock_path):
        return {
            **saved,
            "target_date": target_date,
            "status": STATUS_RUNNING,
            "error": "",
        }

    if lock_path.exists() and _lock_is_stale(lock_path):
        return {
            **saved,
            "target_date": target_date,
            "status": STATUS_FAILED,
            "error": "生成任务超时，可重新生成",
        }

    status = saved.get("status")
    if status == STATUS_RUNNING:
        return {
            **saved,
            "target_date": target_date,
            "status": STATUS_FAILED,
            "error": saved.get("error") or "生成任务异常中断，可重新生成",
        }
    if status == STATUS_FAILED:
        return {**saved, "target_date": target_date}
    if status == STATUS_SUCCESS:
        return {
            **saved,
            "target_date": target_date,
            "status": STATUS_FAILED,
            "error": "任务曾标记成功，但日报文件不存在，可重新生成",
        }
    return {
        "target_date": target_date,
        "status": STATUS_NOT_STARTED,
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
        "error": "",
    }


def claim_finalization_task(target_date, force=False):
    """原子抢占日期级任务锁；返回所有权令牌，未抢到返回 None。"""
    ensure_report_date_closed(target_date)
    if _report_exists(target_date) and not force:
        _write_task_status(target_date, STATUS_SUCCESS)
        return None

    UPDATE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    _, lock_path = _task_paths(target_date)
    if lock_path.exists() and _lock_is_stale(lock_path):
        try:
            lock_path.unlink()
        except OSError:
            return None

    owner_token = uuid.uuid4().hex
    started_at = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    lock_payload = json.dumps({
        "target_date": target_date,
        "owner_token": owner_token,
        "pid": os.getpid(),
        "started_at": started_at,
    }, ensure_ascii=False).encode("utf-8")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        os.write(descriptor, lock_payload)
    finally:
        os.close(descriptor)

    _write_task_status(target_date, STATUS_RUNNING, started_at=started_at)
    return owner_token


def _release_finalization_lock(target_date, owner_token):
    _, lock_path = _task_paths(target_date)
    lock_data = _read_json(lock_path)
    if lock_data.get("owner_token") == owner_token:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def run_claimed_finalization(target_date, owner_token, force=False):
    """执行已经抢占的结算任务，并持久化最终状态。"""
    try:
        generated = finalize_report(target_date, force=force)
        if not _report_exists(target_date):
            raise RuntimeError(f"{target_date} 结算结束但日报文件不存在")
        _write_task_status(target_date, STATUS_SUCCESS)
        return generated
    except Exception as exc:
        _write_task_status(target_date, STATUS_FAILED, error=exc)
        raise
    finally:
        _release_finalization_lock(target_date, owner_token)


def run_finalization_task(target_date, force=False):
    """使用共享日期锁运行结算；已有任务运行时不会重复调用模型。"""
    owner_token = claim_finalization_task(target_date, force=force)
    if owner_token:
        return run_claimed_finalization(target_date, owner_token, force=force)

    status = get_finalization_status(target_date)
    if status["status"] == STATUS_SUCCESS:
        return False
    raise RuntimeError(f"{target_date} 日报生成任务已在运行")

# ------------------------------------------------------------------
# 第一步：抓取素材（已验证可用的公开信源）
# ------------------------------------------------------------------
def fetch_hn(max_items=25):
    """Hacker News Algolia API：近2天高分AI相关帖子"""
    import time
    since = int(time.time()) - 2 * 86400
    queries = ["AI", "LLM", "model", "agent", "Claude", "GPT", "Gemini", "DeepSeek", "Qwen"]
    seen, items = set(), []
    for q in queries:
        url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            f"?query={urllib.request.quote(q)}&tags=story"
            f"&numericFilters=created_at_i>{since},points>25&hitsPerPage=10"
        )
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
            for h in data.get("hits", []):
                if h.get("objectID") in seen:
                    continue
                seen.add(h.get("objectID"))
                items.append({
                    "source": "HackerNews",
                    "title": h.get("title") or "",
                    "url": h.get("url") or "",
                    "date": (h.get("created_at") or "")[:10],
                    "points": h.get("points") or 0,
                })
        except Exception as e:
            print(f"  [警告] HN查询 '{q}' 失败: {e}")
    items.sort(key=lambda x: -x["points"])
    return items[:max_items]


def fetch_rss(name, url, max_items=12):
    """通用 RSS 抓取（TechCrunch / VentureBeat 等）"""
    import html
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        data = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        items = []
        for block in re.findall(r"<item>(.*?)</item>", data, re.S)[:max_items]:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            d = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
            p = re.search(r"<pubDate>(.*?)</pubDate>", block)
            title = html.unescape(t.group(1).strip()) if t else ""
            desc = html.unescape(re.sub(r"<[^>]+>", " ", d.group(1))).strip()[:200] if d else ""
            items.append({
                "source": name,
                "title": title,
                "url": "",
                "date": (p.group(1).strip() if p else "")[:16],
                "summary": desc,
            })
        return items
    except Exception as e:
        print(f"  [警告] {name} 抓取失败: {e}")
        return []


def collect_material():
    """汇总所有信源素材"""
    print("  → Hacker News ...")
    material = fetch_hn()
    print("  → TechCrunch AI ...")
    material += fetch_rss("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/")
    print("  → VentureBeat AI ...")
    material += fetch_rss("VentureBeat", "https://venturebeat.com/category/ai/feed/")
    return material


# ------------------------------------------------------------------
# 第二步：调用 OpenAI 生成日报
# ------------------------------------------------------------------
ANALYST_PROMPT = """你是一名资深AI行业分析师，同时也是AI应用创业顾问。用户是一位20岁的AI应用开发者（非算法工程师），关注：最新AI模型、AI工具、AI Agent、AI创业机会、AI行业趋势。

根据下面的【今日素材】，生成《AI信息雷达日报》，要求：

# 筛选规则
- A级：对未来AI发展有明显影响（新模型发布、能力突破、重要产品上线）
- B级：对AI应用开发者有帮助（新工具、新工作流、新案例）
- C级：普通新闻，一句话带过即可
- 不追求数量追求价值；每条信息回答"这和用户有什么关系"；不制造焦虑；专业词必须解释

# 输出格式（严格遵循，Markdown格式）
# 📡 AI信息雷达日报 | <日期>
## 今日AI一句话总结
（一句话说明今天AI行业最大的变化）
# 1. 今日重要AI事件
每条含：标题/发生了什么/为什么重要/影响/普通人可以做什么/推荐指数（⭐1-5个），标注A级或B级
# 2. 新模型观察
每个模型用表格：公司/发布时间/主要能力/相比之前提升/适合什么场景（无新模型则写"今日无重大新模型发布"）
# 3. AI工具发现
每个工具：用途/解决什么问题/普通用户如何使用/是否值得学习
# 3.5 AI智能体推荐
从今日素材中筛选可下载/可关注的AI智能体，用表格列出：智能体名称/主要用来做什么/适合谁/下载或官方链接（链接必须真实，仅限素材中出现的地址；无下载渠道的注明"预览中"；研究向智能体注明慎用）
# 4. AI新名词解释
关键词/简单解释/为什么最近出现/未来影响
# 5. 创造机会分析
站在20岁AI应用开发者角度，2-3个项目方向，含：项目方向/目标用户/解决问题/实现难度/推荐程度
# 6. 学习建议
今天最值得深入了解的方向，不超过3个；每个方向必须附1-3个可点击的学习链接（Markdown链接格式，优先素材中出现的官方博客/文档/论文/GitHub地址，确保链接真实存在）

只输出日报正文Markdown，不要其他解释。"""


def call_router(material_text, target_date):
    """调用 OpenAI Responses API，保持原有的 str 返回契约。"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY，请先配置 OpenAI API Key")

    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    if not model:
        raise RuntimeError("OPENAI_MODEL 不能为空")

    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL 不能为空")

    input_text = (
        f"今天是 {target_date}。\n\n【今日素材】\n{material_text}\n\n"
        "请基于以上素材生成今日《AI信息雷达日报》。素材不足的部分如实说明，不要编造。"
    )
    payload = {
        "model": model,
        "instructions": ANALYST_PROMPT,
        "input": input_text,
        "max_output_tokens": 12000,
    }
    req = urllib.request.Request(
        f"{base_url}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**HEADERS, "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        raw = urllib.request.urlopen(req, timeout=300).read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API 网络请求失败: {exc.reason}") from exc

    try:
        resp = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI API 返回的不是合法 JSON") from exc

    # Responses API 通常提供顶层 output_text；兼容标准 output 内容块结构。
    text = resp.get("output_text") if isinstance(resp, dict) else None
    if not isinstance(text, str):
        chunks = []
        for item in resp.get("output", []) if isinstance(resp, dict) else []:
            if not isinstance(item, dict):
                continue
            for block in item.get("content", []):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "output_text"
                    and isinstance(block.get("text"), str)
                ):
                    chunks.append(block["text"])
        text = "".join(chunks)

    if not text.strip():
        raise RuntimeError(f"OpenAI API 返回内容为空或结构异常: {str(resp)[:300]}")
    return text.strip()


def material_to_text(material, limit=60):
    """把素材列表转成给模型的纯文本"""
    lines = []
    for i, m in enumerate(material[:limit], 1):
        parts = [f"{i}. [{m['source']}] {m['title']}"]
        if m.get("summary"):
            parts.append(f"   摘要: {m['summary']}")
        if m.get("url"):
            parts.append(f"   链接: {m['url']}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


# ------------------------------------------------------------------
# 前一天信息池结算：规则初筛 → 事件去重 → 单次 AI 分析
# ------------------------------------------------------------------
def _title_tokens(title):
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (title or "").lower())
    tokens = {token for token in normalized.split() if len(token) >= 2}
    for block in re.findall(r"[\u4e00-\u9fff]+", normalized):
        tokens.update(block[index:index + 2] for index in range(len(block) - 1))
    return tokens


def _contains_term(text, term):
    """英文按完整单词/短语匹配，避免 `ai`、`valuation` 等子串误判。"""
    if term.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _item_text(item):
    return " ".join([
        str(item.get("source") or ""),
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("category") or ""),
    ]).lower()


def _is_ai_relevant(item):
    """拦截被热度或默认分类误判的非 AI 内容。"""
    text = _item_text(item)
    return any(_contains_term(text, term) for term in AI_RELEVANCE_TERMS)


def _same_event(left, right):
    left_url = (left.get("link") or left.get("url") or "").strip().rstrip("/")
    right_url = (right.get("link") or right.get("url") or "").strip().rstrip("/")
    if left_url and right_url and left_url == right_url:
        return True

    left_title = (left.get("title") or "").strip().lower()
    right_title = (right.get("title") or "").strip().lower()
    if not left_title or not right_title:
        return False
    ratio = difflib.SequenceMatcher(None, left_title, right_title).ratio()
    if ratio >= 0.84:
        return True
    left_tokens, right_tokens = _title_tokens(left_title), _title_tokens(right_title)
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(shared) >= 3 and union and len(shared) / len(union) >= 0.58


def _candidate_score(item):
    """规则评分：用于选候选，不替代最终 AI 判断。"""
    score = {"A": 7, "B": 4, "C": 1}.get(item.get("importance"), 1)
    source_type = (item.get("source_type") or "").lower()
    source = item.get("source") or ""
    if source_type == "official" or source in {"QwenBlog", "DeepSeek"}:
        score += 3
    elif source_type == "rss":
        score += 2
    elif source_type == "academic":
        score += 1
    elif source_type == "community":
        score += 1
    score += min(3, int(math.log10(max(1, int(item.get("points") or 0) + 1))))
    if item.get("summary"):
        score += 1
    if item.get("link") or item.get("url"):
        score += 1
    if item.get("published_at") or item.get("timestamp"):
        score += 1
    text = _item_text(item)
    if any(_contains_term(text, term) for term in HIGH_IMPACT_TERMS):
        score += 2
    if any(_contains_term(text, term) for term in DEVELOPER_VALUE_TERMS):
        score += 1
    if any(_contains_term(text, term) for term in MAJOR_AI_ORG_TERMS):
        score += 3
    return score


def select_candidates(items, limit=CANDIDATE_LIMIT):
    """过滤非 AI 内容、跨批次去重，并控制单一信源类型占比。"""
    ranked = sorted(
        (
            item for item in items
            if _is_ai_relevant(item) and _candidate_score(item) >= MIN_CANDIDATE_SCORE
        ),
        key=_candidate_score,
        reverse=True,
    )
    unique = []
    for item in ranked:
        duplicate_index = next(
            (index for index, selected in enumerate(unique) if _same_event(item, selected)),
            None,
        )
        if duplicate_index is None:
            unique.append(item)
        elif _candidate_score(item) > _candidate_score(unique[duplicate_index]):
            unique[duplicate_index] = item

    selected = []
    deferred = []
    source_type_counts = {}
    for item in sorted(unique, key=_candidate_score, reverse=True):
        source_type = (item.get("source_type") or "unknown").lower()
        source_limit = CANDIDATE_SOURCE_TYPE_LIMITS.get(source_type, limit)
        if source_type_counts.get(source_type, 0) >= source_limit:
            deferred.append(item)
            continue
        selected.append(item)
        source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
        if len(selected) >= limit:
            return selected

    # 配额只拦截普通内容；额外的高分重大事件仍可回补，避免漏报。
    for item in deferred:
        if len(selected) >= limit:
            break
        if _candidate_score(item) >= HIGH_VALUE_BACKFILL_SCORE:
            selected.append(item)
    return sorted(selected, key=_candidate_score, reverse=True)


def _candidate_text(candidates):
    lines = [
        "【程序初筛后的候选事件】",
        "以下事件已经经过规则评分和事件级去重。只基于这些候选分析，不要补造未提供的事实。",
        "每条重要事件必须明确保留信源、原始发布时间和原始链接。",
    ]
    for index, item in enumerate(candidates, 1):
        link = item.get("link") or item.get("url") or "无原始链接"
        published_at = item.get("published_at") or item.get("timestamp") or "未知"
        lines.append(
            "\n".join([
                f"{index}. 标题：{item.get('title', '')}",
                f"   信源：{item.get('source', '')}（{item.get('source_type', '')}）",
                f"   发布时间：{published_at}",
                f"   规则初筛级别：{item.get('importance', '') or '未知'}；规则分：{_candidate_score(item)}",
                f"   热度：{item.get('points', 0)}；摘要：{item.get('summary', '') or '无'}",
                f"   原始链接：{link}",
            ])
        )
    return "\n\n".join(lines)


def _normalize_report_url(url):
    """统一来源链接，忽略尾部斜杠、锚点和常见追踪参数。"""
    value = (url or "").strip().rstrip(".,;:!?，。；：！？”’\"")
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [
        (key, item_value)
        for key, item_value in query
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        urllib.parse.urlencode(query, doseq=True),
        "",
    ))


def _extract_report_urls(text):
    urls = re.findall(r"https?://[^\s<>\])}]+", text or "")
    return {
        normalized
        for normalized in (_normalize_report_url(url) for url in urls)
        if normalized
    }


def repair_candidate_urls(report, candidates):
    """把模型轻微拼错的同域名链接恢复为候选原始链接。"""
    candidate_urls = {
        normalized
        for normalized in (
            _normalize_report_url(item.get("link") or item.get("url"))
            for item in candidates
        )
        if normalized
    }
    replacements = {}
    for raw_url in re.findall(r"https?://[^\s<>\])}]+", report or ""):
        normalized = _normalize_report_url(raw_url)
        if not normalized or normalized in candidate_urls:
            continue
        parsed = urllib.parse.urlsplit(normalized)
        matches = []
        for candidate_url in candidate_urls:
            candidate_parsed = urllib.parse.urlsplit(candidate_url)
            if candidate_parsed.netloc != parsed.netloc:
                continue
            ratio = difflib.SequenceMatcher(
                None,
                parsed.path.rstrip("/"),
                candidate_parsed.path.rstrip("/"),
            ).ratio()
            if ratio >= 0.88:
                matches.append((ratio, candidate_url))
        matches.sort(reverse=True)
        if matches and (len(matches) == 1 or matches[0][0] - matches[1][0] >= 0.05):
            replacements[raw_url] = matches[0][1]

    repaired = report
    for raw_url, candidate_url in replacements.items():
        repaired = repaired.replace(raw_url, candidate_url)
    return repaired


def _extract_important_events_section(report):
    start = re.search(
        r"(?m)^#{1,6}\s+(?:1\.\s*)?今日重要AI事件\s*$",
        report,
    )
    if not start:
        return ""
    remainder = report[start.end():]
    end = re.search(
        r"(?m)^#{1,6}\s+(?:2\.\s*)?新模型观察\s*$",
        remainder,
    )
    return remainder[:end.start()] if end else remainder


def validate_daily_report(report, target_date, candidates):
    """在正式落盘前校验 AI 日报的日期、结构和来源可追溯性。"""
    text = (report or "").strip()
    errors = []
    if len(text) < REPORT_MIN_CHARS:
        errors.append(f"正文过短（{len(text)} 字符，至少 {REPORT_MIN_CHARS}）")
    if text.startswith("```"):
        errors.append("正文被整个包在代码块中")

    headings = [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    ]
    first_heading = headings[0] if headings else ""
    if "AI信息雷达日报" not in first_heading or target_date not in first_heading:
        errors.append(f"日报标题未明确标注目标日期 {target_date}")

    missing_sections = [
        section
        for section in REQUIRED_REPORT_SECTIONS
        if not any(section in heading for heading in headings)
    ]
    if missing_sections:
        errors.append("缺少板块：" + "、".join(missing_sections))

    important_section = _extract_important_events_section(text)
    candidate_urls = {
        normalized
        for normalized in (
            _normalize_report_url(item.get("link") or item.get("url"))
            for item in candidates
        )
        if normalized
    }
    if candidate_urls:
        event_urls = _extract_report_urls(important_section)
        if not event_urls:
            errors.append("今日重要AI事件没有保留任何原始链接")
        else:
            unknown_urls = sorted(event_urls - candidate_urls)
            if unknown_urls:
                errors.append("重要事件包含素材之外的链接：" + "、".join(unknown_urls[:3]))

    candidate_sources = {
        str(item.get("source") or "").strip().lower()
        for item in candidates
        if str(item.get("source") or "").strip()
    }
    if candidate_sources and important_section and not any(
        source in important_section.lower() for source in candidate_sources
    ):
        errors.append("今日重要AI事件没有标注候选素材中的信源")

    if errors:
        raise RuntimeError("AI 日报质量校验失败：" + "；".join(errors))
    return text


def load_realtime_pool(target_date):
    path = BASE_DIR / "data" / "realtime" / f"{target_date}.json"
    if not path.exists():
        raise RuntimeError(f"当天信息池不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"当天信息池无法读取: {exc}") from exc
    collect_date = payload.get("collect_date") or payload.get("date")
    if collect_date and collect_date != target_date:
        raise RuntimeError(
            f"信息池日期不匹配: 请求 {target_date}，文件标记为 {collect_date}"
        )
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"当天信息池为空: {path}")
    return items


def _item_local_date(item):
    """解析候选事件的发布时间；无法解析时返回 None，交由上层保留。"""
    timestamp = str(item.get("published_at") or item.get("timestamp") or "").strip()
    if not timestamp:
        return None

    parsed = None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(timestamp)
        except (TypeError, ValueError):
            return None

    if parsed.tzinfo is None:
        assumed_tz = timezone.utc if item.get("source") == "HackerNews" else LOCAL_TZ
        parsed = parsed.replace(tzinfo=assumed_tz)
    return parsed.astimezone(LOCAL_TZ).date()


def filter_pool_for_date(items, target_date):
    """只保留发布时间明确落在目标自然日内的信息。"""
    target = date.fromisoformat(target_date)
    return [item for item in items if _item_local_date(item) == target]


def _is_finalized_report(path: Path, target_date: str) -> bool:
    """识别已经由全天信息池结算过的日报，兼容迁移前的旧日报。"""
    try:
        marker = FINALIZED_MARKER.format(date=target_date)
        return marker in path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False


def finalize_report(target_date, force=False, now=None):
    """读取完整信息池生成指定日期最终日报，不触发采集。"""
    ensure_report_date_closed(target_date, now=now)
    out_path = DAILY_DIR / f"{target_date}.md"
    if out_path.exists() and not force and _is_finalized_report(out_path, target_date):
        print(f"[跳过] {out_path} 已完成全天信息池结算，信息池仍可继续采集")
        return False

    pool = load_realtime_pool(target_date)
    dated_pool = filter_pool_for_date(pool, target_date)
    candidates = select_candidates(dated_pool)
    if not candidates:
        raise RuntimeError(f"{target_date} 没有可分析的候选事件")
    print(
        f"  完整信息池: {len(pool)} 条；目标日期有效: {len(dated_pool)} 条；"
        f"规则去重后候选: {len(candidates)} 条"
    )
    report = call_router(_candidate_text(candidates), target_date)
    report = repair_candidate_urls(report, candidates)
    report = validate_daily_report(report, target_date, candidates)
    report = report.rstrip() + "\n\n" + FINALIZED_MARKER.format(date=target_date) + "\n"

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".md.tmp")
    tmp_path.write_text(report, encoding="utf-8")
    tmp_path.replace(out_path)
    print(f"✅ 最终日报已生成: {out_path}（{len(report)} 字符）")
    return True


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="生成AI信息雷达日报")
    parser.add_argument("--date", default=project_today().isoformat(), help="素材日期 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="覆盖已有日报")
    parser.add_argument("--material-only", action="store_true", help="只抓素材不调用模型")
    parser.add_argument("--no-api", action="store_true", help="准备素材后提示手动生成（不消耗token）")
    parser.add_argument("--include-realtime", action="store_true",
                        help="合并 data/realtime/<date>.json 的采集数据作为额外素材")
    parser.add_argument("--finalize-date", help="只读取指定日期信息池，生成最终日报，不重新采集")
    parser.add_argument("--finalize-yesterday", action="store_true",
                        help="只结算昨天完整信息池，供 00:05 定时任务使用")
    parser.add_argument("--finalize-pending", action="store_true",
                        help="结算一期待补日报：昨天优先，其余按最早缺口；自动限制失败重试")
    args = parser.parse_args()

    if args.finalize_date or args.finalize_yesterday or args.finalize_pending:
        target = (
            args.finalize_date
            or (find_pending_report_date(automatic=True) if args.finalize_pending else None)
            or (previous_report_date() if args.finalize_yesterday else None)
        )
        if target is None:
            print("[跳过] 当前没有达到自动重试条件的待补日报")
            return
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", target):
            print(f"[错误] 日期格式不正确: {target}（应为 YYYY-MM-DD）")
            sys.exit(1)
        try:
            run_finalization_task(target, force=args.force)
        except Exception as exc:
            print(f"[错误] 结算 {target} 失败: {exc}")
            sys.exit(2)
        return

    target = args.date
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target):
        print(f"[错误] 日期格式不正确: {target}（应为 YYYY-MM-DD）")
        sys.exit(1)

    if not args.material_only and not args.no_api:
        print("[错误] 直接抓取后生成日报的旧入口已停用。")
        print("请使用 --finalize-yesterday 或 --finalize-date YYYY-MM-DD 结算完整信息池。")
        sys.exit(2)

    out_path = DAILY_DIR / f"{target}.md"
    if out_path.exists() and not args.force:
        print(f"[跳过] {out_path} 已存在，加 --force 可覆盖")
        sys.exit(0)

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print(f"📡 开始生成 {target} 的日报")
    print("第1步：抓取素材")
    material = collect_material()

    # 可选：合并实时采集模块的数据作为增强素材
    if args.include_realtime:
        realtime_path = BASE_DIR / "data" / "realtime" / f"{target}.json"
        if realtime_path.exists():
            try:
                rt_data = json.loads(realtime_path.read_text(encoding="utf-8"))
                rt_items = rt_data.get("items", [])
                # 把 realtime 数据转换为 material 格式，去重后合并
                existing_urls = {m.get("url", "") for m in material}
                added = 0
                for item in rt_items:
                    if item.get("link") and item["link"] not in existing_urls:
                        material.append({
                            "source": f"{item.get('source', '')}(realtime)",
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "date": item.get("timestamp", "")[:10],
                            "summary": item.get("summary", "")[:200],
                            "importance": item.get("importance", ""),
                            "category": item.get("category", ""),
                        })
                        existing_urls.add(item["link"])
                        added += 1
                print(f"  已合并实时采集数据: +{added} 条（共 {len(material)} 条素材）")
            except Exception as e:
                print(f"  [警告] 合并实时采集数据失败: {e}")
        else:
            print(f"  [提示] 今日尚无实时采集数据，可先运行 python src/collector.py")

    if not material:
        print("[错误] 所有信源均抓取失败，请检查网络")
        sys.exit(1)

    raw_path = RAW_DIR / f"{target}.json"
    raw_path.write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  素材已保存: {raw_path}（{len(material)} 条）")

    if args.material_only:
        print("✅ 仅抓取素材完成")
        return

    if args.no_api:
        print(f"\n✅ 素材已就绪。请在 Claude Code 中说："
              f"\"根据 data/raw/{target}.json 素材生成今日AI信息雷达日报，"
              f"按分析师模板写入 data/daily/{target}.md\"")
        return

    print("第2步：调用 OpenAI 生成日报（约1-3分钟）")
    try:
        report = call_router(material_to_text(material), target)
    except Exception as e:
        print(f"\n[错误] 调用 OpenAI 失败: {e}")
        print("请确认 OPENAI_API_KEY 和 OPENAI_MODEL 配置正确，或改用 --no-api 手动生成。")
        print(f"素材仍可用: {raw_path}")
        sys.exit(2)

    out_path.write_text(report, encoding="utf-8")
    print(f"✅ 日报已生成: {out_path}")
    print("⚠️ 建议人工检查内容后，运行 python src/app.py 查看效果")


if __name__ == "__main__":
    main()
