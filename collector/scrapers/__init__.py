"""scrapers 包：所有具体站点爬虫。注册到 fetch_rss.py 的 _build_scrapers()。"""
from .base import BaseScraper, Item  # noqa: F401
from .shuying import ShuYingScraper     # noqa: F401
from .socialbeta import SocialBetaScraper  # noqa: F401
from .adaomou import AdQuanScraper      # noqa: F401