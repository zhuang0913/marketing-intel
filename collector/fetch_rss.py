# -*- coding: utf-8 -*-
"""
营销情报采集脚本
------------------------------------------------------------
支持两种数据源：
  1. type: rss       原生 RSS / RSSHub 路由（feedparser 抓取）
  2. type: scraper   自定义 Python 爬虫（scrapers/*.py）

公众号源走 wewe-rss / feeddd 等第三方免费 RSS 服务，按 rss 类型配置即可。

流程：
  1. 读取 sources.yaml
  2. 按源类型分别抓取
  3. 按 URL 去重（跳过 Notion 中已存在的链接）
  4. 按关键词规则自动打标：行业 / 内容类型 / 营销框架
  5. 写入 Notion 数据库（页面级 create）

环境变量（GitHub Actions 中配置为 Secrets）：
  NOTION_TOKEN        Notion 集成密钥
  NOTION_DATABASE_ID  目标数据库 ID
  MAX_DAYS            (可选) 只采集最近 N 天的文章，默认 3
  MAX_PER_SOURCE      (可选) 每源最多写入条数，默认 5
"""
import os
import re
import sys
import html
import datetime
import json
import time

import feedparser
import requests
import yaml

# ================= 配置 =================
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
MAX_DAYS = int(os.environ.get("MAX_DAYS", "3"))
MAX_PER_SOURCE = int(os.environ.get("MAX_PER_SOURCE", "5"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(BASE_DIR, "sources.yaml")

# RSSHub 公共实例地址（运行时由 load_sources 覆盖，支持自建实例）
RSSHUB_BASE = "https://rsshub.app"

NOTION_API = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ================= 爬虫注册表 =================
# 把 scrapers/ 下的爬虫类显式注册，新增爬虫时只改一行。
# name -> (类, 可选参数)
def _build_scrapers():
    from scrapers.shuying import ShuYingScraper
    from scrapers.socialbeta import SocialBetaScraper
    from scrapers.adaomou import AdQuanScraper
    return {
        "shuying":     (ShuYingScraper, {}),
        "socialbeta":  (SocialBetaScraper, {}),
        "adaomou":     (AdQuanScraper, {}),
    }


# ================= 分类规则 =================
INDUSTRY_RULES = {
    "美妆个护": ["美妆", "护肤", "彩妆", "化妆品", "个护", "精华", "面霜", "防晒",
               "珀莱雅", "欧莱雅", "雅诗兰黛", "肤质", "成分党", "胶原蛋白", "敏感肌"],
    "食品饮料": ["食品", "饮料", "零食", "咖啡", "茶饮", "奶茶", "乳品", "奶粉",
               "三顿半", "元气森林", "农夫山泉", "预制菜", "烘焙", "糖果"],
    "服装时尚": ["服装", "时尚", "服饰", "穿搭", "运动鞋", " sneakers", "优衣库",
               "安踏", "李宁", "波司登", "奢侈品", "lululemon", "潮牌", "鞋服"],
    "母婴亲子": ["母婴", "育儿", "婴儿", "儿童", "孕产", "亲子", "辅食", "童装"],
    "3C数码": ["3C", "数码", "手机", "耳机", "智能硬件", "扫地机器人", "清洁家电",
             "无人机", "笔记本", "穿戴设备", "大疆", "小米", "华为"],
    "大健康": ["健康", "保健品", "养生", "医疗", "体检", "健身", "营养品",
             "银发", "老年", "中医药", "轻食"],
    "餐饮": ["餐饮", "餐厅", "外卖", "火锅", "茶咖", "麦当劳", "肯德基", "瑞幸",
           "星巴克", "海底捞", "堂食", "到店"],
    "家居日用": ["家居", "家清", "日用", "家电", "家具", "寝具", "收纳",
               "戴森", "宜家", "毛巾", "纸品"],
    "宠物经济": ["宠物", "猫粮", "狗粮", "猫砂", "养宠", "兽医", "宠物医院"],
    "酒水": ["白酒", "啤酒", "红酒", "低度酒", "果酒", "威士忌", "茅台",
           "酒类", "微醺", "精酿"],
}

TYPE_RULES = {
    "行业研报": ["报告", "白皮书", "洞察", "研究", "榜单", "数据解读", "趋势报告"],
    "平台洞察": ["平台", "算法", "流量", "新规", "政策", "招商", "玩法", "投流"],
    "电商知识": ["GMV", "直播带货", "大促", "双11", "618", "电商", "店铺",
              "转化率", "SKU", "货架", "跨境", "Temu", "即时零售"],
    "广告知识": ["广告", "营销案例", "联名", "campaign", "创意", "投放",
              "品牌片", "代言人", "种草", "campaign复盘", "营销活动"],
    "产品知识": ["产品经理", "需求分析", "用户体验", "UX", "功能设计",
              "产品拆解", "迭代", "MVP", "产品逻辑"],
    "商业趋势": ["商业模式", "出海", "增长", "估值", "融资", "IPO",
              "第二曲线", "护城河", "行业变局", "价格战"],
}

FRAMEWORK_RULES = {
    "产品创新": ["新品", "创新", "首发", "上新", "产品力", "定制化",
              "新规格", "迭代"],
    "消费者洞察": ["消费者", "人群", "Z世代", "人群画像", "消费习惯",
               "用户调研", "偏好", "心智占领"],
    "品牌定位": ["品牌定位", "高端化", "品牌升级", "品牌战略", "差异化",
              "品牌资产", "心智", "品牌焕新"],
    "内容营销": ["内容营销", "种草", "短视频", "直播", "KOL", "KOC",
              "UGC", "自媒体", "内容策略", "笔记"],
    "渠道运营": ["渠道", "分销", "线下门店", "电商渠道", "全渠道", "经销",
              "货架", "即时零售", "门店"],
    "私域运营": ["私域", "社群", "企业微信", "会员", "复购", "导购",
              "小程序", "SCRM"],
    "定价策略": ["定价", "价格带", "降价", "涨价", "促销", "折扣",
              "性价比", "价格战", "9.9"],
    "增长黑客": ["增长", "获客", "裂变", "转化", "AARRR", "A/B测试",
              "冷启动", "投放优化", "ROI"],
    "供应链": ["供应链", "选品", "库存", "周转", "履约", "物流",
             "自有品牌", "代工", "柔性供应链"],
    "ESG营销": ["ESG", "可持续", "环保", "碳中和", "公益营销", "社会责任"],
}


# ================= 工具函数 =================
def load_sources():
    """
    读取 sources.yaml。返回 List[Dict]，每条字段：
      - name: 来源名
      - category: 内容类型
      - type: 'rss' | 'scraper'
      - url: rss 源使用（原生 RSS 或 RSSHub 完整 URL）
      - rsshub: RSSHub 路径（仅路由源）
      - scraper: scraper 类型名（注册表 key）
      - original_url: 源站首页（运维排查用）
    """
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    base = (cfg.get("rsshub_base") or "https://rsshub.app").rstrip("/")
    global RSSHUB_BASE
    RSSHUB_BASE = base
    sources = []
    for s in cfg.get("sources", []):
        stype = s.get("type", "rss")
        common = {
            "name": s["name"],
            "category": s.get("category", "其他"),
            "original_url": s.get("original_url", ""),
        }
        if stype == "scraper":
            sources.append({
                **common,
                "type": "scraper",
                "scraper": s.get("scraper"),
                "params": s.get("params", {}),
            })
        else:  # rss
            rsshub = s.get("rsshub", "")
            url = s.get("url") or ((base + rsshub) if rsshub else "")
            if url:
                sources.append({
                    **common,
                    "type": "rss",
                    "url": url,
                    "rsshub": rsshub,
                })
    return sources


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def classify(title, summary, source_category):
    text = f"{title} {summary}"
    industries = [tag for tag, kws in INDUSTRY_RULES.items()
                  if any(kw.lower() in text.lower() for kw in kws)]
    ctype = source_category
    for tag, kws in TYPE_RULES.items():
        if any(kw.lower() in text.lower() for kw in kws):
            ctype = tag
            break
    frameworks = [tag for tag, kws in FRAMEWORK_RULES.items()
                  if any(kw.lower() in text.lower() for kw in kws)]
    if not industries:
        industries = ["其他"]
    return industries, ctype, frameworks


def notion_request(method, path, body=None, retry=3):
    for i in range(retry):
        try:
            res = requests.request(
                method, NOTION_API + path,
                headers=NOTION_HEADERS,
                data=json.dumps(body) if body is not None else None,
                timeout=30,
            )
            if res.status_code == 429:
                time.sleep(2 ** (i + 1))
                continue
            return res
        except requests.RequestException:
            if i == retry - 1:
                raise
            time.sleep(3)
    return res


def get_existing_urls():
    """拉取数据库中已有条目的链接，用于去重（分页循环）。"""
    urls = set()
    cursor = None
    while True:
        body = {"page_size": 100, "filter": {"property": "链接", "url": {"is_not_empty": True}}}
        if cursor:
            body["start_cursor"] = cursor
        res = notion_request("POST", f"/databases/{NOTION_DATABASE_ID}/query", body)
        if res.status_code != 200:
            print(f"[WARN] 拉取已有条目失败: HTTP {res.status_code} {res.text[:200]}")
            return urls
        data = res.json()
        for page in data.get("results", []):
            u = page.get("properties", {}).get("链接", {}).get("url")
            if u:
                urls.add(u.strip().rstrip("/"))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return urls


def create_page(item):
    properties = {
        "标题": {"title": [{"text": {"content": item["title"][:2000]}}]},
        "链接": {"url": item["url"]},
        "来源": {"select": {"name": item["source"]}},
        "发布日期": {"date": {"start": item["publish_date"]}},
        "抓取日期": {"date": {"start": item["fetch_date"]}},
        "行业": {"multi_select": [{"name": t} for t in item["industries"]]},
        "内容类型": {"select": {"name": item["ctype"]}},
        "摘要": {"rich_text": [{"text": {"content": item["summary"][:2000]}}]},
        "状态": {"select": {"name": "未读"}},
        "收藏": {"checkbox": False},
    }
    if item["frameworks"]:
        properties["营销框架"] = {"multi_select": [{"name": t} for t in item["frameworks"]]}
    res = notion_request("POST", "/pages", {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    })
    return res


def entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime.date(t[0], t[1], t[2]).isoformat()
    return datetime.date.today().isoformat()


def iso(d):
    """datetime/date -> YYYY-MM-DD。None 时回退今天。"""
    if d is None:
        return datetime.date.today().isoformat()
    if isinstance(d, datetime.datetime):
        return d.date().isoformat()
    return d.isoformat()


# ================= 抓取器（按 source 类型分派） ============
def _log_failure(src, reason, actual_url=""):
    """统一失败日志格式：源名 / 原因 / 抓取URL / 源站链接（方便排查）"""
    orig = src.get("original_url") or "（未配置）"
    print(f"[FAIL] {src['name']}: {reason}")
    if actual_url:
        print(f"        抓取URL: {actual_url}")
    print(f"        源站: {orig}")


def fetch_rss_source(src):
    """type=rss：用 feedparser 抓取，返回 List[Dict]，字段与 Item 一致。"""
    actual_url = src.get("url") or (RSSHUB_BASE + src["rsshub"] if RSSHUB_BASE and src.get("rsshub") else "")
    try:
        feed = feedparser.parse(src["url"], request_headers={
            "User-Agent": "Mozilla/5.0 (marketing-intel-collector)"})
    except Exception as e:
        _log_failure(src, f"抓取异常 {e}", actual_url)
        return [], True
    if feed.bozo and not feed.entries:
        reason = f"源不可用 ({feed.bozo_exception})" if feed.bozo_exception else "返回为空"
        _log_failure(src, reason, actual_url)
        return [], True

    out = []
    for entry in feed.entries:
        title = strip_html(getattr(entry, "title", "")) or "(无标题)"
        url = (getattr(entry, "link", "") or "").strip()
        if not url:
            continue
        pub = entry_date(entry)
        summary = strip_html(getattr(entry, "summary", ""))[:300]
        out.append({
            "title": title, "url": url, "source": src["name"],
            "publish_date": pub, "summary": summary,
        })
    return out, False


def fetch_scraper_source(src, registry):
    """type=scraper：调用对应爬虫类，返回标准化 Item。"""
    key = src.get("scraper")
    if key not in registry:
        _log_failure(src, f"未注册的爬虫 {key}（请检查 SCRAPER_REGISTRY）")
        return [], True
    cls, defaults = registry[key]
    params = {**defaults, **src.get("params", {})}
    try:
        scraper = cls(**params)
        items = scraper.fetch()
    except Exception as e:
        _log_failure(src, f"爬虫异常 {e}", src.get("original_url", ""))
        return [], True
    if not items:
        _log_failure(src, "爬虫未抓到任何条目（站点改版或反爬？）", src.get("original_url", ""))
        return [], True
    out = []
    for it in items:
        out.append({
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "publish_date": iso(it.published),
            "summary": it.summary,
        })
    return out, False


# ================= 主流程 =================
def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("[ERROR] 缺少环境变量 NOTION_TOKEN / NOTION_DATABASE_ID")
        sys.exit(1)

    sources = load_sources()
    registry = _build_scrapers()
    rss_count = sum(1 for s in sources if s["type"] == "rss")
    scraper_count = sum(1 for s in sources if s["type"] == "scraper")
    print(f"共 {len(sources)} 个信息源（RSS {rss_count} 个，爬虫 {scraper_count} 个），"
          f"抓取最近 {MAX_DAYS} 天，每源最多 {MAX_PER_SOURCE} 条\n")

    existing = get_existing_urls()
    print(f"Notion 已有 {len(existing)} 条记录（用于去重）\n")

    today = datetime.date.today()
    deadline = (today - datetime.timedelta(days=MAX_DAYS)).isoformat()
    fetch_date = today.isoformat()

    stats = {"ok": 0, "skip_old": 0, "dup": 0, "fail_write": 0}
    failed_sources = []

    for src in sources:
        if src["type"] == "scraper":
            raw_items, failed = fetch_scraper_source(src, registry)
        else:
            raw_items, failed = fetch_rss_source(src)
        if failed:
            failed_sources.append(src)

        written = 0
        for item in raw_items:
            if written >= MAX_PER_SOURCE:
                break
            url = item["url"].strip()
            if not url:
                continue
            if url.rstrip("/") in existing:
                stats["dup"] += 1
                continue
            pub = item["publish_date"]
            if pub < deadline:
                stats["skip_old"] += 1
                continue
            title = item["title"]
            summary = item["summary"]
            industries, ctype, frameworks = classify(title, summary, src["category"])

            res = create_page({
                "title": title, "url": url, "source": item["source"],
                "publish_date": pub, "fetch_date": fetch_date,
                "industries": industries, "ctype": ctype,
                "frameworks": frameworks, "summary": summary,
            })
            if res.status_code == 200:
                existing.add(url.rstrip("/"))
                written += 1
                stats["ok"] += 1
                print(f"  [+] {src['name']} | {ctype} | {title[:40]}")
            else:
                stats["fail_write"] += 1
                print(f"  [ERR] 写入失败 HTTP {res.status_code}: {res.text[:150]}")
            time.sleep(0.35)  # Notion 限速 ~3 req/s

    print("\n========== 采集汇总 ==========")
    print(f"新增写入: {stats['ok']}  |  跳过重复: {stats['dup']}  |  "
          f"跳过过期: {stats['skip_old']}  |  写入失败: {stats['fail_write']}")
    if failed_sources:
        print(f"\n失败源 ({len(failed_sources)} 个)，请复制下方链接人工访问或排查：")
        for s in failed_sources:
            if s["type"] == "scraper":
                actual = f"自建爬虫 scrapers/{s.get('scraper','?')}.py"
            else:
                actual = s.get("url") or ((RSSHUB_BASE + s["rsshub"]) if RSSHUB_BASE and s.get("rsshub") else "(无)")
            print(f"  - {s['name']}")
            print(f"      抓取URL: {actual}")
            print(f"      源站: {s.get('original_url') or '（未配置）'}")
        print("\n排查思路:")
        print("  • 抓取URL 404/重定向 → RSSHub 路由变更，到 https://docs.rsshub.app 查新路由，改 sources.yaml 一行即可")
        print("  • 抓取URL 429/限速 → RSSHub 公共实例限流，可自建（README 第六步）或临时跳过该源")
        print("  • 爬虫异常 → 站点改版，编辑 scrapers/<name>.py 即可，其它文件不用动")
        print("  • 源站URL 可访问 → 大概率是 RSSHub 路由挂了，去源站找最新的 RSS 链接替换 url/rsshub")


if __name__ == "__main__":
    main()