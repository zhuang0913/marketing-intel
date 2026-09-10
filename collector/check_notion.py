"""
Notion 连通性自检：验证 Token 是否有效、父页面是否已共享给 Integration。

用法：
    python check_notion.py

不需要任何参数，会从 .env.local 读取凭证。
"""

import json
import sys
import urllib.error
import urllib.request

from bootstrap_notion import NOTION_BASE, NOTION_VERSION, fmt_id, load_env

OK = "[OK]  "
FAIL = "[FAIL]"


def api(method, endpoint, token, body=None):
    url = f"{NOTION_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    env = load_env()
    token = env.get("NOTION_TOKEN", "")
    page_id = fmt_id(env.get("NOTION_PARENT_PAGE_ID", ""))
    db_id = fmt_id(env.get("NOTION_DATABASE_ID", ""))

    print("=" * 58)
    print("Notion 连通性自检")
    print("=" * 58)
    print(f"Token        : {(token[:12] + '...' + token[-6:]) if token else '(未配置)'}")
    print(f"父页面 ID     : {page_id or '(未配置)'}")
    print(f"数据库 ID     : {db_id or '(未配置)'}")
    print("-" * 58)

    if not token:
        print(f"{FAIL} .env.local 里没有 NOTION_TOKEN")
        sys.exit(1)

    # --- 1) Token ---
    try:
        me = api("GET", "users/me", token)
        print(f"{OK} 1/3 Token 有效，Integration 名称: {me.get('name')}")
    except urllib.error.HTTPError as e:
        print(f"{FAIL} 1/3 Token 无效 HTTP {e.code}")
        print("      去 https://www.notion.so/profile/integrations 重新复制")
        sys.exit(1)

    # --- 2) 父页面 ---
    if page_id:
        try:
            pg = api("GET", f"pages/{page_id}", token)
            title = ""
            for v in (pg.get("properties") or {}).values():
                if v.get("type") == "title":
                    title = "".join(t.get("plain_text", "") for t in v.get("title", []))
            print(f"{OK} 2/3 父页面可访问，标题: {title or '(无标题)'}")
        except urllib.error.HTTPError as e:
            print(f"{FAIL} 2/3 父页面不可访问 HTTP {e.code}")
            if e.code == 404:
                print("      → 页面没共享给 Integration！")
                print("        新版界面路径：")
                print("        1. 页面右上角点 [共享] 打开面板")
                print("        2. 面板底部点 [高阶] 展开")
                print("        3. 找到 [连接/代理] → [添加] → 搜索 intel-bootstrap")
                print("        4. 添加后再点右上角 [···] 里的 [连接] 也可作为备用入口")
            sys.exit(1)
    else:
        print(f"{FAIL} 2/3 .env.local 里没有 NOTION_PARENT_PAGE_ID")
        sys.exit(1)

    # --- 3) 数据库（可选） ---
    if db_id:
        try:
            db = api("GET", f"databases/{db_id}", token)
            n = len(db.get("properties") or {})
            print(f"{OK} 3/3 数据库可访问，共 {n} 个属性")
        except urllib.error.HTTPError as e:
            print(f"{FAIL} 3/3 数据库不可访问 HTTP {e.code}")
            sys.exit(1)
    else:
        print("  --  3/3 跳过（还没建库，属正常）")

    print("-" * 58)
    print("全部通过 ✅  可以跑采集脚本了")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消")
