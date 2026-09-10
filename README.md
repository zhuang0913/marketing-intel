# 营销情报工作台

自动采集 30+ 中文营销信息源 → 自动分类打标 → 存入 Notion → 静态工作台查看/筛选/收藏/记笔记。

```
RSS 源(30+) ──> Python 采集脚本(GitHub Actions 每日运行) ──> Notion 数据库
                                                              │
工作台(index.html, 部署在 GitHub Pages) <── Cloudflare Worker 代理 ┘
```

## 项目结构

```
marketing-intel/
├── index.html                     # 工作台（演示模式/ API 模式）
├── worker/
│   └── worker.js                  # Cloudflare Worker 代理（保护 Notion 密钥 + 跨域）
├── collector/
│   ├── fetch_rss.py               # 采集主脚本（抓取/去重/打标/写入 Notion）
│   ├── sources.yaml               # 信息源清单（RSS + 自定义爬虫）
│   ├── scrapers/                  # 自定义站点爬虫（数英/SocialBeta/广告门）
│   │   ├── base.py                #   基类（UA/重试/HTML解析/日期解析）
│   │   ├── shuying.py             #   数英网爬虫
│   │   ├── socialbeta.py          #   SocialBeta 爬虫
│   │   └── adaomou.py             #   广告门爬虫
│   └── requirements.txt
├── .github/workflows/collect.yml  # 每日定时采集（GitHub Actions）
└── README.md
```

## 关于数据源稳定性（重要）

`sources.yaml` 中有两种数据源类型：

- **`type: rss`** —— 原生 RSS / RSSHub 路由。**优点**：免维护。**缺点**：RSSHub 公共实例（rsshub.app）有频率限制，路由会随站点改版失效（数英/SocialBeta/广告门尤其严重）。
- **`type: scraper`** —— 自定义 Python 爬虫。**优点**：完全可控，长期稳定，不依赖第三方服务。**缺点**：站点改版时要小修选择器。

**当前三个核心站已用爬虫**（数英/SocialBeta/广告门），其他站点继续用 RSS/RSSHub。

### 如何新增一个自定义爬虫

比如你想加一个 Morketing 数据源，编辑 3 个文件即可：

**1. `collector/scrapers/morketing.py`**（继承 BaseScraper，实现 parse）：

```python
from .base import BaseScraper, Item, clean_text, normalize_url

class MorketingScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            name="Morketing",
            list_urls=["https://www.morketing.com/"],
        )

    def parse(self, soup, page_url):
        items = []
        for a in soup.select('a[href*="/html/"]'):
            title = clean_text(a.get_text(), 120)
            url = normalize_url(a.get("href", ""), page_url)
            if title and url:
                items.append(Item(title=title, url=url, source=self.name))
        return items
```

**2. `collector/scrapers/__init__.py`** 加一行：`from .morketing import MorketingScraper`

**3. `collector/fetch_rss.py` 的 `_build_scrapers()`** 注册：

```python
from scrapers.morketing import MorketingScraper
...
return {
    ...
    "morketing": (MorketingScraper, {}),
}
```

**4. `collector/sources.yaml`** 加：

```yaml
  - name: Morketing
    type: scraper
    scraper: morketing
    category: 广告知识
```

下次 Actions 跑就会带上。

---

## 第一步：创建 Notion 数据库

1. 在 Notion 中新建一个页面，输入 `/table` 创建 **全页表格（Database - Full page）**。
2. 按下表添加属性（**属性名和类型必须完全一致**，脚本按名称读写）：

| 属性名 | 类型 | 说明 |
|---|---|---|
| 标题 | Title | 文章标题（主键） |
| 链接 | URL | 原文地址（去重依据） |
| 来源 | Select | 信息源名称，如 数英网 |
| 发布日期 | Date | 文章发布时间 |
| 抓取日期 | Date | 脚本采集时间 |
| 行业 | Multi-select | 美妆个护、食品饮料、服装时尚、母婴亲子、3C数码、大健康、餐饮、家居日用、宠物经济、酒水、其他 |
| 内容类型 | Select | 行业研报、平台洞察、电商知识、广告知识、产品知识、商业趋势、其他 |
| 营销框架 | Multi-select | 产品创新、消费者洞察、品牌定位、内容营销、渠道运营、私域运营、定价策略、增长黑客、供应链、ESG营销 |
| 摘要 | Text | 自动截取的文章摘要 |
| 状态 | Select | 未读 / 已读（默认未读） |
| 收藏 | Checkbox | 工作台星标同步到这里 |
| 笔记 | Text | 工作台笔记同步到这里 |

