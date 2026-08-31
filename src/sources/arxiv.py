# -*- coding: utf-8 -*-
"""arXiv cs.AI / cs.CL RSS 信源适配器"""

import re
import html
from datetime import datetime, timezone, timedelta
from .base import BaseSource, NewsItem, fetch_url

FEEDS = [
    ("cs.AI", "https://export.arxiv.org/rss/cs.AI"),
    ("cs.CL", "https://export.arxiv.org/rss/cs.CL"),
    ("cs.LG", "https://export.arxiv.org/rss/cs.LG"),
]


class ArxivSource(BaseSource):
    name = "arXiv"
    source_type = "academic"

    def fetch(self, max_items: int = 15) -> list:
        items = []
        seen = set()

        for cat, url in FEEDS:
            try:
                data = fetch_url(url, timeout=20).decode("utf-8", "ignore")
            except Exception as e:
                print(f"  [arXiv] {cat} 抓取失败: {e}")
                continue

            for block in re.findall(r"<item>(.*?)</item>", data, re.S):
                t = re.search(r"<title>(.*?)</title>", block, re.S)
                d = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
                l = re.search(r"<link>(.*?)</link>", block)
                p = re.search(r"<pubDate>(.*?)</pubDate>", block)

                title = html.unescape(t.group(1).strip()) if t else ""
                title = re.sub(r"^\[?\d{4}\.\d{4,6}v?\d*\]?\s*", "", title)
                title = re.sub(r"^cs\.\w+:\s*", "", title)

                summary = html.unescape(re.sub(r"<[^>]+>", " ", d.group(1))).strip()[:200] if d else ""
                link = l.group(1).strip() if l else ""
                pubdate = p.group(1).strip() if p else ""
                arxiv_id = link.split("/abs/")[-1] if "/abs/" in link else ""

                if arxiv_id in seen:
                    continue
                seen.add(arxiv_id)

                # AI 关键词过滤
                title_lower = title.lower()
                keywords = ["llm", "agent", "gpt", "claude", "deepseek", "qwen",
                            "rag", "reasoning", "alignment", "multimodal",
                            "rlhf", "instruct", "chat", "transformer", "diffusion",
                            "generation", "embedding", "vector", "tool", "function call",
                            "code", "benchmark", "safety", "guard", "jailbreak",
                            "fine-tun", "lora", "quantiz", "inference"]
                if not any(kw in title_lower for kw in keywords):
                    continue

                items.append(NewsItem(
                    title=title,
                    source=self.name,
                    source_type=self.source_type,
                    timestamp=pubdate,
                    link=link,
                    summary=summary,
                    tags=["paper", cat, "research"],
                ))

        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items[:max_items]
