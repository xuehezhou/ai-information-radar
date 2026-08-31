# -*- coding: utf-8 -*-
"""Qwen 官方博客 + DeepSeek 官方更新日志 信源适配器"""

import re
import html
from .base import BaseSource, NewsItem, fetch_url

QWEN_BLOG_URL = "https://qwen.ai/blog"
DEEPSEEK_UPDATES_URL = "https://api-docs.deepseek.com/updates/"


class QwenBlogSource(BaseSource):
    """Qwen 官方博客"""
    name = "QwenBlog"
    source_type = "official"

    def fetch(self, max_items: int = 8) -> list:
        items = []
        try:
            html_text = fetch_url(QWEN_BLOG_URL, timeout=15).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [Qwen] 博客抓取失败: {e}")
            return []

        # 从 HTML 中提取博客条目：找所有包含 blog?id= 的链接
        links = re.findall(
            r'<a[^>]*href="(/blog\?id=[^"]*)"[^>]*>(.*?)</a>',
            html_text, re.S
        )

        # 如果没找到 blog?id= 链接，尝试匹配任何包含 qwen 相关关键词的标题文本
        if not links:
            # 尝试从页面标题/描述提取
            titles = re.findall(
                r'<(?:h[1-4]|title)[^>]*>(.*?)</(?:h[1-4]|title)>',
                html_text, re.S
            )
            for t_html in titles:
                text = html.unescape(re.sub(r"<[^>]+>", " ", t_html)).strip()
                text = " ".join(text.split())
                if text and len(text) > 10:
                    items.append(NewsItem(
                        title=text[:200],
                        source=self.name,
                        source_type=self.source_type,
                        timestamp="",
                        link=QWEN_BLOG_URL,
                        summary=text[:200],
                        tags=["Qwen", "official", "model"],
                    ))
            return items[:max_items]

        seen = set()
        for link_path, card_html in links:
            if link_path in seen:
                continue
            seen.add(link_path)

            text = html.unescape(re.sub(r"<[^>]+>", " ", card_html)).strip()
            text = " ".join(text.split())
            if not text or len(text) < 5:
                continue

            items.append(NewsItem(
                title=text[:200],
                source=self.name,
                source_type=self.source_type,
                timestamp="",
                link=f"https://qwen.ai{link_path}",
                summary=text[:200],
                tags=["Qwen", "official", "model"],
            ))

        return items[:max_items]


class DeepSeekUpdatesSource(BaseSource):
    """DeepSeek 官方更新日志"""
    name = "DeepSeek"
    source_type = "official"

    def fetch(self, max_items: int = 5) -> list:
        items = []
        try:
            html_text = fetch_url(DEEPSEEK_UPDATES_URL, timeout=15).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [DeepSeek] 更新日志抓取失败: {e}")
            return []

        # 提取标题文本
        blocks = re.findall(
            r'<(?:h[2-4]|title|a[^>]*class="[^"]*title[^"]*")[^>]*>(.*?)</(?:h[2-4]|title|a)>',
            html_text, re.S
        )

        seen = set()
        for block_html in blocks:
            text = html.unescape(re.sub(r"<[^>]+>", " ", block_html)).strip()
            text = " ".join(text.split())
            if not text or len(text) < 10 or text in seen:
                continue
            seen.add(text)

            items.append(NewsItem(
                title=text[:200],
                source=self.name,
                source_type=self.source_type,
                timestamp="",
                link=DEEPSEEK_UPDATES_URL,
                summary=text[:200],
                tags=["DeepSeek", "official", "model"],
            ))

        return items[:max_items]
