"""把 Notion 数据库全量导出为 JSON，供前端静态托管使用。

输出格式：与 Notion API query 端点一致，前端 index.html 的 mapNotionItem() 直接处理。
- results: Notion page 对象数组（带 properties）
- fetched_at: 导出时间（ISO 8601）
- count: 条目数
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def notion_query(token, db_id, page_size=100, start_cursor=None):
    body = {"page_size": page_size}
    if start_cursor:
        body["start_cursor"] = start_cursor
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
            "User-Agent": "marketing-intel-export/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def export(token, db_id):
    all_results = []
    cursor = None
    page = 0
    while True:
        page += 1
        try:
            data = notion_query(token, db_id, page_size=100, start_cursor=cursor)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[ERROR] page {page} 失败: {e.code} {body[:200]}", file=sys.stderr)
            sys.exit(1)
        results = data.get("results", [])
        all_results.extend(results)
        print(f"  page {page}: +{len(results)} (累计 {len(all_results)})")
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break

    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(all_results),
        "database_id": db_id,
        "results": all_results,
    }


def main():
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        print("缺少 NOTION_TOKEN 或 NOTION_DATABASE_ID", file=sys.stderr)
        sys.exit(1)

    print(f"导出数据库 {db_id} ...")
    payload = export(token, db_id)

    out_path = Path(__file__).parent.parent.parent / "docs" / "data.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"\n✅ 已写入 {out_path}  ({payload['count']} 条, {size_kb:.1f} KB)")


if __name__ == "__main__":
    main()