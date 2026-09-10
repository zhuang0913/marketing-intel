"""
scrapers/base.py — 自定义爬虫基类
提供 UA、超时、重试、HTML 解析、时间解析等通用能力。
所有具体站点爬虫继承 BaseScraper，实现 fetch() 返回标准化 Item 列表。
"""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# ---------- 标准化条目 ----------
@dataclass
class Item:
    """一个抓回来的文章条目，与 RSS Item 字段保持一致，方便统一处理。"""
    title: str
    url: str
    source: str                       # 来源名（用于 Notion）
    published: Optional[datetime] = None
    summary: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)


# ---------- 工具函数 ----------
_USER_AGENTS = [
    # 桌面端主流 UA，随机切换以减少被风控的概率
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


def parse_date(text: str, today: Optional[datetime] = None) -> Optional[datetime]:
    """
    把各种乱七八糟的中文日期串解析成 datetime。支持：
      - 2026-09-09 / 2026/09/09 / 2026.09.09
      - 2026年9月9日 / 2026-9-9
      - 9月9日 17:02（自动补当年）
      - 昨天 17:02 / 前天 18:19（相对今天）
      - N小时前 / N分钟前
    解析失败返回 None。
    """
    if not text:
        return None
    s = text.strip()
    now = today or datetime.now()
    s = re.sub(r"\s+", " ", s)

    # 相对时间：昨天 / 前天 / 今天
    if "昨天" in s:
        m = re.search(r"(\d{1,2}):(\d{1,2})", s)
        base = now - timedelta(days=1)
        if m:
            return base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return base.replace(hour=0, minute=0, second=0, microsecond=0)
    if "前天" in s:
        m = re.search(r"(\d{1,2}):(\d{1,2})", s)
        base = now - timedelta(days=2)
        if m:
            return base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return base.replace(hour=0, minute=0, second=0, microsecond=0)
    if "今天" in s:
        m = re.search(r"(\d{1,2}):(\d{1,2})", s)
        if m:
            return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)

    # N小时前 / N分钟前
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    # 完整日期：先尝试带时分
    patterns_with_time = [
        r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{1,2})",
    ]
    for p in patterns_with_time:
        m = re.search(p, s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                int(m.group(4)), int(m.group(5)))
            except ValueError:
                pass

    # 纯日期
    patterns = [
        r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                0, 0, 0)
            except ValueError:
                pass

    # 简写日期如 9月9日（默认当年）
    m = re.search(r"(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{1,2}))?", s)
    if m:
        try:
            hour = int(m.group(3)) if m.group(3) else 0
            minute = int(m.group(4)) if m.group(4) else 0
            return datetime(now.year, int(m.group(1)), int(m.group(2)), hour, minute)
        except ValueError:
            pass

    return None


def clean_text(text: str, max_len: int = 300) -> str:
    """去空白、压缩换行，截断到 max_len。"""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    return t[:max_len]


def normalize_url(url: str, base: str) -> str:
    """把 /article/123 这种相对路径补全成绝对 URL。"""
    from urllib.parse import urljoin
    return urljoin(base, url)


# ---------- 基类 ----------
class BaseScraper(ABC):
    """所有自定义站点爬虫继承此类。"""

    # 子类必须设置
    name: str = ""                # 来源名，写入 Notion 的「来源」字段
    list_urls: List[str] = []     # 要抓的列表页 URL 列表

    # 子类可覆盖
    request_timeout: int = 20
    max_retries: int = 3
    retry_backoff: float = 2.0    # 失败后等待秒数

    def __init__(self, name: str = "", list_urls: Optional[List[str]] = None):
        if name:
            self.name = name
        if list_urls:
            self.list_urls = list_urls
        if not self.name:
            raise ValueError(f"{type(self).__name__} 必须设置 name")
        if not self.list_urls:
            raise ValueError(f"{self.name} 必须设置至少一个 list_urls")

    # ---- 抓取 + 重试 ----
    def _get(self, url: str) -> Optional[BeautifulSoup]:
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {
                    "User-Agent": random.choice(_USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
                r = requests.get(url, headers=headers, timeout=self.request_timeout)
                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                return BeautifulSoup(r.text, "html.parser")
            except Exception as e:
                last_err = e
                wait = self.retry_backoff * attempt
                log.warning(f"[{self.name}] GET {url} 第{attempt}次失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
        log.error(f"[{self.name}] GET {url} 全部重试失败: {last_err}")
        return None

    # ---- 主入口 ----
    def fetch(self) -> List[Item]:
        items: List[Item] = []
        seen_urls = set()
        for url in self.list_urls:
            soup = self._get(url)
            if soup is None:
                continue
            try:
                page_items = self.parse(soup, url)
            except Exception as e:
                log.error(f"[{self.name}] parse 失败 {url}: {e}")
                continue
            for it in page_items:
                # 去重
                if it.url in seen_urls:
                    continue
                seen_urls.add(it.url)
                if it.source != self.name:
                    it.source = self.name
                items.append(it)
        return items

    # ---- 子类实现 ----
    @abstractmethod
    def parse(self, soup: BeautifulSoup, page_url: str) -> Iterable[Item]:
        """从单页解析出 Item 列表。"""
        raise NotImplementedError