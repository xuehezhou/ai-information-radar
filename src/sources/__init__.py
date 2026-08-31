# -*- coding: utf-8 -*-
"""信源适配器包

每个模块导出对应信源的采集器类，统一继承 BaseSource。
"""

from .base import BaseSource, NewsItem
from .hackernews import HackerNewsSource
from .techcrunch import TechCrunchSource
from .venturebeat import VentureBeatSource
from .reddit_ml import RedditMLSource
from .arxiv import ArxivSource
from .github_trending import GitHubTrendingSource
from .producthunt import ProductHuntSource
from .qwen_blog import QwenBlogSource, DeepSeekUpdatesSource

__all__ = [
    "BaseSource", "NewsItem",
    "HackerNewsSource",
    "TechCrunchSource",
    "VentureBeatSource",
    "RedditMLSource",
    "ArxivSource",
    "GitHubTrendingSource",
    "ProductHuntSource",
    "QwenBlogSource",
    "DeepSeekUpdatesSource",
]