> 提示：Select/Multi-select 的选项无需预先录入，脚本写入时会自动创建；但先手动建好所有选项可以避免同义词分裂（例如"美妆"和"美妆个护"变成两个选项）。

3. 打开数据库右上角 `···` → **Connections / 连接** → 添加你创建的 Integration（见下一步）。
   **不执行这一步，集成无权访问数据库，脚本会报 401/404。**

### 创建 Integration（获取密钥）

1. 访问 https://www.notion.so/my-integrations → **New integration**。
2. 名字随意（如 marketing-intel），类型选 Internal，关联你的工作区。
3. 创建后复制 **Internal Integration Secret**（`secret_` 开头）→ 这就是 `NOTION_TOKEN`。
4. 数据库 URL 中 `?v=` 之前那串 32 位字符串 → 这就是 `NOTION_DATABASE_ID`。
   如 `https://notion.so/workspace/`**`a1b2c3...`**`?v=...`

---

## 第二步：部署 Cloudflare Worker 代理

方式 A —— 网页粘贴（最简单）：

1. 注册/登录 https://dash.cloudflare.com → 左侧 **Workers & Pages** → **Create** → **Create Worker**。
2. 部署默认 Worker 后点 **Edit code / 编辑代码**，把 `worker/worker.js` 的全部内容粘贴进去，**Deploy**。
3. 进入 Worker 的 **Settings → Variables and Secrets**，添加：

| 类型 | 变量名 | 值 |
|---|---|---|
| Secret | `NOTION_TOKEN` | 你的 `secret_...` |
| Variable | `NOTION_DATABASE_ID` | 数据库 32 位 ID |
| Variable | `ALLOW_ORIGIN` | 前端域名，如 `https://yourname.github.io`（开发期可留空） |

4. 记下 Worker 地址（如 `https://marketing-intel-proxy.yourname.workers.dev`）。
5. 浏览器访问 `https://.../api/health`，返回 `{"ok":true,...}` 即部署成功。

方式 B —— wrangler CLI：

```bash
cd worker
npx wrangler deploy worker.js --name marketing-intel-proxy \
  --var NOTION_DATABASE_ID:你的数据库ID ALLOW_ORIGIN:https://yourname.github.io
# NOTION_TOKEN 用 secret 方式: npx wrangler secret put NOTION_TOKEN
```

---

## 第三步：部署工作台（GitHub Pages）

1. 在 GitHub 新建仓库（如 `marketing-intel`），把本项目全部文件推上去：

```bash
cd marketing-intel
git init && git add -A && git commit -m "init: 营销情报工作台"
git branch -M main
git remote add origin https://github.com/你的用户名/marketing-intel.git
git push -u origin main
```

2. 仓库 **Settings → Pages** → Source 选 `Deploy from a branch`，分支 `main`、目录 `/ (root)` → Save。
3. 1-2 分钟后访问 `https://你的用户名.github.io/marketing-intel/`。
4. 编辑仓库中的 `index.html`，找到顶部配置区：

```js
const API_BASE = "";
```

改成你的 Worker 地址：

```js
const API_BASE = "https://marketing-intel-proxy.yourname.workers.dev";
```

提交后刷新页面，右上角徽章变为 **"API 模式（Notion 实时数据）"** 即接入成功。
（留空则是演示模式，用内置模拟数据体验全部交互。）

> 接入 API 后，回到 Worker 的 `ALLOW_ORIGIN` 变量，改成你最终的 Pages 域名，收紧跨域白名单。

---

## 第四步：配置每日自动采集

1. GitHub 仓库 **Settings → Secrets and variables → Actions** → **New repository secret**，添加：

| Secret 名 | 值 |
|---|---|
| `NOTION_TOKEN` | `secret_...` |
| `NOTION_DATABASE_ID` | 数据库 32 位 ID |

