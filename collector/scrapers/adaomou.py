"""
scrapers/adaomou.py — 广告门（adquan.com）爬虫

真实结构（首页混合三种）：
1. 顶部轮播图：
   <a href="/article/{id}" target="_blank">
     <img src="...">
     <div class="swiperDiv"><span>标题</span></div>
   </a>

2. 普通文章位（article_2_href）：
   <a class="article_2_href" href="/article/{id}" target="_blank">
     <p class="article_2_p">标题</p>
   </a>

3. 最新文章区：
   <a href="/article/{id}">
     <p class="desc">摘要</p>
     <h3 class="title">标题</h3>
     <span class="date">2026/09/09</span>
   </a>

策略：统一找所有 /article/{id} 链接，
按 a 内是否存在子结构（p/spans）智能识别：
  - 若 a 内含完整子结构（h3 + 日期），优先用结构化字段
  - 否则取 a 内最长非日期文本作为标题
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List

from bs4 import BeautifulSoup

from .base import BaseScraper, Item, clean_text, normalize_url, parse_date

log = logging.getLogger(__name__)


class AdQuanScraper(BaseScraper):
    """广告门首页爬虫。"""

    def __init__(self, name: str = "广告门"):
        super().__init__(
            name=name,
            list_urls=[
                "https://www.adquan.com/",
            ],
        )

    def parse(self, soup: BeautifulSoup, page_url: str) -> Iterable[Item]:
        items: List[Item] = []
        seen_in_page = set()

        for a in soup.find_all("a"):
            href = a.get("href", "")
            if not re.search(r"/article/\d+", href):
                continue
            url = normalize_url(href, page_url)
            if url in seen_in_page:
                continue

            # ---- 标题提取 ----
            title_text = ""
            # 优先 h3
            h3 = a.find("h3")
            if h3:
                title_text = clean_text(h3.get_text(), max_len=120)
            # 次选 p.article_2_p / p.desc / p 其他
            if not title_text:
                for p in a.find_all("p"):
                    ptxt = clean_text(p.get_text(), max_len=120)
                    if ptxt and not re.fullmatch(r"\d{4}[/.-]\d{1,2}[/.-]\d{1,2}", ptxt):
                        title_text = ptxt
                        break
            # 再次：span（轮播图 swiperDiv）
            if not title_text:
                span = a.find("span")
                if span:
                    title_text = clean_text(span.get_text(), max_len=120)
            # 最后兜底：整段文本，截断到第一个日期前
            if not title_text:
                full = clean_text(a.get_text(" "), max_len=120)
                # 去掉开头的日期
                full = re.sub(r"^\d{4}[/.-]\d{1,2}[/.-]\d{1,2}\s*", "", full)
                title_text = full

            if not title_text or len(title_text) < 4:
                continue

            # 防御：标题恰好是纯日期
            if re.fullmatch(r"\d{4}[/.-]\d{1,2}[/.-]\d{1,2}", title_text):
                continue

            seen_in_page.add(url)

            # ---- 摘要提取 ----
            summary = ""
            for p in a.find_all("p"):
                ptxt = clean_text(p.get_text(), max_len=300)
                if not ptxt:
                    continue
                if ptxt == title_text:
                    continue
                if re.fullmatch(r"\d{4}[/.-]\d{1,2}[/.-]\d{1,2}", ptxt):
                    continue
                summary = ptxt
                break

            # ---- 日期提取 ----
            pub_date = None
            # 优先级：<span class="date">YYYY/MM/DD</span> > <label>YYYY-MM-DD</label> > 文本匹配
            for tag in a.find_all(["span", "label"]):
                m = re.search(r"\d{4}[/.-]\d{1,2}[/.-]\d{1,2}", tag.get_text())
                if m:
                    pub_date = parse_date(m.group(0))
                    break
            if not pub_date:
                m = re.search(r"\d{4}[/.-]\d{1,2}[/.-]\d{1,2}", a.get_text(" "))
                if m:
                    pub_date = parse_date(m.group(0))

            items.append(Item(
                title=title_text,
                url=url,
                source=self.name,
                published=pub_date,
                summary=summary,
            ))

        log.info(f"[{self.name}] {page_url} 解析到 {len(items)} 条")
        return items