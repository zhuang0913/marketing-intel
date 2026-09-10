/**
 * 营销情报工作台 - Notion API 代理（Cloudflare Worker）
 * ---------------------------------------------------------
 * 端点：
 *   GET   /api/health        健康检查
 *   GET   /api/items         拉取数据库全部条目（服务端循环分页，返回统一结构）
 *                            可选 ?filter=<URL编码的Notion filter JSON>&limit=N
 *   PATCH  /api/items/:id    更新条目，body 为简化格式：
 *                            { "status": "已读", "starred": true, "note": "..." }
 *                            （三个字段均可选，只传需要更新的）
 *
 * 环境变量（Cloudflare Dashboard -> Settings -> Variables）：
 *   NOTION_TOKEN        Notion 集成密钥（secret）
 *   NOTION_DATABASE_ID  数据库 ID（32位字符串）
 *   ALLOW_ORIGIN        允许跨域的前端域名，如 https://yourname.github.io（默认 * ）
 *
 * 部署方式见项目 README.md。
 */

const NOTION_VERSION = "2022-06-28";

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin || "*",
    "Access-Control-Allow-Methods": "GET, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

function notionHeaders(token) {
  return {
    "Authorization": "Bearer " + token,
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
  };
}

function json(status, body, extraHeaders) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

/** 循环分页拉取数据库全部条目 */
async function queryAll(env, filter) {
  let cursor = undefined;
  let results = [];
  do {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    if (filter) body.filter = filter;
    const res = await fetch(
      `https://api.notion.com/v1/databases/${env.NOTION_DATABASE_ID}/query`,
      { method: "POST", headers: notionHeaders(env.NOTION_TOKEN), body: JSON.stringify(body) }
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Notion query 失败 (HTTP ${res.status}): ${text}`);
    }
    const data = await res.json();
    results = results.concat(data.results);
    cursor = data.has_more ? data.next_cursor : undefined;
  } while (cursor);
  return results;
}

/** 简化 patch -> Notion properties */
function buildProperties(patch) {
  const props = {};
  if (patch.status !== undefined) {
    props["状态"] = { select: { name: patch.status } };
  }
  if (patch.starred !== undefined) {
    props["收藏"] = { checkbox: !!patch.starred };
  }
  if (patch.note !== undefined) {
    props["笔记"] = { rich_text: [{ text: { content: String(patch.note).slice(0, 2000) } }] };
  }
  if (Object.keys(props).length === 0) {
    throw new Error("请求体需包含 status / starred / note 至少一个字段");
  }
  return props;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const origin = env.ALLOW_ORIGIN || "*";

    // CORS 预检
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // 健康检查
    if (request.method === "GET" && (path === "/api/health" || path === "/")) {
      return json(200, { ok: true, service: "marketing-intel-proxy", time: new Date().toISOString() }, corsHeaders(origin));
    }

    // 查询条目
    if (request.method === "GET" && path === "/api/items") {
      try {
        let filter = null;
        const f = url.searchParams.get("filter");
        if (f) {
          try { filter = JSON.parse(f); } catch (e) {
            return json(400, { error: "filter 参数不是合法 JSON" }, corsHeaders(origin));
          }
        }
        const results = await queryAll(env, filter);
        const limit = parseInt(url.searchParams.get("limit") || "0", 10);
        const limited = limit > 0 ? results.slice(0, limit) : results;
        return json(200, { count: limited.length, results: limited }, corsHeaders(origin));
      } catch (err) {
        return json(502, { error: err.message }, corsHeaders(origin));
      }
    }

    // 更新条目
    const patchMatch = path.match(/^\/api\/items\/([0-9a-fA-F]{32})$/);
    if (request.method === "PATCH" && patchMatch) {
      try {
        const pageId = patchMatch[1];
        const patch = await request.json();
        const properties = buildProperties(patch);
        const res = await fetch(`https://api.notion.com/v1/pages/${pageId}`, {
          method: "PATCH",
          headers: notionHeaders(env.NOTION_TOKEN),
          body: JSON.stringify({ properties }),
        });
        if (!res.ok) {
          const text = await res.text();
          return json(502, { error: `Notion 更新失败 (HTTP ${res.status}): ${text}` }, corsHeaders(origin));
        }
        const page = await res.json();
        return json(200, { ok: true, id: page.id }, corsHeaders(origin));
      } catch (err) {
        return json(400, { error: err.message }, corsHeaders(origin));
      }
    }

    return json(404, { error: "Not Found" }, corsHeaders(origin));
  },
};