2. 仓库 **Actions** 标签页 → 左侧 "每日营销情报采集" → 若未启用点 **Enable workflow**。
3. 点 **Run workflow** 手动跑一次验证，点进日志查看采集汇总（新增/重复/失败源数量）。
4. 之后每天北京时间 10:00 左右自动执行（GitHub cron 可能有 15-30 分钟延迟）。

调整频率：编辑 `.github/workflows/collect.yml` 中的 cron 表达式。
调整采集范围：修改 workflow 中 `MAX_DAYS`（回看天数）和 `MAX_PER_SOURCE`（每源条数）。

---

## 信息源维护

- 源清单在 `collector/sources.yaml`，分六大类共 30 个源。
- 每个源都有 `original_url` 字段记录源站首页，**采集失败时日志会自动打印源站链接**，方便快速跳过去排查（详见下方"日常运维"）。
- 部分源通过 **RSSHub** 转换（很多中文营销站点没有原生 RSS）。公共实例 `rsshub.app` 有频率限制，建议：
  - 换镜像：改 `sources.yaml` 顶部的 `rsshub_base`；
  - 或自建：`docker run -d --name rsshub -p 1200:1200 diygod/rsshub`，然后把 base 改成 `http://你的服务器:1200`。
- 添加新源：在 `sources.yaml` 追加 3-4 行即可：
  ```yaml
  - name: Morketing
    category: 广告知识
    rsshub: /morketing           # 或 url: https://example.com/feed
    original_url: https://www.morketing.com/   # 必填：源站首页，失败时打印
  ```

## 日常运维：失败排查

每次采集结束，Actions 日志末尾会输出"采集汇总"。如果有失败源，会附上**完整链接列表**，复制就能直接访问排查：

```
========== 采集汇总 ==========
新增写入: 42 | 跳过重复: 18 | 跳过过期: 9 | 写入失败: 0

失败源 (2 个)，请复制下方链接人工访问或排查：
  - CBNData 消费站
      抓取URL: https://rsshub.app/cbndata/information
      源站: https://www.cbndata.com/
  - 数英网
      抓取URL: 自建爬虫 scrapers/shuying.py
      源站: https://www.digitaling.com/

排查思路:
  • 抓取URL 404/重定向 → RSSHub 路由变更，到 https://docs.rsshub.app 查新路由，
                         改 sources.yaml 的 rsshub/url 一行即可
  • 抓取URL 429/限速 → RSSHub 公共实例限流，可自建（见上节）或临时注释掉该源
  • 爬虫异常 → 站点改版，编辑 scrapers/<name>.py 即可，其它文件不用动
  • 源站URL 可访问但抓取URL 失败 → 大概率是 RSSHub 路由挂了，去源站找最新 RSS 替换
```

**临时禁用某个源**：在 `sources.yaml` 里把对应条目用 `# ` 注释掉即可，下次跑就跳过它。

**修改后立即验证**：在本地（确保 `pip install -r requirements.txt`）跑一次 `python collector/fetch_rss.py`（需要环境变量 `NOTION_TOKEN` / `NOTION_DATABASE_ID`），立刻能看到新的失败/通过情况。

## 分类规则调整

打标规则集中在 `collector/fetch_rss.py` 顶部的三个字典：

- `INDUSTRY_RULES` —— 关键词 → 行业标签（多标签）
- `TYPE_RULES` —— 关键词 → 内容类型（覆盖源默认类型）
- `FRAMEWORK_RULES` —— 关键词 → 营销框架标签（多标签）

标题+摘要命中关键词即打标。改完 push 即生效，无需其他操作。

---

## 常见问题

**Q: 工作台显示"数据加载失败"？**
先访问 Worker 的 `/api/health` 确认代理正常；再检查 Notion 数据库是否已连接 Integration（第一步第 3 小节）。

**Q: Actions 日志大量源失败？**
多为 RSSHub 公共实例限速。自建 RSSHub 或减少源数量、降低 `MAX_PER_SOURCE`。

**Q: 想改筛选维度/新增行业？**
`index.html` 顶部 `INDUSTRY / TYPES / FRAMEWORKS` 三个常量数组即选项列表，同时同步修改 Notion 属性选项和 `fetch_rss.py` 规则字典。

**Q: 演示模式的数据会保存吗？**
演示模式下已读/收藏/笔记操作保存在浏览器 localStorage，点"刷新"按钮可重置。API 模式下所有操作实时写回 Notion。
