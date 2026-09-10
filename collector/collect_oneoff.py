# -*- coding: utf-8 -*-
"""
一次性本地采集兜底脚本。

当前沙箱环境里 Python 的 OpenSSL 栈访问 api.notion.com 会被连接重置，
但 curl（Schannel）可以正常访问。本脚本临时把 fetch_rss.notion_request
替换为 curl 后端，用于在本地跑通首次全量采集。

GitHub Actions 运行在 Ubuntu 云端，不存在此问题，后续用正常 workflow 即可。
"""
import json
import os
import subprocess
import sys
import tempfile

# 加载 .env.local
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", ".env.local")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import fetch_rss


class CurlResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def notion_request_curl(method, path, body=None, retry=3):
    url = fetch_rss.NOTION_API + path
    headers = [
        "-H", f"Authorization: Bearer {fetch_rss.NOTION_TOKEN}",
        "-H", "Notion-Version: 2022-06-28",
        "-H", "Content-Type: application/json",
    ]
    body_file = None
    cmd = ["curl", "-s", "-w", "\\n%{http_code}", "-X", method, url] + headers
    if body is not None:
        body_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        json.dump(body, body_file, ensure_ascii=False)
        body_file.close()
        cmd += ["-d", f"@{body_file.name}"]

    last_err = None
    for i in range(retry):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60)
            lines = result.stdout.rsplit("\n", 1)
            status_code = int(lines[-1])
            text = lines[0] if len(lines) > 1 else ""
            return CurlResponse(status_code, text)
        except Exception as e:
            last_err = e
            time.sleep(2 ** i)
    raise last_err


import time
fetch_rss.notion_request = notion_request_curl

if __name__ == "__main__":
    fetch_rss.main()
