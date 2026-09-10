"""
scrapers/socialbeta.py — SocialBeta（socialbeta.com）爬虫

真实结构（首页）：
  <a href="/campaign/{id}" target="_blank">文章标题</a>
  <a class="tit" href="/article/{id}">长文标题</a>

SocialBeta 的列表页结构非常轻量：每个文章就是一个独立的 a 标签，
里面只有标题文字。摘要/日期/品牌标签只能在文章详情页拿到。

策略：抓所有 /campaign/{id} 和 /article/{id} 链接，
取 a 内的文字作为标题。
日期拿不到时回退到今天（采集脚本的 entry_date 会处理）。
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List

from bs4 import BeautifulSoup

from .base import BaseScraper, Item, clean_text, normalize_url

log = logging.getLogger(__name__)


class SocialBetaScraper(BaseScraper):
    """SocialBeta 首页爬虫。"""

    def __init__(self, name: str = "SocialBeta"):
        super().__init__(
            name=name,
            list_urls=[
                "https://socialbeta.com/",
            ],
        )

    def parse(self, soup: BeautifulSoup, page_url: str) -> Iterable[Item]:
        items: List[Item] = []
        seen_in_page = set()

        # 找所有指向 /campaign/{id} 或 /article/{id} 的 a 标签
        anchors = []
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if re.search(r"/(campaign|article)/\d+", href):
                anchors.append(a)

        for a in anchors:
            href = a.get("href", "")
            url = normalize_url(href, page_url)
            if url in seen_in_page:
                continue

            # 标题：a 的纯文本
            title_text = clean_text(a.get_text(), max_len=120)
            if not title_text or len(title_text) < 4:
                continue

            # 排除纯时间/纯徽章文本（防御）
            if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}(\s+\d{1,2}:\d{2})?", title_text):
                continue
            if re.fullmatch(r"(昨天|前天|今天)\s*\d{1,2}:\d{2}", title_text):
                continue

            seen_in_page.add(url)
            items.append(Item(
                title=title_text,
                url=url,
                source=self.name,
                published=None,        # 列表页拿不到日期，留给 fetch_rss 的 fallback
                summary="",            # 列表页无摘要
            ))

        log.info(f"[{self.name}] {page_url} 解析到 {len(items)} 条")
        return items