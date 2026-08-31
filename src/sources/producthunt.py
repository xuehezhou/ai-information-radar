# -*- coding: utf-8 -*-
"""ProductHunt AI 分类信源适配器"""

import re
import html
from .base import BaseSource, NewsItem, fetch_url


class ProductHuntSource(BaseSource):
    name = "ProductHunt"
    source_type = "community"

    def fetch(self, max_items: int = 15) -> list:
        items = []

        # 方案1：RSS feed（最稳定）
        rss_items = self._fetch_rss(max_items)
        if rss_items:
            return rss_items

        # 方案2：HTML 页面解析（降级）
        return self._fetch_html(max_items)

    def _fetch_rss(self, max_items: int = 10) -> list:
        """RSS feed 抓取"""
        rss_urls = [
            "https://www.producthunt.com/feed?format=rss",
            "https://www.producthunt.com/feed/topics/artificial-intelligence.rss",
        ]
        all_items = []

        for url in rss_urls:
            try:
                data = fetch_url(url, timeout=15).decode("utf-8", "ignore")
            except Exception as e:
                print(f"  [ProductHunt] RSS {url[-30:]} 抓取失败: {e}")
                continue

            # ProductHunt RSS 中的条目格式
            for block in re.findall(r"<item>(.*?)</item>", data, re.S)[:max_items]:
                t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
                d = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
                l = re.search(r"<link>(.*?)</link>", block)

                title = html.unescape(t.group(1).strip()) if t else ""
                desc = html.unescape(re.sub(r"<[^>]+>", " ", d.group(1))).strip()[:200] if d else ""
                link = l.group(1).strip() if l else ""

                # ProductHunt RSS 包含所有产品，手动过滤 AI 相关
                title_lower = title.lower()
                ai_kw = ["ai", "llm", "agent", "gpt", "claude", "chatgpt", "copilot",
                         "prompt", "machine learning", "deep learning", "generative",
                         "automation", "workflow", "no-code ai", "developer tool",
                         "code assistant", "data analysis", "nlp"]
                if not any(kw in title_lower for kw in ai_kw):
                    continue

                all_items.append(NewsItem(
                    title=title,
                    source=self.name,
                    source_type=self.source_type,
                    timestamp="",
                    link=link,
                    summary=desc,
                    points=10,
                    tags=["ProductHunt", "product", "AI"],
                ))

        return all_items

    def _fetch_html(self, max_items: int = 10) -> list:
        """HTML 页面解析（降级方案）"""
        items = []
        seen = set()

        for url in [
            "https://www.producthunt.com/feed?category=ai",
            "https://www.producthunt.com/feed?topic=artificial-intelligence",
        ]:
            try:
                html_text = fetch_url(url, timeout=15).decode("utf-8", "ignore")
            except Exception as e:
                print(f"  [ProductHunt] HTML 抓取失败: {e}")
                continue

            # 从 HTML 提取产品链接
            cards = re.findall(
                r'<a[^>]*href="(/posts/[^"]+)"[^>]*>(.*?)</a>',
                html_text, re.S
            )
            for link_path, card_html in cards[:max_items]:
                post_id = link_path.split("/")[-1].split("-")[0] if link_path else ""
                if post_id in seen:
                    continue
                seen.add(post_id)

                card_text = html.unescape(re.sub(r"<[^>]+>", " ", card_html)).strip()
                card_text = " ".join(card_text.split())
                if len(card_text) < 10:
                    continue

                product_name = card_text.split()[0] if card_text else ""
                desc = " ".join(card_text.split()[1:])[:200]

                items.append(NewsItem(
                    title=f"{product_name}：{desc}" if desc else product_name,
                    source=self.name,
                    source_type=self.source_type,
                    timestamp="",
                    link=f"https://www.producthunt.com{link_path}",
                    summary=f"ProductHunt AI 产品",
                    points=10,
                    tags=["ProductHunt", "product", "AI"],
                ))

            if seen:
                break

        return items
