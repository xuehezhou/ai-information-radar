# -*- coding: utf-8 -*-
"""
AI信息雷达 · 每日资讯查看应用
Flask 主应用：首页（新闻门户）+ 日报详情页
数据存储：data/daily/YYYY-MM-DD.md（纯 Markdown 文件即数据库）

v1.7: 新增手机 App 离线同步 API（/api/reports、/api/read/<date>）
"""

import json
import logging
import os
import re
import socket
import sys
import threading
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Windows 控制台默认 GBK，无法输出 emoji/部分中文 → 强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import markdown
from flask import Flask, abort, jsonify, render_template

# ------------------------------------------------------------------
# 路径与常量
# ------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # PyInstaller 打包模式：数据目录在 exe 旁边（日报/已读状态可持久化、可随应用拷走）
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent   # ai-radar 根目录
DAILY_DIR = BASE_DIR / "data" / "daily"
REALTIME_DIR = BASE_DIR / "data" / "realtime"
READ_STATUS_PATH = BASE_DIR / "data" / "read_status.json"
CATCHUP_LOG_PATH = BASE_DIR / "data" / "catchup.log"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")        # 日期白名单，防路径穿越
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
FINALIZATION_START_MINUTE = 5
INSTANCE_ID = "ai-radar-portable-source"


def project_now(now=None) -> datetime:
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    return current.astimezone(LOCAL_TZ)


def project_today(now=None) -> date:
    return project_now(now).date()


def report_target_date(now=None) -> str:
    """最终日报的目标日期始终是上海时区中的昨天。"""
    return (project_today(now) - timedelta(days=1)).isoformat()


def finalization_window_open(now=None) -> bool:
    """每天 00:05 后才允许手动兜底启动昨日日报结算。"""
    current = project_now(now)
    return current.hour * 60 + current.minute >= FINALIZATION_START_MINUTE

if getattr(sys, "frozen", False):
    # 打包版：模板/静态资源在 PyInstaller 资源目录（_MEIPASS）
    _res_dir = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    app = Flask(
        __name__,
        template_folder=str(_res_dir / "templates"),
        static_folder=str(_res_dir / "static"),
    )
    # 无控制台 exe 下 stdout/stderr 为 None，重定向到日志文件避免 print 崩溃
    if sys.stdout is None:
        _logs = BASE_DIR / "data"
        _logs.mkdir(parents=True, exist_ok=True)
        _logf = open(_logs / "app.log", "a", encoding="utf-8")
        sys.stdout = _logf
        sys.stderr = _logf
else:
    app = Flask(__name__)

# 补录日志
_catchup_logger = None

# 当天日报更新状态只保存在当前进程内；日报文件本身是成功状态的持久依据。
_daily_update_lock = threading.Lock()
_daily_update_status = {}


