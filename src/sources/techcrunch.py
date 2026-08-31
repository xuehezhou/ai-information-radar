# -*- coding: utf-8 -*-
"""TechCrunch AI 频道 RSS 信源适配器"""

import re
import html
from .base import BaseSource, NewsItem, fetch_url

FEED_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"


class TechCrunchSource(BaseSource):
    name = "TechCrunch"
    source_type = "rss"

    def fetch(self, max_items: int = 12) -> list:
        try:
            data = fetch_url(FEED_URL, timeout=20).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [TechCrunch] 抓取失败: {e}")
            return []

        items = []
        for block in re.findall(r"<item>(.*?)</item>", data, re.S)[:max_items]:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            d = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
            l = re.search(r"<link>(.*?)</link>", block)
            p = re.search(r"<pubDate>(.*?)</pubDate>", block)
            title = html.unescape(t.group(1).strip()) if t else ""
            desc = html.unescape(re.sub(r"<[^>]+>", " ", d.group(1))).strip()[:200] if d else ""
            link = l.group(1).strip() if l else ""
            pubdate = self._parse_date(p.group(1).strip()) if p else ""

            items.append(NewsItem(
                title=title,
                source=self.name,
                source_type=self.source_type,
                timestamp=pubdate,
                link=link,
                summary=desc,
                tags=["media", "tech"],
            ))
        return items

    @staticmethod
    def _parse_date(rfc2822: str) -> str:
        """将 RFC 2822 日期转为 ISO 格式"""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(rfc2822)
            return dt.isoformat()
        except Exception:
            return rfc2822[:25]
