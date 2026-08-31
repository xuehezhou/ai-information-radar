# -*- coding: utf-8 -*-
"""VentureBeat AI 频道 RSS 信源适配器"""

import re
import html
from .base import BaseSource, NewsItem, fetch_url

FEED_URL = "https://venturebeat.com/category/ai/feed/"


class VentureBeatSource(BaseSource):
    name = "VentureBeat"
    source_type = "rss"

    def fetch(self, max_items: int = 12) -> list:
        try:
            data = fetch_url(FEED_URL, timeout=20).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [VentureBeat] 抓取失败: {e}")
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
            pubdate = p.group(1).strip() if p else ""

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