def _get_catchup_logger():
    global _catchup_logger
    if _catchup_logger is None:
        _catchup_logger = logging.getLogger("catchup")
        _catchup_logger.setLevel(logging.INFO)
        file_logging = True
        try:
            h = logging.FileHandler(str(CATCHUP_LOG_PATH), encoding="utf-8")
        except OSError as exc:
            # 日志目录不可写时，不能阻断日报采集；降级到控制台输出。
            file_logging = False
            h = logging.StreamHandler(sys.stderr)
            print(f"[警告] 无法写入补录日志，改用控制台输出: {exc}", file=sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        _catchup_logger.addHandler(h)
        if file_logging:
            _catchup_logger.addHandler(logging.StreamHandler(sys.stderr))
    return _catchup_logger


# ------------------------------------------------------------------
# 已读/未读状态管理
# ------------------------------------------------------------------
def load_read_status():
    """读取已读状态。返回 { '2026-08-05': '2026-08-10T15:30:00', ... }"""
    if not READ_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(READ_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_read_status(status):
    """保存已读状态到 JSON 文件。"""
    READ_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    READ_STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mark_read(date_str):
    """将某期日报标记为已读（仅在首次阅读时记录时间戳）。"""
    status = load_read_status()
    if date_str not in status:
        from datetime import datetime
        status[date_str] = datetime.now().isoformat()
        save_read_status(status)


# ------------------------------------------------------------------
# 数据读取辅助函数
# ------------------------------------------------------------------
def list_issues():
    """列出已经结束自然日的日报；今天只能作为实时信息池。"""
    if not DAILY_DIR.exists():
        return []
    today_date = project_today()
    dates = sorted(
        (
            p.stem for p in DAILY_DIR.glob("*.md")
            if DATE_RE.match(p.stem) and date.fromisoformat(p.stem) < today_date
        ),
        reverse=True,
    )
    return dates


def read_issue(date_str):
    """读取一期日报原文。不存在返回 None。"""
    if not DATE_RE.match(date_str) or date.fromisoformat(date_str) >= project_today():
        return None
    path = DAILY_DIR / f"{date_str}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def parse_summary(md_text):
    """提取「今日AI一句话总结」段落（第一个 ## 标题后的第一段）。"""
    m = re.search(
        r"##\s*今日AI一句话总结\s*\n+(.+?)(?=\n\s*\n|\n#|\n---|\Z)",
        md_text,
        re.S,
    )
    if not m:
        return ""
    summary = m.group(1).strip()
    # 去掉 Markdown 加粗标记，保留纯文本给首页卡片用
    return re.sub(r"\*\*(.+?)\*\*", r"\1", summary)


def parse_stats(md_text):
    """统计日报关键数字，用于首页卡片展示。"""
    # 事件数：匹配 "## ... 事件X ..." 或 "## 事件X"
    events = len(re.findall(r"^##\s*[^\n]*事件[一二三四五六七八九十\d]+", md_text, re.M))
    # 新模型数：只统计第2节内的 "### ① ② ③"（避免把第3节工具序号误算进来）
    sec2 = re.search(r"#\s*2\.[^\n]*\n(.*?)(?=\n#\s*3\.|\Z)", md_text, re.S)
    models = len(re.findall(r"^###\s*[①②③④⑤⑥⑦⑧⑨⑩]", sec2.group(1), re.M)) if sec2 else 0
    # 创造机会数：第5节 "### 机会X"
    chances = len(re.findall(r"^###\s*机会[一二三四五六七八九十\d]+", md_text, re.M))
    # A级事件数：标题含 "（A级）"
    a_level = len(re.findall(r"（A级）", md_text))
    return {
        "events": events,
        "models": models,
        "chances": chances,
        "a_level": a_level,
    }


def render_markdown(md_text):
    """渲染日报 Markdown 为 HTML（支持表格、代码块）。"""
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )


def load_realtime_info(target_date=None):
    """读取当日实时采集数据的摘要信息。

    返回 None 表示今天尚未采集；返回摘要、分类和最近一次信源健康状态。
    采集模块独立于此函数——此函数仅读取已有数据，不触发采集。
    """
    if target_date is None:
        target_date = project_today().isoformat()
    path = REALTIME_DIR / f"{target_date}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stats = data.get("stats", {})
        a_count = stats.get("by_importance", {}).get("A", 0)
        source_health = stats.get("source_health", {})
        health_summary = stats.get("source_health_summary", {})
        failed_sources = sorted(
            name
            for name, item in source_health.items()
            if item.get("status") == "failed"
        )
        partial_sources = sorted(
            name
            for name, item in source_health.items()
            if item.get("status") == "partial"
        )
        empty_sources = sorted(
            name
            for name, item in source_health.items()
            if item.get("status") == "empty"
        )
        return {
            "total": data.get("total", 0),
            "a_count": a_count,
            "by_category": stats.get("by_category", {}),
            "source_health_total": health_summary.get("total", 0),
            "source_health_available": health_summary.get("available", 0),
            "failed_sources": failed_sources,
            "partial_sources": partial_sources,
            "empty_sources": empty_sources,
        }
    except Exception:
        return None


# ------------------------------------------------------------------
# 全局模板变量（刊头需要）
# ------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        "today": project_today().strftime("%Y年%m月%d日"),
        "total": len(list_issues()),
    }


