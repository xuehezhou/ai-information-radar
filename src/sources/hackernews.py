# -*- coding: utf-8 -*-
"""Hacker News Algolia API 信源适配器"""

import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

from .base import BaseSource, NewsItem, fetch_url


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
QUERIES = ["AI", "LLM", "model", "agent", "Claude", "GPT", "Gemini", "DeepSeek", "Qwen"]


class HackerNewsSource(BaseSource):
    name = "HackerNews"
    source_type = "community"

    def fetch(self, max_items: int = 25) -> list:
        since = int(time.time()) - 2 * 86400  # 近2天
        return self._fetch_range(f"created_at_i>{since},points>10", max_items)

    def fetch_for_date(self, target_date: str, max_items: int = 60) -> list:
        """按上海自然日精确回溯历史资讯。"""
        target = date.fromisoformat(target_date)
        local_start = datetime.combine(target, datetime_time.min, tzinfo=LOCAL_TZ)
        local_end = local_start + timedelta(days=1)
        start_epoch = int(local_start.astimezone(timezone.utc).timestamp())
        end_epoch = int(local_end.astimezone(timezone.utc).timestamp())
        filters = (
            f"created_at_i>={start_epoch},created_at_i<{end_epoch},points>10"
        )
        return self._fetch_range(filters, max_items)

    def _fetch_range(self, numeric_filters: str, max_items: int) -> list:
        seen, items = set(), []

        for query in QUERIES:
            params = urllib.parse.urlencode({
                "query": query,
                "tags": "story",
                "numericFilters": numeric_filters,
                "hitsPerPage": 100,
            })
            url = f"https://hn.algolia.com/api/v1/search_by_date?{params}"
            try:
                data = json.loads(fetch_url(url, timeout=20).decode("utf-8"))
                for h in data.get("hits", []):
                    oid = h.get("objectID")
                    if oid in seen:
                        continue
                    seen.add(oid)
                    items.append(NewsItem(
                        title=h.get("title") or "",
                        source=self.name,
                        source_type=self.source_type,
                        timestamp=h.get("created_at") or "",
                        link=h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                        summary="",
                        points=h.get("points") or 0,
                        comments=h.get("num_comments") or 0,
                        tags=["HN", "community"],
                    ))
            except Exception as e:
                print(f"  [HN] 查询 '{query}' 失败: {e}")

        items.sort(key=lambda x: -x.points)
        return items[:max_items]
