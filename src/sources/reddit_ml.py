# -*- coding: utf-8 -*-
"""Reddit r/MachineLearning + r/artificial 信源适配器"""

import json
import time
from .base import BaseSource, NewsItem, fetch_url

SUBREDDITS = [
    ("MachineLearning", "research"),
    ("artificial", "community"),
    ("LocalLLaMA", "community"),
]


class RedditMLSource(BaseSource):
    name = "Reddit"
    source_type = "community"

    def fetch(self, max_items: int = 30) -> list:
        all_items = []
        seen = set()

        for sub, flavor in SUBREDDITS:
            try:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                data = fetch_url(url, timeout=15).decode("utf-8")
                posts = json.loads(data).get("data", {}).get("children", [])

                for p in posts:
                    d = p["data"]
                    pid = d.get("id")
                    if pid in seen or d.get("stickied"):
                        continue
                    seen.add(pid)

                    created = d.get("created_utc", 0)
                    if time.time() - created > 86400:
                        continue

                    score = d.get("score", 0)
                    if score < 5:
                        continue

                    title = d.get("title", "")
                    selftext = (d.get("selftext") or "")[:200]
                    link = f"https://www.reddit.com{d.get('permalink', '')}"
                    if d.get("url") and not d.get("is_self"):
                        link = d.get("url", link)

                    all_items.append(NewsItem(
                        title=title,
                        source=self.name,
                        source_type=self.source_type,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(created)),
                        link=link,
                        summary=selftext if selftext else "",
                        points=score,
                        comments=d.get("num_comments", 0),
                        tags=["Reddit", f"r/{sub}", flavor],
                    ))
            except Exception as e:
                print(f"  [Reddit] r/{sub} 抓取失败: {e}")

        all_items.sort(key=lambda x: -x.points)
        return all_items[:max_items]
