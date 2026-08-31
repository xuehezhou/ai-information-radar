# -*- coding: utf-8 -*-
"""信源适配器基类"""

import ssl
import urllib.request
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, asdict
from typing import Optional

# ------------------------------------------------------------------
# 全局 URL 抓取工具（自动尝试代理→直连→SSL宽松）
# ------------------------------------------------------------------
PROXY_URL = "http://127.0.0.1:10090"  # 系统代理地址
DEFAULT_HEADERS = {"User-Agent": "ai-radar/1.0"}


def _build_openers():
    """构建多个 opener（代理 / 直连 / SSL宽松），按优先级排列"""
    openers = []

    # 1. 代理模式
    proxy = urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL})
    openers.append(("proxy", urllib.request.build_opener(proxy)))

    # 2. 直连 + 宽松 SSL（显式禁用系统代理）
    no_proxy = urllib.request.ProxyHandler({})
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
    openers.append((
        "direct-nossl",
        urllib.request.build_opener(no_proxy, https_handler),
    ))

    # 3. 纯直连（不继承 Windows / 环境代理）
    openers.append((
        "direct",
        urllib.request.build_opener(urllib.request.ProxyHandler({})),
    ))

    return openers


_OPENERS = _build_openers()
_REQUEST_HEALTH = ContextVar("ai_radar_source_request_health", default=None)


@contextmanager
def source_request_health(source_name: str):
    """为单个并发信源隔离记录网络请求结果。"""
    health = {
        "source": source_name,
        "requests": 0,
        "failed_requests": 0,
        "errors": [],
    }
    token = _REQUEST_HEALTH.set(health)
    try:
        yield health
    finally:
        _REQUEST_HEALTH.reset(token)


def fetch_url(url: str, timeout: int = 20) -> bytes:
    """抓取 URL 内容，自动尝试多种连接方式。

    优先级：代理 → 直连(SSL宽松) → 直连
    返回 bytes 内容，失败抛出最后一个异常。
    """
    last_error = None
    health = _REQUEST_HEALTH.get()
    if health is not None:
        health["requests"] += 1

    for name, opener in _OPENERS:
        # ProxyHandler may mutate a Request via set_proxy(). Give each
        # fallback a fresh request so a failed proxy cannot pollute direct mode.
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        try:
            return opener.open(req, timeout=timeout).read()
        except Exception as e:
            last_error = e
            continue  # 尝试下一种方式

    if health is not None:
        health["failed_requests"] += 1
        error_text = f"{type(last_error).__name__}: {last_error}"[:200]
        if error_text not in health["errors"]:
            health["errors"].append(error_text)
    raise last_error


@dataclass
class NewsItem:
    """统一的数据结构 —— 所有信源适配器输出此格式"""
    title: str
    source: str                    # 信源名称：HackerNews / Reddit / arXiv ...
    source_type: str               # 信源类型：community / rss / academic / official
    timestamp: str                 # ISO 格式时间戳
    link: str                      # 原始链接
    summary: str = ""              # 摘要（≤200字）
    category: str = ""             # 待分类，采集后由分类器填充
    importance: str = ""           # 待评分，采集后由评分器填充
    impact_analysis: str = ""      # 待填充，仅 A 级事件需要
    tags: list = field(default_factory=list)
    points: int = 0                # 热度指标（HN points / Reddit upvotes / GitHub stars）
    comments: int = 0              # 评论数
    collected_at: str = ""         # 采集时间
    duplicate_of: Optional[str] = None  # 重复标记

    def to_dict(self) -> dict:
        data = asdict(self)
        # timestamp 为兼容旧数据保留；published_at 是明确的数据实际发布时间。
        data["published_at"] = self.timestamp
        return data

    @property
    def id(self) -> str:
        """基于 title+link 的稳定 ID（用于去重）"""
        import hashlib
        raw = f"{self.title}|{self.link}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()


class BaseSource(ABC):
    """信源适配器抽象基类

    每个信源实现 fetch() 方法，返回 NewsItem 列表。
    """

    name: str = "base"
    source_type: str = "unknown"

    @abstractmethod
    def fetch(self, max_items: int = 25) -> list:
        """抓取数据，返回 NewsItem 列表"""
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"
