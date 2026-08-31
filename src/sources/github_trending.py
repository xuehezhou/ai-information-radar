# -*- coding: utf-8 -*-
"""GitHub Trending AI/ML 仓库信源适配器"""

import re
import html
from .base import BaseSource, NewsItem, fetch_url


class GitHubTrendingSource(BaseSource):
    name = "GitHub"
    source_type = "community"

    def fetch(self, max_items: int = 15) -> list:
        items = []
        seen = set()

        urls = [
            "https://github.com/trending?since=daily",
            "https://github.com/trending/python?since=daily",
        ]

        for base_url in urls:
            try:
                html_text = fetch_url(base_url, timeout=15).decode("utf-8", "ignore")
            except Exception as e:
                print(f"  [GitHub] {base_url} 抓取失败: {e}")
                continue

            repos = re.findall(
                r'<article class="Box-row"[^>]*>(.*?)</article>',
                html_text, re.S
            )
            for repo_html in repos[:15]:
                name_m = re.search(r'<h2[^>]*>.*?<a[^>]*>([^<]+)</a>', repo_html, re.S)
                if not name_m:
                    continue
                full_name = re.sub(r'\s+', '', name_m.group(1).strip())

                if full_name in seen:
                    continue
                seen.add(full_name)

                desc_m = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', repo_html, re.S)
                desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()[:200] if desc_m else ""

                lang_m = re.search(r'itemprop="programmingLanguage"[^>]*>([^<]+)<', repo_html)
                lang = lang_m.group(1).strip() if lang_m else ""

                stars = 0
                star_m = re.search(r'(\d[\d,]*)\s*stars?', repo_html, re.S | re.I)
                if star_m:
                    stars = int(star_m.group(1).replace(",", ""))

                owner, _, repo_name = full_name.partition("/")
                link = f"https://github.com/{owner}/{repo_name}"

                combined = f"{full_name} {desc} {lang}".lower()
                ai_kw = ["ai", "llm", "agent", "gpt", "claude", "chatgpt", "deepseek",
                         "rag", "langchain", "transformer", "diffusion", "embedding",
                         "vector", "inference", "fine-tun", "lora", "quantiz",
                         "neural", "nlp", "vision", "generative", "prompt",
                         "chatbot", "copilot", "codex", "tool call", "mcp"]
                if not any(kw in combined for kw in ai_kw):
                    continue

                items.append(NewsItem(
                    title=f"{full_name}：{desc}" if desc else full_name,
                    source=self.name,
                    source_type=self.source_type,
                    timestamp="",
                    link=link,
                    summary=desc,
                    points=stars,
                    tags=["GitHub", "trending", lang.lower() if lang else "unknown"],
                ))

        items.sort(key=lambda x: -x.points)
        return items[:max_items]
