"""
一键建库脚本：自动创建"营销情报条目"数据库 + 12 个属性 + 全部标签选项。

【使用前你需要做这 4 件事】
1. 在 Notion 建一个空页面（标题随便，比如"营销情报数据库"）
2. 去 https://www.notion.so/profile/integrations 新建一个 Internal Integration，复制它的 token（secret_xxx）
3. 把那个空页面右上角 Share → Invite → 选你刚创建的 Integration
4. 在 .env.local 写入：
       NOTION_TOKEN=secret_你的token
       NOTION_PARENT_PAGE_ID=从那个空页面 URL 里提取的 32 位 ID

【然后跑这一行】
    python bootstrap_notion.py

【脚本会做的事】
- 调 Notion API 建库（12 个属性 + 全部 Select/Multi-select 选项）
- 输出 database_id 和数据库 URL
- 自动把 NOTION_DATABASE_ID 追加到 .env.local
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

DATABASE_TITLE = [{"type": "text", "text": {"content": "营销情报条目"}}]


def _select_options(names, color="default"):
    return [{"name": n, "color": color} for n in names]


# ================== 12 个属性（与 fetch_rss.py / index.html 完全对齐） ==================
PROPERTIES = {
    # 1. 标题（Title）
    "标题": {"title": {}},

    # 2. 状态（Select）
    "状态": {"select": {"options": [
        {"name": "未读", "color": "blue"},
        {"name": "已读", "color": "default"},
        {"name": "已收藏", "color": "yellow"},
    ]}},

    # 3. 来源（Select）
    "来源": {"select": {"options": []}},

    # 4. 链接（URL）
    "链接": {"url": {}},

    # 5. 发布日期（Date）
    "发布日期": {"date": {}},

    # 6. 抓取日期（Date）
    "抓取日期": {"date": {}},

    # 7. 摘要（Rich text）
    "摘要": {"rich_text": {}},

    # 8. 行业（Multi-select）
    "行业": {"multi_select": {"options": _select_options([
        "美妆个护", "食品饮料", "服装时尚", "母婴亲子", "3C数码",
        "大健康", "餐饮", "家居日用", "宠物经济", "酒水",
    ], color="blue")}},

    # 9. 内容类型（Select）
    "内容类型": {"select": {"options": _select_options([
        "行业研报", "平台洞察", "电商知识", "广告知识",
        "产品知识", "商业趋势", "其他",
    ], color="green")}},

    # 10. 营销框架（Multi-select）
    "营销框架": {"multi_select": {"options": _select_options([
        "产品创新", "消费者洞察", "品牌定位", "内容营销",
        "渠道运营", "私域运营", "定价策略", "增长黑客",
        "供应链", "ESG营销",
    ], color="orange")}},

    # 11. 收藏（Checkbox）
    "收藏": {"checkbox": {}},

    # 12. 笔记（Rich text）
    "笔记": {"rich_text": {}},
}


# ================== 工具函数 ==================
def _env_candidates():
    """依次查找 .env.local：collector/ 目录 → 项目根目录。"""
    here = Path(__file__).parent
    return [here / ".env.local", here.parent / ".env.local"]


def load_env():
    """从 .env.local 读环境变量（不依赖 python-dotenv）。

    会依次读取 collector/.env.local 和 marketing-intel/.env.local，
    两个文件都存在时后读到的键覆盖先读到的。
    """
    env = {}
    for env_path in _env_candidates():
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def env_file_for_write():
    """确定把 NOTION_DATABASE_ID 写回哪个文件（优先已有的那个）。"""
    for p in _env_candidates():
        if p.exists():
            return p
    return _env_candidates()[0]


def call_notion(method, endpoint, token, body=None):
    url = f"{NOTION_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API 返回 HTTP {e.code}\n{body}") from e


def fmt_id(s):
    """保留连字符的 32 位 ID；Notion API 两种格式都接受。"""
    return s.replace("-", "").strip()


# ================== 主流程 ==================
def main():
    env = load_env()
    token = env.get("NOTION_TOKEN", "")
    page_id = fmt_id(env.get("NOTION_PARENT_PAGE_ID", ""))

    if not token or not (token.startswith("secret_") or token.startswith("ntn_")):
        print("[ERROR] .env.local 缺少 NOTION_TOKEN（应以 secret_ 或 ntn_ 开头）")
        print()
        print("请先把这一行写进 marketing-intel/.env.local：")
        print("  NOTION_TOKEN=secret_你的token   # 旧版格式")
        print("  NOTION_TOKEN=ntn_你的token      # 新版格式")
        sys.exit(1)
    if not page_id:
        print("[ERROR] .env.local 缺少 NOTION_PARENT_PAGE_ID")
        print()
        print("请先把这一行写进 marketing-intel/.env.local：")
        print("  NOTION_PARENT_PAGE_ID=32位页面ID")
        print()
        print("提取方法：")
        print("  1. 打开那个空页面")
        print("  2. 看浏览器地址栏 URL，找 32 位十六进制字符串")
        print("  3. 例如：https://www.notion.so/a1b2c3d4e5f6789012345678abcdef01?v=xxx")
        print("     那段 a1b2c3d4e5f6789012345678abcdef01 就是")
        sys.exit(1)

    print(f"Token   : {token[:18]}...")
    print(f"Parent  : {page_id}")
    print(f"将创建  : 营销情报条目（{len(PROPERTIES)} 个属性）")
    print()

    body = {
        "parent": {"type": "page_id", "page_id": page_id},
        "title": DATABASE_TITLE,
        "properties": PROPERTIES,
    }

    print("调用 Notion API...")
    try:
        result = call_notion("POST", "databases", token, body)
    except RuntimeError as e:
        msg = str(e)
        print(f"\n[ERROR] {msg}\n")
        if "401" in msg:
            print("→ Token 无效，去 https://www.notion.so/profile/integrations 检查")
        elif "404" in msg:
            print("→ 找不到页面，可能原因：")
            print("  1. NOTION_PARENT_PAGE_ID 写错了（回头再看下 URL）")
            print("  2. Integration 还没被邀请到这个页面")
            print("     新版界面：页面右上角 [共享] → 面板底部 [高阶] → [连接/代理] → 添加 intel-bootstrap")
        elif "400" in msg:
            print("→ 请求格式被 Notion 拒绝（一般不会发生，如果出现请把上面 ERROR 内容贴给我）")
        sys.exit(1)

    db_id = result["id"].replace("-", "")
    db_url = result["url"]

    print()
    print("✅ 数据库创建成功！")
    print(f"   Database ID : {db_id}")
    print(f"   URL         : {db_url}")
    print()

    # 自动写入/更新 NOTION_DATABASE_ID 到 .env.local
    env_path = env_file_for_write()
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if "NOTION_DATABASE_ID=" in content:
        content = re.sub(r"NOTION_DATABASE_ID=.*\n?", f"NOTION_DATABASE_ID={db_id}\n", content)
        env_path.write_text(content, encoding="utf-8")
        print(f"✅ 已更新 {env_path.name} -> NOTION_DATABASE_ID（覆盖旧值）")
    else:
        with env_path.open("a", encoding="utf-8") as f:
            if content and not content.endswith("\n"):
                f.write("\n")
            f.write(f"NOTION_DATABASE_ID={db_id}\n")
        print(f"✅ 已自动写入 {env_path.name} -> NOTION_DATABASE_ID")

    print()
    print("下一步：把这个脚本的输出贴给我，我会继续帮你完成：")
    print("  1) 测试 Integration 连通 + 写入一条测试数据")
    print("  2) 跑真实采集脚本，把今天的数据全写进去")
    print("  3) 给你 Cloudflare / GitHub Pages 一键部署命令")


if __name__ == "__main__":
    main()