# ------------------------------------------------------------------
# 路由
# ------------------------------------------------------------------
@app.route("/")
def index():
    """首页：新闻门户风格，日报卡片列表（未读/已读分开）"""
    today_date = project_today().isoformat()
    today_update = start_today_update_if_needed(today_date)
    read_status = load_read_status()
    daily_reports = []
    for date_str in list_issues():
        md_text = read_issue(date_str)
        if md_text is None:
            continue
        daily_reports.append({
            "date": date_str,
            "summary": parse_summary(md_text),
            "stats": parse_stats(md_text),
            "is_read": date_str in read_status,
            "read_at": read_status.get(date_str, ""),
        })

    # 拆分：未读在前，已读在后
    unread = [item for item in daily_reports if not item["is_read"]]
    read_issues = [item for item in daily_reports if item["is_read"]]

    latest_completed_report = daily_reports[0] if daily_reports else None
    today_realtime = load_realtime_info(today_date)
    report_update_status = get_report_update_status()
    return render_template(
        "index.html",
        daily_reports=daily_reports,
        unread=unread,
        read_issues=read_issues,
        latest_completed_report=latest_completed_report,
        today_realtime=today_realtime,
        today_date=today_date,
        today_update=today_update,
        report_update_status=report_update_status,
    )


@app.route("/daily/<date_str>")
def daily(date_str):
    """日报详情页：渲染完整 Markdown，首次访问标记已读"""
    if not DATE_RE.match(date_str):
        abort(404)
    md_text = read_issue(date_str)
    if md_text is None:
        abort(404)

    issues = list_issues()
    try:
        idx = issues.index(date_str)
        newer = issues[idx - 1] if idx > 0 else None          # 更晚的一期
        older = issues[idx + 1] if idx < len(issues) - 1 else None  # 更早的一期
    except ValueError:
        newer = older = None

    # 标记已读
    mark_read(date_str)

    return render_template(
        "daily.html",
        content=render_markdown(md_text),
        date_str=date_str,
        newer=newer,
        older=older,
    )


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


# ------------------------------------------------------------------
# 手机 App 同步 API（离线版 APK 使用）
# ------------------------------------------------------------------
def _report_json(date_str, md_text):
    """把一期日报转成手机 App 用的 JSON 结构（含渲染 HTML + 上一篇/下一篇）。"""
    issues = list_issues()
    try:
        idx = issues.index(date_str)
        newer = issues[idx - 1] if idx > 0 else None          # 更晚一期
        older = issues[idx + 1] if idx < len(issues) - 1 else None  # 更早一期
    except ValueError:
        newer = older = None
    return {
        "date": date_str,
        "summary": parse_summary(md_text),
        "stats": parse_stats(md_text),
        "is_read": date_str in load_read_status(),
        "newer": newer,
        "older": older,
        "html": render_markdown(md_text),
    }


@app.route("/api/reports")
def api_reports():
    """手机 App 同步接口：返回全部日报（元信息 + 渲染 HTML + 已读状态）。"""
    reports = []
    for date_str in list_issues():
        md_text = read_issue(date_str)
        if md_text is None:
            continue
        reports.append(_report_json(date_str, md_text))
    return app.response_class(
        json.dumps({"reports": reports}, ensure_ascii=False),
        mimetype="application/json; charset=utf-8",
    )


@app.route("/api/read/<date_str>", methods=["POST"])
def api_mark_read(date_str):
    """手机 App 上报已读状态（fire-and-forget，供电脑端同步展示）。"""
    if DATE_RE.match(date_str):
        mark_read(date_str)
    return "", 204


