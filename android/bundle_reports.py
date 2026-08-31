# -*- coding: utf-8 -*-
"""把 data/daily 下的日报打包成 APK assets：
  - assets/index.json                日报列表（日期/一句话总结/统计/上一篇下一篇）
  - assets/reports/<date>.html       每期日报自包含页面（内联 CSS + 导航）

在 build.bat 打包前自动运行。产出与 Flask /api/reports 结构一致，
手机 App 离线读 assets，联网时用 /api/reports 同步更新。
"""
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]         # ai-radar 根目录
ANDROID_DIR = Path(__file__).resolve().parent
ASSETS = ANDROID_DIR / "assets"
REPORTS_DIR = ASSETS / "reports"
DAILY_DIR = ROOT / "data" / "daily"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 复用 app.py 的解析/渲染逻辑，保证与网页版完全一致
sys.path.insert(0, str(ROOT / "src"))
from app import parse_summary, parse_stats, render_markdown  # noqa: E402


def make_page(date_str, content_html, newer, older):
    """组装一页自包含 HTML（内联 CSS，可离线打开）。"""
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    nav_prev = f'<a href="airiradar://daily/{newer}">‹ {newer}</a>' if newer else "<a></a>"
    nav_next = f'<a href="airiradar://daily/{older}">{older} ›</a>' if older else "<a></a>"
    return (
        '<!DOCTYPE html>\n<html lang="zh"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=3">\n'
        f"<title>AI信息雷达 · {date_str}</title>\n"
        "<style>" + css + "</style></head>\n<body>\n"
        '<header class="app-head"><span class="app-title">📡 AI信息雷达</span>'
        f'<span class="app-date">{date_str}</span></header>\n'
        f'<article class="daily-content">\n{content_html}\n</article>\n'
        f'<nav class="reader-nav">{nav_prev}{nav_next}</nav>\n'
        '<footer class="app-foot">AI信息雷达 · 每日AI行业资讯</footer>\n'
        "</body></html>\n"
    )


def main():
    dates = sorted(
        (p.stem for p in DAILY_DIR.glob("*.md") if DATE_RE.match(p.stem)),
        reverse=True,
    )
    if not dates:
        print("!! data/daily 下没有日报，跳过打包")
        return 1

    reports = []
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(dates):
        md = (DAILY_DIR / f"{d}.md").read_text(encoding="utf-8")
        newer = dates[i - 1] if i > 0 else None             # 更晚一期
        older = dates[i + 1] if i < len(dates) - 1 else None  # 更早一期
        page = make_page(d, render_markdown(md), newer, older)
        (REPORTS_DIR / f"{d}.html").write_text(page, encoding="utf-8")
        reports.append({
            "date": d,
            "summary": parse_summary(md),
            "stats": parse_stats(md),
            "newer": newer,
            "older": older,
        })
        print(f"  ok {d}  ({len(page) // 1024} KB)")

    (ASSETS / "index.json").write_text(
        json.dumps({"reports": reports}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"packed {len(dates)} reports -> assets/reports/ + assets/index.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
