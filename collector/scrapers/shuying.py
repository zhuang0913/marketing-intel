"""
scrapers/shuying.py — 数英网（digitaling.com）爬虫

数英文章列表项的真实结构（首页）：
  <div class="f_l w_445">
    <h3><a href="/articles/{id}.html" title="标题">标题</a></h3>
    <p class="font_14 line_18 mg_b_15 color_666">摘要</p>
    <p class="h_line_30">
      <a><img title="作者名"/></a>
      <label>2026-09-09</label>
      <i>（互动数据）</i>
    </p>
  </div>

策略：找所有 h3 内的 /articles/{id}.html 链接，
然后回到祖父级 div 找摘要、日期、作者。
"""

import logging
import re
from typing import Iterable, List

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, Item, clean_text, normalize_url, parse_date

log = logging.getLogger(__name__)


class ShuYingScraper(BaseScraper):
    """数英网爬虫。"""

    def __init__(self, name: str = "数英网", max_pages: int = 2):
        urls = ["https://www.digitaling.com/articles"]
        for p in range(2, max_pages + 1):
            urls.append(f"https://www.digitaling.com/articles?page={p}")
        super().__init__(name=name, list_urls=urls)

    def parse(self, soup: BeautifulSoup, page_url: str) -> Iterable[Item]:
        items: List[Item] = []
        seen_in_page = set()

        # 找所有 h3 内的 /articles/{id}.html 链接
        for h3 in soup.find_all("h3"):
            a = h3.find("a", href=re.compile(r"/articles/\d+\.html"))
            if not a:
                continue
            href = a.get("href", "")
            url = normalize_url(href, page_url)
            if url in seen_in_page:
                continue
            seen_in_page.add(url)

            # 标题：a 内的文字
            title_text = clean_text(a.get_text(), max_len=120)
            if not title_text:
                title_text = clean_text(a.get("title", ""), max_len=120)
            if not title_text or len(title_text) < 4:
                continue

            # 祖父级 div：包含摘要、日期、作者
            container = h3.parent  # <div class="f_l w_445">
            if not container:
                continue

            # 摘要：第一个非空的 color_666 / line_18 / 描述类 p
            summary = ""
            for p in container.find_all("p"):
                ptxt = clean_text(p.get_text(" "), max_len=300)
                if ptxt and not re.search(r"\d{4}-\d{1,2}-\d{1,2}", ptxt):
                    summary = ptxt
                    break

            # 日期：<label>YYYY-MM-DD</label>
            pub_date = None
            for label in container.find_all("label"):
                m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", label.get_text())
                if m:
                    pub_date = parse_date(m.group(0))
                    break

            # 作者：找 img.title="作者"
            author = ""
            img = container.find("img", attrs={"title": True})
            if img:
                author = clean_text(img.get("title", ""), max_len=40)

            items.append(Item(
                title=title_text,
                url=url,
                source=self.name,
                published=pub_date,
                summary=summary,
                author=author,
            ))

        log.info(f"[{self.name}] {page_url} 解析到 {len(items)} 条")
        return items