# ------------------------------------------------------------------
# 昨日最终日报状态与手动兜底
# ------------------------------------------------------------------
def _finalization_module():
    """延迟导入结算模块，保持源码运行和 PyInstaller 入口兼容。"""
    source_dir = str(BASE_DIR / "src")
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import generate_daily
    return generate_daily


def get_report_update_status(now=None):
    """读取昨日结算和历史连续性状态，不触发采集或模型调用。"""
    target_date = report_target_date(now)
    finalization = _finalization_module()
    status = finalization.get_finalization_status(target_date)
    continuity = finalization.get_report_continuity(now)
    active_target_date = (
        continuity["running_dates"][0]
        if continuity["running_dates"]
        else None
    )
    next_pending_date = finalization.find_pending_report_date(
        now,
        automatic=False,
        continuity=continuity,
    )
    issues = list_issues()
    return {
        "target_date": target_date,
        "status": status["status"],
        "latest_completed_date": issues[0] if issues else None,
        "started_at": status.get("started_at", ""),
        "updated_at": status.get("updated_at", ""),
        "completed_at": status.get("completed_at", ""),
        "error": status.get("error", ""),
        "can_start": bool(
            next_pending_date
            and not active_target_date
            and (next_pending_date != target_date or finalization_window_open(now))
        ),
        "active_target_date": active_target_date,
        "next_pending_date": next_pending_date,
        "continuity": {
            key: value
            for key, value in continuity.items()
            if key != "task_states"
        },
    }


def _run_claimed_report_finalization(target_date, owner_token):
    """后台结算线程入口；失败只记录状态，不影响 Flask 请求。"""
    try:
        _finalization_module().run_claimed_finalization(target_date, owner_token)
    except Exception as exc:
        _get_catchup_logger().warning(
            "日报兜底结算 %s 失败: %s", target_date, str(exc)[:300]
        )


def start_report_finalization_if_needed(now=None):
    """启动一期可恢复的缺失日报；昨天优先，所有入口共享日期锁。"""
    status = get_report_update_status(now)
    if status["active_target_date"] or not status["can_start"]:
        return status

    target_date = status["next_pending_date"]
    owner_token = _finalization_module().claim_finalization_task(target_date)
    if owner_token:
        thread = threading.Thread(
            target=_run_claimed_report_finalization,
            args=(target_date, owner_token),
            daemon=True,
            name=f"daily-finalize-{target_date}",
        )
        thread.start()
    return get_report_update_status(now)


@app.route("/api/update-status")
def api_update_status():
    """检查昨日日报、最近完成日报和历史连续性。"""
    return jsonify(get_report_update_status())


@app.route("/api/update-check", methods=["POST"])
def api_update_check():
    """必要时非阻塞启动一期待补日报，不触发数据采集。"""
    return jsonify(start_report_finalization_if_needed())


@app.route("/api/instance")
def api_instance():
    """供本机启动器确认端口对应的是主源码实例。"""
    return jsonify({
        "project_id": INSTANCE_ID,
        "edition": "source",
        "today": project_today().isoformat(),
    })


# ------------------------------------------------------------------
# 自动补录缺失日报（后台线程，不阻塞首页加载）
# ------------------------------------------------------------------
def find_missing_dates():
    """找出最早日报到昨天之间缺失的日期。返回 list[str]"""
    all_dates = list_issues()
    if not all_dates:
        return []

    # earliest → yesterday（今天由正常流程处理）
    earliest = min(all_dates)
    yesterday = (project_today() - timedelta(days=1)).isoformat()
    if earliest >= yesterday:
        return []

    existing = set(all_dates)
    missing = []
    d = date.fromisoformat(earliest)
    end = date.fromisoformat(yesterday)
    while d <= end:
        ds = d.isoformat()
        if ds not in existing:
            missing.append(ds)
        d += timedelta(days=1)

    return missing


def _try_generate_for_date(target_date):
    """仅使用已存在的目标日期信息池补录日报，不伪造历史采集。"""
    log = _get_catchup_logger()
    try:
        sys.path.insert(0, str(BASE_DIR / "src"))
        from generate_daily import finalize_report

        log.info("补录 %s: 结算目标日期信息池...", target_date)
        generated = finalize_report(target_date)
        report_path = DAILY_DIR / f"{target_date}.md"
        return generated or report_path.exists()
    except Exception as exc:
        log.warning("补录 %s: 失败: %s", target_date, str(exc)[:200])
        return False


def _set_today_update_status(target_date, state, error=""):
    """记录当天更新状态，供首页显示并用于防止重复启动。"""
    status = {
        "state": state,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "error": error[:200] if error else "",
    }
    with _daily_update_lock:
        _daily_update_status[target_date] = status
    return status


def _get_today_update_status(target_date):
    """读取当天更新状态，返回副本避免模板或调用方修改共享状态。"""
    with _daily_update_lock:
        status = _daily_update_status.get(target_date)
        return dict(status) if status else None


def _run_today_update(target_date):
    """后台执行当天采集和日报生成，不影响首页请求。"""
    try:
        success = _try_generate_for_date(target_date)
        report_path = DAILY_DIR / f"{target_date}.md"
        if success and report_path.exists():
            _set_today_update_status(target_date, "success")
        else:
            _set_today_update_status(target_date, "failed", "采集或日报生成未完成")
    except Exception as exc:
        _set_today_update_status(target_date, "failed", str(exc))


def start_today_update_if_needed(target_date=None):
    """返回今日实时池状态；今天绝不被视为已完成日报。"""
    if target_date is None:
        target_date = project_today().isoformat()

    with _daily_update_lock:
        _daily_update_status[target_date] = {
            "state": "collecting" if load_realtime_info(target_date) else "scheduled",
            "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
            "error": "今日实时信息持续采集中，明日 00:05 生成最终日报",
        }
    return _get_today_update_status(target_date)


def auto_catchup():
    """后台自动补录缺失日报（线程入口）。"""
    log = _get_catchup_logger()
    missing = find_missing_dates()
    if not missing:
        log.info("补录检查: 无缺失日期，跳过")
        return

    log.info("补录检查: 发现 %d 个缺失日期: %s", len(missing), ", ".join(missing))
    success, fail = 0, 0
    for ds in sorted(missing):
        try:
            if _try_generate_for_date(ds):
                success += 1
            else:
                fail += 1
        except Exception as e:
            log.error("补录 %s: 未预期错误: %s", ds, traceback.format_exc()[:500])
            fail += 1

    log.info("补录完成: %d 成功, %d 失败", success, fail)


_catchup_started = False


def start_catchup_thread():
    """启动补录后台线程（仅一次）。"""
    global _catchup_started
    if _catchup_started:
        return
    _catchup_started = True
    t = threading.Thread(target=auto_catchup, daemon=True, name="catchup")
    t.start()


# ------------------------------------------------------------------
# 启动
# ------------------------------------------------------------------
def find_free_port(start=8899, tries=20):
    """从 8899 开始找一个可用端口（避开路由器 8787）"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


if __name__ == "__main__":
    preferred_port = int(os.environ.get("AI_RADAR_PORT", "8899"))
    strict_port = os.environ.get("AI_RADAR_STRICT_PORT") == "1"
    port = preferred_port if strict_port else find_free_port(preferred_port)
    print(f"📡 AI信息雷达已启动: http://127.0.0.1:{port}")
    print(f"   日报目录: {DAILY_DIR}")
    # 采集与日报结算由 Windows 计划任务执行；首页只读取已有结果，不触发 AI。
    # PyInstaller 打包版：双击 exe 后自动打开浏览器
    if getattr(sys, "frozen", False):
        import webbrowser as _webbrowser
        threading.Timer(1.5, lambda: _webbrowser.open(f"http://127.0.0.1:{port}")).start()
    # 绑定 0.0.0.0：无论系统代理如何配置都能访问
    # 127.0.0.1 / localhost / 本机IP 三种方式均可打开
    app.run(host="0.0.0.0", port=port, debug=False)
