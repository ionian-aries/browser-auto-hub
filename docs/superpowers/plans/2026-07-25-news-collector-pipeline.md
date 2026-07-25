# 资讯采集 Pipeline 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `news.collector` pipeline，完成「网页采集 → LLM 粗筛/细筛 → 入库」全链路，替换来也 RPA 资讯采集服务。

**Architecture:** 单 Pipeline + 7 个顺序阶段（方案 A），config 优先 + LLM 探索 Agent 兜底。模块拆分为 6 个文件，pipeline 类只做编排调度。

**Tech Stack:** Python 3.11+, Playwright (浏览器), litellm (LLM 统一调用), SQLAlchemy (异步 DB), pytest-asyncio (测试)

## Global Constraints

- 对齐 spec: `docs/specs/6.2026-07-25-资讯采集Pipeline设计.md`
- 浏览器初始化对齐 workflow.py: `async_playwright().start()`, `new_context()` 无参数, `asyncio.sleep()`, `timeout=60000`
- 不手动设置 user_agent — Playwright 默认 UA 与浏览器指纹自洽
- MySQL 8.0, DATETIME(fsp=6)
- DB 表由部署者预创建，engine 不执行 create_all
- 入库阈值: `decision="pass"` 且 `score >= 6.0`
- 限速: 同域名请求间隔 ≥ 2s, 信源切换延迟 5s

---

## 文件结构

```
packages/engine/src/engine/pipelines/news_collector/
├── __init__.py              # "News collector pipelines."
├── config_schema.py         # Config 结构定义 + resolve_config() 继承解析
├── config_store.py          # Config DB 读写（raw SQL via ctx.db）
├── crawler.py               # 基于 config 的列表提取 + 翻页 + 正文提取
├── explorer.py              # 探索 Agent: LLM 分析 DOM → 生成/修复 config
├── screener.py              # 粗筛（批量 LLM）+ 细筛（逐篇 LLM）
├── collector.py             # NewsCollectorPipeline 主编排（7 Phase）
└── prompts/
    ├── explorer.txt         # 探索 Agent 提示词
    ├── news_coarse.txt      # 粗筛提示词（迁移自 RPA 包）
    └── news_fine.txt        # 细筛提示词（迁移自 RPA 包）

packages/engine/tests/
├── test_news_config_schema.py
├── test_news_crawler.py
├── test_news_screener.py
├── test_news_explorer.py
└── test_news_collector.py
```

---

## Task 1: 数据库表创建 + config_schema 模块

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/__init__.py`
- Create: `packages/engine/src/engine/pipelines/news_collector/config_schema.py`
- Test: `packages/engine/tests/test_news_config_schema.py`
- SQL: 手动执行的 DDL（记录在 plan 中，由部署者执行）

**Interfaces:**
- Consumes: 无
- Produces: `resolve_config(source: dict, entry: dict) -> dict`, `validate_source_config(config: dict) -> bool`

- [ ] **Step 1: 记录 DDL（部署者手动执行）**

以下 SQL 需在 MySQL 中手动执行（spec §8）：

```sql
-- 表 1: 信源配置（LLM 自管理）
CREATE TABLE news_source_configs (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  source_name     VARCHAR(255)   NOT NULL COMMENT '信源名称',
  base_url        VARCHAR(1000)  NOT NULL COMMENT '信源根域名',
  config_json     JSON           NOT NULL COMMENT '完整配置',
  last_verified   DATETIME(6)    DEFAULT NULL COMMENT '最近成功采集时间',
  explore_count   INT            NOT NULL DEFAULT 0,
  created_at      DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at      DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE INDEX uk_base_url (base_url(500))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表 2: 素材库
CREATE TABLE documents (
  id            BIGINT         NOT NULL AUTO_INCREMENT PRIMARY KEY,
  category      VARCHAR(50)    NOT NULL,
  title         VARCHAR(500)   NOT NULL,
  content       LONGTEXT       NOT NULL,
  digest        TEXT           NOT NULL,
  insight       TEXT           DEFAULT NULL,
  link_url      VARCHAR(1000)  NOT NULL,
  doc_date      DATE           NOT NULL,
  website_name  VARCHAR(255)   NOT NULL,
  score         DECIMAL(3,1)   DEFAULT NULL,
  score_reason  VARCHAR(500)   DEFAULT NULL,
  INDEX idx_category (category),
  INDEX idx_category_score (category, score DESC),
  INDEX idx_doc_date (doc_date),
  UNIQUE INDEX uk_dedup (title(200), link_url(200))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表 3: 采集日志
CREATE TABLE news_crawl_log (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  execution_id    VARCHAR(64)    NOT NULL,
  source_name     VARCHAR(255)   NOT NULL,
  entry_url       VARCHAR(1000)  NOT NULL,
  page_number     INT            NOT NULL,
  items_found     INT            NOT NULL DEFAULT 0,
  status          VARCHAR(20)    NOT NULL,
  error_message   TEXT           DEFAULT NULL,
  crawled_at      DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_execution (execution_id),
  INDEX idx_source_entry (source_name, entry_url(200))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 2: 创建 `__init__.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/__init__.py
"""News collector pipelines."""
```

- [ ] **Step 3: 写 `test_news_config_schema.py` 的失败测试**

```python
# packages/engine/tests/test_news_config_schema.py
import pytest
from engine.pipelines.news_collector.config_schema import resolve_config


class TestResolveConfig:
    """entry 级覆盖 + source 级 fallback"""

    def test_entry_overrides_source_list(self):
        source = {
            "configs": {
                "list": {"mode": "selectors", "fields": {"container": "ul.old"}},
                "pagination": None,
                "detail": {"mode": "selectors", "fields": {"title": "h1"}},
            }
        }
        entry = {
            "configs": {
                "list": {"mode": "selectors", "fields": {"container": "ul.new"}},
            }
        }
        result = resolve_config(source, entry)
        assert result["list"]["fields"]["container"] == "ul.new"
        assert result["pagination"] is None
        assert result["detail"]["fields"]["title"] == "h1"

    def test_entry_without_configs_falls_back_to_source(self):
        source = {
            "configs": {
                "list": {"mode": "script", "fields": {"items": "() => []"}},
                "pagination": {"mode": "selectors", "fields": {"next": "a.next"}},
                "detail": {"mode": "selectors", "fields": {"title": "h1"}},
            }
        }
        entry = {}  # 无 configs
        result = resolve_config(source, entry)
        assert result["list"]["mode"] == "script"
        assert result["pagination"]["fields"]["next"] == "a.next"

    def test_pagination_null_means_no_pagination(self):
        source = {
            "configs": {
                "list": {"mode": "selectors", "fields": {}},
                "pagination": None,
                "detail": {"mode": "selectors", "fields": {}},
            }
        }
        entry = {}
        result = resolve_config(source, entry)
        assert result["pagination"] is None
```

- [ ] **Step 4: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_config_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.pipelines.news_collector'`

- [ ] **Step 5: 实现 `config_schema.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/config_schema.py
"""Config 数据结构定义 + 继承解析（spec §3）"""

from __future__ import annotations


def resolve_config(source: dict, entry: dict) -> dict:
    """entry 级覆盖，未定义则 fallback 到 source 级。

    Returns:
        {"list": {...}, "pagination": {...} | None, "detail": {...}}
    """
    entry_configs = entry.get("configs", {})
    source_configs = source["configs"]
    return {
        "list":       entry_configs.get("list")       or source_configs["list"],
        "pagination": entry_configs.get("pagination") or source_configs.get("pagination"),
        "detail":     entry_configs.get("detail")     or source_configs.get("detail"),
    }
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_config_schema.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/__init__.py \
       packages/engine/src/engine/pipelines/news_collector/config_schema.py \
       packages/engine/tests/test_news_config_schema.py
git commit -m "feat(news): add config_schema with resolve_config inheritance"
```

---

## Task 2: 提示词文件迁移

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/prompts/explorer.txt`
- Create: `packages/engine/src/engine/pipelines/news_collector/prompts/news_coarse.txt`
- Create: `packages/engine/src/engine/pipelines/news_collector/prompts/news_fine.txt`

**Interfaces:**
- Consumes: 无
- Produces: 文本文件，被 screener.py 和 explorer.py 通过 `Path(__file__).parent / "prompts" / "xxx.txt"` 读取

- [ ] **Step 1: 创建 `news_coarse.txt`**

从 RPA 交付包 `prompts/news-coarse.md` 复制全文到 `prompts/news_coarse.txt`。
内容即上文中 news-coarse.md 的完整文本（去掉首行 `# 资讯粗筛提示词` 标题和 `> version` 元数据行）。

- [ ] **Step 2: 创建 `news_fine.txt`**

从 RPA 交付包 `prompts/news-fine.md` 复制全文到 `prompts/news_fine.txt`。
内容即上文中 news-fine.md 的完整文本（去掉首行标题和元数据行）。

- [ ] **Step 3: 创建 `explorer.txt`**

```
## 角色
你是一个网页结构分析专家。你的任务是分析一个网页的 DOM 结构，生成用于自动化采集的配置。

## 输入
1. 页面的简化 DOM 结构摘要（JSON 格式，已去除 script/style/nav/footer 等噪音）
2. 页面 URL：{url}
3. 信源名称：{source_name}
4. 页面类型：{page_type}（list 或 detail）

## 任务

### 当 page_type = "list" 时
分析 DOM 结构，输出配置 JSON，包含三个部分：

**list（列表提取）**
- 从 repeating_structures 中找到包含新闻条目的容器
- 识别列表项的标签、class、标题、链接、日期的提取方式
- 优先使用 CSS 选择器（mode="selectors"）
- 如果选择器无法完成（如日期藏在 URL 中），使用 JS 代码块（mode="script"）

**pagination（翻页）**
- 从 pagination_candidates 中识别翻页机制
- 无翻页时输出 null

**detail（详情页，推断）**
- 基于常见政府网站结构推断详情页的标题、正文、日期、来源选择器

### 当 page_type = "detail" 时
分析 DOM 结构，输出 detail 配置：
- title: 文章标题（通常是 h1 或最大的标题元素）
- content: 正文内容（最长的文本块容器）
- date: 发布日期
- source: 来源信息

## 输出格式
严格输出 JSON，不输出解释文字。

{config_json_schema}

## 约束
- 选择器必须能在当前页面匹配到 ≥1 个元素
- JS 代码必须是可直接 page.evaluate() 的纯函数体（箭头函数）
- 日期格式统一为 YYYY-MM-DD
{repair_hint}
```

- [ ] **Step 4: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/prompts/
git commit -m "feat(news): add prompt templates (coarse, fine, explorer)"
```

---

## Task 3: LLM 客户端 + 依赖

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/llm_client.py`
- Modify: `packages/engine/pyproject.toml`
- Test: `packages/engine/tests/test_news_llm_client.py`

**Interfaces:**
- Consumes: 环境变量 `LLM_API_KEY`, `LLM_MODEL` (可选), `LLM_BASE_URL` (可选)
- Produces: `async def call_llm(prompt: str, system: str | None = None) -> str`

- [ ] **Step 1: 添加 litellm 依赖**

修改 `packages/engine/pyproject.toml`，在 `dependencies` 中添加：

```toml
dependencies = [
    "pydantic>=2.0",
    "playwright>=1.40",
    "litellm>=1.40",
]
```

Run: `cd packages/engine && uv sync`

- [ ] **Step 2: 写 `test_news_llm_client.py` 的失败测试**

```python
# packages/engine/tests/test_news_llm_client.py
import json
import pytest
from unittest.mock import AsyncMock, patch


class TestCallLlm:
    @pytest.mark.asyncio
    async def test_call_llm_returns_text(self):
        from engine.pipelines.news_collector.llm_client import call_llm

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '{"results": []}'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm("test prompt", system="test system")
            assert result == '{"results": []}'

    @pytest.mark.asyncio
    async def test_call_llm_json_parse(self):
        from engine.pipelines.news_collector.llm_client import call_llm_json

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '{"decision": "pass", "score": 8.0}'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm_json("test prompt")
            assert result["decision"] == "pass"
            assert result["score"] == 8.0

    @pytest.mark.asyncio
    async def test_call_llm_json_strips_markdown(self):
        from engine.pipelines.news_collector.llm_client import call_llm_json

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '```json\n{"decision": "pass"}\n```'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm_json("test prompt")
            assert result["decision"] == "pass"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_llm_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 实现 `llm_client.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/llm_client.py
"""LLM 调用封装 — 基于 litellm 统一接口。

环境变量:
  LLM_API_KEY:   API 密钥（必填）
  LLM_MODEL:     模型名（默认 gpt-4o）
  LLM_BASE_URL:  API base URL（可选，用于自建/代理）
"""

from __future__ import annotations

import json
import os
import re

import litellm


async def _acompletion(messages: list[dict], **kwargs):
    """内部包装，方便测试 mock。"""
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL")
    kw = {"model": model, "messages": messages, "api_key": api_key}
    if base_url:
        kw["api_base"] = base_url
    kw.update(kwargs)
    return await litellm.acompletion(**kw)


async def call_llm(prompt: str, system: str | None = None) -> str:
    """调用 LLM，返回原始文本。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = await _acompletion(messages)
    return response.choices[0].message.content


async def call_llm_json(prompt: str, system: str | None = None) -> dict:
    """调用 LLM，解析返回 JSON。自动去除 markdown 代码块包裹。"""
    text = await call_llm(prompt, system)
    # 去除 ```json ... ``` 包裹
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_llm_client.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add packages/engine/pyproject.toml \
       packages/engine/src/engine/pipelines/news_collector/llm_client.py \
       packages/engine/tests/test_news_llm_client.py
git commit -m "feat(news): add LLM client wrapper with litellm"
```

---

## Task 4: config_store — Config DB 读写

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/config_store.py`
- Test: `packages/engine/tests/test_news_config_store.py`

**Interfaces:**
- Consumes: `ctx.db` (AsyncSession), `config_schema.resolve_config`
- Produces: `async def load_config(db, base_url) -> dict | None`, `async def save_config(db, source_name, base_url, config_json) -> None`, `async def increment_explore_count(db, base_url) -> None`

- [ ] **Step 1: 写失败测试**

```python
# packages/engine/tests/test_news_config_store.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from engine.pipelines.news_collector.config_store import load_config, save_config


class TestConfigStore:
    @pytest.mark.asyncio
    async def test_load_config_found(self):
        row = MagicMock()
        row.config_json = json.dumps({"configs": {"list": {"mode": "selectors"}}})
        row.source_name = "交通运输部"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        config = await load_config(db, "https://www.mot.gov.cn")
        assert config is not None
        assert config["source_name"] == "交通运输部"

    @pytest.mark.asyncio
    async def test_load_config_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        config = await load_config(db, "https://unknown.example.com")
        assert config is None

    @pytest.mark.asyncio
    async def test_save_config_insert(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        await save_config(db, "新华社", "https://www.news.cn",
                          {"configs": {"list": {"mode": "selectors"}}})
        assert db.execute.called
        assert db.commit.called
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_config_store.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `config_store.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/config_store.py
"""Config DB 读写 — raw SQL via AsyncSession（spec §8.1）"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


async def load_config(db: Any, base_url: str) -> dict | None:
    """从 news_source_configs 加载信源配置。"""
    result = await db.execute(
        text("SELECT source_name, config_json FROM news_source_configs "
             "WHERE base_url = :base_url LIMIT 1"),
        {"base_url": base_url},
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    config = json.loads(row.config_json) if isinstance(row.config_json, str) else row.config_json
    return {"source_name": row.source_name, **config}


async def save_config(db: Any, source_name: str, base_url: str,
                      config_json: dict) -> None:
    """UPSERT 信源配置到 news_source_configs。"""
    await db.execute(
        text("INSERT INTO news_source_configs (source_name, base_url, config_json) "
             "VALUES (:name, :url, :cfg) "
             "ON DUPLICATE KEY UPDATE "
             "source_name = VALUES(source_name), "
             "config_json = VALUES(config_json), "
             "updated_at = CURRENT_TIMESTAMP(6)"),
        {"name": source_name, "url": base_url,
         "cfg": json.dumps(config_json, ensure_ascii=False)},
    )
    await db.commit()


async def increment_explore_count(db: Any, base_url: str) -> None:
    """累加探索 Agent 触发次数。"""
    await db.execute(
        text("UPDATE news_source_configs SET explore_count = explore_count + 1 "
             "WHERE base_url = :base_url"),
        {"base_url": base_url},
    )
    await db.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_config_store.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/config_store.py \
       packages/engine/tests/test_news_config_store.py
git commit -m "feat(news): add config_store for DB read/write"
```

---

## Task 5: crawler — 基于 config 的列表提取 + 翻页 + 正文提取

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/crawler.py`
- Test: `packages/engine/tests/test_news_crawler.py`

**Interfaces:**
- Consumes: `config_schema.resolve_config`, Playwright `Page`
- Produces:
  - `async def try_extract_items(page, list_config) -> list[dict]` — 返回 `[{title, date, url}, ...]`
  - `async def go_next_page(page, pagination_config) -> bool` — 翻页成功返回 True
  - `async def try_extract_detail(page, detail_config) -> dict | None` — 返回 `{title, content, date, source}`

- [ ] **Step 1: 写失败测试**

```python
# packages/engine/tests/test_news_crawler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from engine.pipelines.news_collector.crawler import (
    try_extract_items, go_next_page, try_extract_detail,
)


class FakeLocator:
    def __init__(self, items):
        self._items = items

    async def count(self):
        return len(self._items)

    def nth(self, i):
        return self._items[i]


class FakeElement:
    def __init__(self, text="", href=None, child=None):
        self._text = text
        self._href = href
        self._child = child

    async def inner_text(self):
        return self._text

    async def get_attribute(self, name):
        if name == "href":
            return self._href
        return None

    async def query_selector(self, sel):
        return self._child


class TestTryExtractItems:
    @pytest.mark.asyncio
    async def test_selectors_mode(self):
        """selectors 模式：用 page.locator 提取"""
        # 构造 fake item: <li><a href="/news/1">标题A</a><span>2026-06-01</span></li>
        link = FakeElement(text="标题A", href="/news/1")
        date_el = FakeElement(text="2026-06-01")
        item = MagicMock()
        item.inner_text = AsyncMock(return_value="标题A\n2026-06-01")
        item.query_selector = AsyncMock(side_effect=lambda sel: link if "a" in sel else date_el)
        item.query_selector_all = AsyncMock(return_value=[date_el])

        page = MagicMock()
        page.locator = MagicMock(return_value=FakeLocator([item]))

        config = {
            "mode": "selectors",
            "fields": {
                "container": "ul.news-list",
                "item": "li",
                "title": "a",
                "link": "a",
                "link_attr": "href",
                "date": "span",
            },
        }
        items = await try_extract_items(page, config)
        assert len(items) == 1
        assert items[0]["title"] == "标题A"

    @pytest.mark.asyncio
    async def test_script_mode(self):
        """script 模式：用 page.evaluate 执行 JS"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=[
            {"title": "新闻1", "date": "2026-06-15", "url": "/n/1"},
            {"title": "新闻2", "date": "2026-06-14", "url": "/n/2"},
        ])

        config = {
            "mode": "script",
            "fields": {
                "items": "() => Array.from(document.querySelectorAll('li')).map(...)",
            },
        }
        items = await try_extract_items(page, config)
        assert len(items) == 2
        assert items[0]["title"] == "新闻1"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """提取结果为空列表"""
        page = MagicMock()
        page.locator = MagicMock(return_value=FakeLocator([]))

        config = {"mode": "selectors", "fields": {"container": "ul", "item": "li",
                   "title": "a", "link": "a", "link_attr": "href", "date": "span"}}
        items = await try_extract_items(page, config)
        assert items == []


class TestGoNextPage:
    @pytest.mark.asyncio
    async def test_no_pagination(self):
        """pagination 为 None → 返回 False"""
        page = MagicMock()
        result = await go_next_page(page, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_selectors_click_next(self):
        """selectors 模式：点击下一页按钮"""
        next_btn = MagicMock()
        next_btn.count = AsyncMock(return_value=1)
        next_btn.click = AsyncMock()

        page = MagicMock()
        page.locator = MagicMock(return_value=next_btn)
        page.wait_for_load_state = AsyncMock()

        config = {"mode": "selectors", "fields": {"next": "a.next", "next_text": "下一页"}}
        result = await go_next_page(page, config)
        assert result is True
        next_btn.click.assert_called_once()


class TestTryExtractDetail:
    @pytest.mark.asyncio
    async def test_selectors_mode(self):
        """selectors 模式提取正文"""
        page = MagicMock()

        async def fake_locator(sel):
            loc = MagicMock()
            if "h1" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="文章标题")
                loc.count = AsyncMock(return_value=1)
            elif "content" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="这是正文内容，超过50字的文本..." * 5)
                loc.count = AsyncMock(return_value=1)
            elif "date" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="2026-06-15")
                loc.count = AsyncMock(return_value=1)
            else:
                loc.count = AsyncMock(return_value=0)
            return loc

        page.locator = fake_locator

        config = {
            "mode": "selectors",
            "fields": {"title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"},
        }
        result = await try_extract_detail(page, config)
        assert result is not None
        assert result["title"] == "文章标题"

    @pytest.mark.asyncio
    async def test_script_mode(self):
        """script 模式执行 JS"""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=lambda code: {
            "title_code": "文章标题",
            "content_code": "正文内容" * 20,
            "date_code": "2026-06-15",
            "source_code": "新华社",
        }.get(code, ""))

        config = {
            "mode": "script",
            "fields": {
                "title": "title_code",
                "content": "content_code",
                "date": "date_code",
                "source": "source_code",
            },
        }
        result = await try_extract_detail(page, config)
        assert result is not None
        assert result["title"] == "文章标题"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_crawler.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `crawler.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/crawler.py
"""基于 config 的列表提取 + 翻页 + 正文提取（spec §3.5, §3.6）"""

from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page


async def try_extract_items(page: Page, list_config: dict) -> list[dict]:
    """基于 list config 提取当前页的新闻条目。

    Returns: [{title, date, url}, ...] 空列表表示提取失败。
    """
    mode = list_config["mode"]
    fields = list_config["fields"]

    if mode == "script":
        # JS 代码块直接返回数组
        result = await page.evaluate(fields["items"])
        if not result:
            return []
        return [
            {"title": it.get("title", ""), "date": it.get("date"), "url": it.get("url", "")}
            for it in result
        ]

    # mode == "selectors"
    container_sel = fields.get("container", "")
    item_sel = fields.get("item", "li")
    full_sel = f"{container_sel} > {item_sel}" if container_sel else item_sel

    items_loc = page.locator(full_sel)
    count = await items_loc.count()
    if count == 0:
        return []

    results = []
    for i in range(count):
        el = items_loc.nth(i)
        # 标题
        title_sel = fields.get("title", "a")
        title_el = await el.query_selector(title_sel)
        title = (await title_el.inner_text()).strip() if title_el else ""

        # 链接
        link_sel = fields.get("link", "a")
        link_el = await el.query_selector(link_sel)
        link_attr = fields.get("link_attr", "href")
        url = (await link_el.get_attribute(link_attr)) if link_el else ""

        # 日期
        date = None
        date_sel = fields.get("date")
        if date_sel:
            date_el = await el.query_selector(date_sel)
            if date_el:
                date_text = (await date_el.inner_text()).strip()
                # 尝试标准化日期
                m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_text)
                if m:
                    date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        # 日期 fallback：从 URL 中提取
        if not date and url:
            m = re.search(r"/(\d{4})(\d{2})/.*?(\d{4})(\d{2})(\d{2})", url)
            if m:
                date = f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
            else:
                m = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
                if m:
                    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        if title or url:
            results.append({"title": title, "date": date, "url": url or ""})

    return results


async def go_next_page(page: Page, pagination_config: dict | None) -> bool:
    """翻到下一页。返回 True 表示成功，False 表示无下一页。"""
    if pagination_config is None:
        return False

    mode = pagination_config["mode"]
    fields = pagination_config["fields"]

    if mode == "script":
        next_url = await page.evaluate(fields.get("next_url", "() => null"))
        if not next_url:
            return False
        await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        return True

    # mode == "selectors"
    # 优先 url_pattern
    url_pattern = fields.get("url_pattern")
    if url_pattern:
        # 从当前 URL 推断下一页
        current = page.url
        m = re.search(r"index_(\d+)\.html", current)
        if m:
            next_page = int(m.group(1)) + 1
            next_url = re.sub(r"index_\d+\.html", f"index_{next_page}.html", current)
        else:
            next_url = current.rstrip("/").rsplit("/", 1)[0] + "/" + url_pattern.replace("{page}", "1")
        await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        return True

    # 点击下一页按钮
    next_sel = fields.get("next", "")
    if not next_sel:
        return False
    btn = page.locator(next_sel)
    if await btn.count() == 0:
        return False
    await btn.first.click()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return True


async def try_extract_detail(page: Page, detail_config: dict | None) -> dict | None:
    """基于 detail config 提取正文。返回 {title, content, date, source} 或 None。"""
    if detail_config is None:
        return None

    mode = detail_config["mode"]
    fields = detail_config["fields"]

    if mode == "script":
        result = {}
        for key in ("title", "content", "date", "source"):
            code = fields.get(key)
            if code:
                result[key] = await page.evaluate(code)
            else:
                result[key] = ""
        if not result.get("content"):
            return None
        return result

    # mode == "selectors"
    result = {}
    for key in ("title", "content", "date", "source"):
        sel = fields.get(key)
        if sel:
            loc = page.locator(sel)
            if await loc.count() > 0:
                result[key] = (await loc.first.inner_text()).strip()
            else:
                result[key] = ""
        else:
            result[key] = ""

    if not result.get("content"):
        return None

    # 日期标准化
    if result.get("date"):
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", result["date"])
        if m:
            result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_crawler.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/crawler.py \
       packages/engine/tests/test_news_crawler.py
git commit -m "feat(news): add crawler with selectors/script mode support"
```

---

## Task 6: screener — 粗筛 + 细筛

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/screener.py`
- Test: `packages/engine/tests/test_news_screener.py`

**Interfaces:**
- Consumes: `llm_client.call_llm_json`, prompts 文件
- Produces:
  - `async def coarse_screen(items: list[dict], start_date: str, end_date: str, preference: str | None, batch_size: int) -> list[dict]` — 返回 pass 的 items
  - `async def fine_screen(item: dict, start_date: str, end_date: str) -> dict | None` — 返回细筛结果或 None (reject)

- [ ] **Step 1: 写失败测试**

```python
# packages/engine/tests/test_news_screener.py
import pytest
from unittest.mock import AsyncMock, patch
from engine.pipelines.news_collector.screener import coarse_screen, fine_screen


class TestCoarseScreen:
    @pytest.mark.asyncio
    async def test_coarse_filters_rejected(self):
        items = [
            {"id": "1", "title": "港口吞吐量增长", "date": "2026-06-15", "url": "/1"},
            {"id": "2", "title": "教育部招生计划", "date": "2026-06-15", "url": "/2"},
        ]
        with patch("engine.pipelines.news_collector.screener.call_llm_json",
                    new_callable=AsyncMock,
                    return_value={"results": [
                        {"id": "1", "decision": "pass"},
                        {"id": "2", "decision": "reject"},
                    ]}):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert len(result) == 1
            assert result[0]["title"] == "港口吞吐量增长"

    @pytest.mark.asyncio
    async def test_coarse_batch_split(self):
        """20+ items 分成多批"""
        items = [{"id": str(i), "title": f"标题{i}", "date": None, "url": f"/{i}"}
                 for i in range(25)]

        call_count = 0
        async def mock_llm(prompt, system=None):
            nonlocal call_count
            call_count += 1
            # 返回全部 pass
            import json, re
            m = re.search(r'"items":\s*\[', prompt)
            # 简化：返回对应数量的 pass
            count = 20 if call_count == 1 else 5
            return {"results": [{"id": str(i), "decision": "pass"} for i in range(count)]}

        with patch("engine.pipelines.news_collector.screener.call_llm_json",
                    new_callable=AsyncMock, side_effect=mock_llm):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert call_count == 2  # 25 items → 2 批


class TestFineScreen:
    @pytest.mark.asyncio
    async def test_fine_pass(self):
        item = {"title": "港口建设", "content": "正文内容" * 50,
                "date": "2026-06-15", "url": "/1", "source_name": "交通运输部"}

        with patch("engine.pipelines.news_collector.screener.call_llm_json",
                    new_callable=AsyncMock,
                    return_value={
                        "decision": "pass",
                        "doc_date": "2026-06-15",
                        "category": "建设发展",
                        "digest": "摘要",
                        "insight": "行业观察",
                        "score": 7.5,
                        "score_reason": "信息质量高",
                    }):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is not None
            assert result["score"] == 7.5
            assert result["category"] == "建设发展"

    @pytest.mark.asyncio
    async def test_fine_reject(self):
        item = {"title": "无关内容", "content": "正文" * 50,
                "date": "2026-06-15", "url": "/1", "source_name": "x"}

        with patch("engine.pipelines.news_collector.screener.call_llm_json",
                    new_callable=AsyncMock,
                    return_value={"decision": "reject", "reject_reason": "与港航无关"}):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is None

    @pytest.mark.asyncio
    async def test_fine_below_threshold(self):
        """score < 6.0 → 返回 None"""
        item = {"title": "低分", "content": "正文" * 50,
                "date": "2026-06-15", "url": "/1", "source_name": "x"}

        with patch("engine.pipelines.news_collector.screener.call_llm_json",
                    new_callable=AsyncMock,
                    return_value={
                        "decision": "pass", "doc_date": "2026-06-15",
                        "category": "建设发展", "digest": "x", "insight": "x",
                        "score": 4.5, "score_reason": "信息碎片",
                    }):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_screener.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `screener.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/screener.py
"""粗筛（批量 LLM）+ 细筛（逐篇 LLM）（spec §6 Phase 4/6）"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .llm_client import call_llm_json

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_COARSE_PROMPT = (_PROMPTS_DIR / "news_coarse.txt").read_text(encoding="utf-8")
_FINE_PROMPT = (_PROMPTS_DIR / "news_fine.txt").read_text(encoding="utf-8")

# 细筛入库阈值
_SCORE_THRESHOLD = 6.0


async def coarse_screen(
    items: list[dict],
    start_date: str,
    end_date: str,
    preference: str | None,
    batch_size: int = 20,
) -> list[dict]:
    """批量粗筛，返回 decision=pass 的 items。

    Args:
        items: [{title, date, url, ...}, ...]（需含 id 字段或在函数内分配）
        batch_size: 每批条数，默认 20
    """
    # 为每条 item 分配临时 id
    for i, it in enumerate(items):
        it.setdefault("id", str(i))

    passed = []
    sem = asyncio.Semaphore(3)

    async def _process_batch(batch: list[dict]):
        async with sem:
            items_json = json.dumps(
                [{"id": it["id"], "title": it.get("title", ""),
                  "doc_date": it.get("date"), "link_url": it.get("url", "")}
                 for it in batch],
                ensure_ascii=False,
            )
            prompt = _COARSE_PROMPT.replace("{start_date}", start_date)
            prompt = prompt.replace("{end_date}", end_date)
            # 注入 preference 到关注范围（如有）
            if preference:
                prompt += f"\n\n## 额外关注\n{preference}"
            prompt += f"\n\n## 输入\n```json\n{{\"start_date\": \"{start_date}\", \"end_date\": \"{end_date}\", \"items\": {items_json}}}\n```"

            try:
                result = await call_llm_json(prompt)
                decisions = {r["id"]: r["decision"] for r in result.get("results", [])}
                for it in batch:
                    if decisions.get(it["id"]) == "pass":
                        passed.append(it)
            except Exception:
                # LLM 失败 → 该批次全部 pass（宁可多 pass 不可误 reject）
                passed.extend(batch)

    # 分批
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        await _process_batch(batch)

    return passed


async def fine_screen(
    item: dict,
    start_date: str,
    end_date: str,
) -> dict | None:
    """单篇细筛。返回细筛结果（含 category/digest/insight/score），
    reject 或 score < 6.0 时返回 None。
    """
    prompt = _FINE_PROMPT.replace("{start_date}", start_date)
    prompt = prompt.replace("{end_date}", end_date)
    prompt += f"\n\n## 输入\n```json\n{json.dumps({
        'start_date': start_date,
        'end_date': end_date,
        'title': item.get('title', ''),
        'content': item.get('content', ''),
        'doc_date': item.get('date'),
        'link_url': item.get('url', ''),
    }, ensure_ascii=False)}\n```"

    try:
        result = await call_llm_json(prompt)
    except Exception:
        return None

    if result.get("decision") != "pass":
        return None

    score = result.get("score", 0)
    if isinstance(score, str):
        try:
            score = float(score)
        except ValueError:
            score = 0
    if score < _SCORE_THRESHOLD:
        return None

    return {
        "decision": "pass",
        "doc_date": result.get("doc_date", item.get("date")),
        "category": result.get("category", ""),
        "digest": result.get("digest", ""),
        "insight": result.get("insight", ""),
        "score": score,
        "score_reason": result.get("score_reason", ""),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_screener.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/screener.py \
       packages/engine/tests/test_news_screener.py
git commit -m "feat(news): add screener with coarse batch + fine per-article"
```

---

## Task 7: explorer — LLM 探索 Agent

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/explorer.py`
- Test: `packages/engine/tests/test_news_explorer.py`

**Interfaces:**
- Consumes: `llm_client.call_llm_json`, `crawler.try_extract_items`, `crawler.try_extract_detail`, DOM 摘要 JS
- Produces:
  - `async def explore_list(page, source_name, base_url, db, max_retries) -> dict | None`
  - `async def explore_detail(page, url, max_retries) -> dict | None`

- [ ] **Step 1: 写失败测试**

```python
# packages/engine/tests/test_news_explorer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from engine.pipelines.news_collector.explorer import explore_list


class TestExploreList:
    @pytest.mark.asyncio
    async def test_explore_generates_config(self):
        """探索 Agent 成功生成 config 并验证"""
        generated_config = {
            "list": {"mode": "selectors", "fields": {
                "container": "ul.news", "item": "li", "title": "a",
                "link": "a", "link_attr": "href", "date": "span"
            }},
            "pagination": None,
            "detail": {"mode": "selectors", "fields": {
                "title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"
            }},
        }

        page = MagicMock()
        page.url = "https://example.com/news"
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock, return_value=generated_config), \
             patch("engine.pipelines.news_collector.explorer.try_extract_items",
                    new_callable=AsyncMock, return_value=[{"title": "test", "date": "2026-06-01", "url": "/1"}]):
            result = await explore_list(page, "测试源", "https://example.com", db, max_retries=3)
            assert result is not None
            assert result["list"]["mode"] == "selectors"

    @pytest.mark.asyncio
    async def test_explore_fails_after_retries(self):
        """探索 Agent 多次失败后返回 None"""
        page = MagicMock()
        page.url = "https://example.com/news"
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock, return_value={"list": {}, "pagination": None, "detail": {}}), \
             patch("engine.pipelines.news_collector.explorer.try_extract_items",
                    new_callable=AsyncMock, return_value=[]):
            result = await explore_list(page, "测试源", "https://example.com", db, max_retries=2)
            assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_explorer.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `explorer.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/explorer.py
"""探索 Agent：LLM 分析 DOM → 生成/修复 config（spec §7）"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .config_store import save_config, increment_explore_count
from .crawler import try_extract_items, try_extract_detail
from .llm_client import call_llm_json

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_EXPLORER_PROMPT = (_PROMPTS_DIR / "explorer.txt").read_text(encoding="utf-8")

# Config JSON schema 描述（注入到 prompt 中）
_CONFIG_JSON_SCHEMA = """
{
  "list": {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {container, item, title, date, link, link_attr}
      // script: {items: "JS代码，返回 [{title, date, url}, ...]"}
    }
  },
  "pagination": null | {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {next: "CSS选择器", next_text: "按钮文本"}
      // script: {next_url: "JS代码，返回下一页URL或null"}
    }
  },
  "detail": {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {title, content, date, source} — 均为 CSS 选择器
      // script: {title, content, date, source} — 均为 JS 代码
    }
  }
}
"""

# 通用 DOM 摘要 JS（与 dom_explorer.py 中的相同）
_DOM_SUMMARY_JS = r"""
() => {
    const NOISE_TAGS = new Set([
        'SCRIPT','STYLE','NOSCRIPT','SVG','CANVAS',
        'NAV','HEADER','FOOTER','IFRAME','EMBED','OBJECT'
    ]);
    const NOISE_KW = [
        'nav','menu','sidebar','footer','header','breadcrumb',
        'copyright','ad-','ads','banner','toolbar','cookie',
        'modal','popup','tooltip'
    ];
    function isNoise(el) {
        if (NOISE_TAGS.has(el.tagName)) return true;
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        const id = (el.id || '').toLowerCase();
        return NOISE_KW.some(kw => (cls + ' ' + id).includes(kw));
    }
    function summarize(el, depth, maxNodes) {
        if (!el || !el.tagName || depth > 6 || isNoise(el)) return null;
        try {
            const s = window.getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden') return null;
        } catch(e) {}
        const node = { t: el.tagName.toLowerCase() };
        if (el.id) node.id = el.id;
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim().replace(/\s+/g, ' ');
            if (cls) node.c = cls;
        }
        const firstLink = el.querySelector('a[href]');
        if (firstLink) {
            node.has_link = true;
            const href = firstLink.getAttribute('href') || '';
            if (href) node.link_sample = href.substring(0, 120);
        }
        const children = Array.from(el.children).filter(c => !isNoise(c));
        if (children.length === 0) {
            const text = (el.innerText || '').trim();
            if (text) node.txt = text.substring(0, 80);
        } else {
            node.n = children.length;
            if (depth < 6 && maxNodes.remaining > 0) {
                const ch = [];
                for (const child of children) {
                    if (maxNodes.remaining <= 0) break;
                    maxNodes.remaining--;
                    const s = summarize(child, depth + 1, maxNodes);
                    if (s) ch.push(s);
                }
                if (ch.length > 0) node.ch = ch;
            }
        }
        return node;
    }
    function findRepeating() {
        const out = [];
        const seen = new Set();
        for (const el of document.querySelectorAll('*')) {
            if (isNoise(el)) continue;
            const ch = Array.from(el.children).filter(c => !isNoise(c));
            if (ch.length < 3) continue;
            const groups = {};
            for (const c of ch) { (groups[c.tagName] = groups[c.tagName] || []).push(c); }
            const best = Object.entries(groups).sort((a,b) => b[1].length - a[1].length)[0];
            if (!best || best[1].length < 3) continue;
            const key = el.tagName + '|' + (el.className||'') + '|' + best[0];
            if (seen.has(key)) continue;
            seen.add(key);
            const withLinks = best[1].filter(c => c.querySelector('a[href]')).length;
            if (withLinks < 3) continue;
            out.push({
                container: { tag: el.tagName.toLowerCase(), id: el.id || undefined,
                    c: (typeof el.className === 'string' ? el.className.trim() : '') || undefined },
                groupSize: best[1].length, groupWithLinks: withLinks,
                samples: best[1].slice(0,3).map(c => {
                    const a = c.querySelector('a[href]');
                    return { tag: c.tagName.toLowerCase(),
                        text: (c.innerText||'').trim().substring(0,80),
                        link_href: a ? (a.getAttribute('href')||'').substring(0,120) : undefined };
                })
            });
        }
        return out.sort((a,b) => b.groupWithLinks - a.groupWithLinks).slice(0,5);
    }
    function findPagination() {
        const out = [];
        for (const el of document.querySelectorAll('a, button, [onclick]')) {
            const text = (el.innerText||'').trim();
            const href = el.getAttribute('href') || '';
            const onclick = el.getAttribute('onclick') || '';
            if (/\d/.test(text) || /[下><»]|next|prev|page/i.test(text) ||
                /page|index_/.test(href) || /page|goPage/i.test(onclick)) {
                out.push({ tag: el.tagName.toLowerCase(),
                    c: (typeof el.className === 'string' ? el.className.trim() : '') || undefined,
                    text: text.substring(0,40),
                    href: href ? href.substring(0,120) : undefined,
                    onclick: onclick ? onclick.substring(0,100) : undefined });
            }
        }
        return out.slice(0, 15);
    }
    const maxNodes = { remaining: 300 };
    return {
        url: location.href, title: document.title,
        body: summarize(document.body, 0, maxNodes),
        repeating_structures: findRepeating(),
        pagination_candidates: findPagination(),
    };
}
"""


async def explore_list(
    page: Page,
    source_name: str,
    base_url: str,
    db: Any,
    max_retries: int = 3,
) -> dict | None:
    """探索列表页 DOM → LLM 生成 config → 验证 → 存 DB。

    Returns: 可用的 config dict 或 None（失败）。
    """
    dom_summary = await page.evaluate(_DOM_SUMMARY_JS)
    dom_json = json.dumps(dom_summary, ensure_ascii=False, indent=2)

    repair_hint = ""
    for attempt in range(max_retries):
        prompt = _EXPLORER_PROMPT.replace("{url}", page.url)
        prompt = prompt.replace("{source_name}", source_name)
        prompt = prompt.replace("{page_type}", "list")
        prompt = prompt.replace("{config_json_schema}", _CONFIG_JSON_SCHEMA)
        prompt = prompt.replace("{repair_hint}", repair_hint)
        prompt += f"\n\n## DOM 结构摘要\n```json\n{dom_json}\n```"

        try:
            config = await call_llm_json(prompt)
        except Exception:
            repair_hint = f"\n## 上次尝试失败\nLLM 返回的内容无法解析为 JSON，请确保严格输出 JSON 格式。"
            continue

        # 验证：用生成的 config 在当前页面试跑
        list_config = config.get("list")
        if not list_config or not list_config.get("fields"):
            repair_hint = f"\n## 上次尝试失败\n生成的 config 缺少 list.fields，请确保输出完整的配置。"
            continue

        items = await try_extract_items(page, list_config)
        if items:
            # 成功 → 存 DB
            await save_config(db, source_name, base_url, config)
            await increment_explore_count(db, base_url)
            return config

        repair_hint = (
            f"\n## 上次尝试失败\n"
            f"你生成的配置提取结果为空（items 数量: {len(items)}）。\n"
            f"请重新分析 DOM 结构，修正选择器或 JS 代码。"
        )

    return None


async def explore_detail(
    page: Page,
    url: str,
    max_retries: int = 3,
) -> dict | None:
    """探索详情页 DOM → LLM 生成 detail config → 验证。

    Returns: 可用的 detail config dict 或 None。
    """
    dom_summary = await page.evaluate(_DOM_SUMMARY_JS)
    dom_json = json.dumps(dom_summary, ensure_ascii=False, indent=2)

    repair_hint = ""
    for attempt in range(max_retries):
        prompt = _EXPLORER_PROMPT.replace("{url}", url)
        prompt = prompt.replace("{source_name}", "")
        prompt = prompt.replace("{page_type}", "detail")
        prompt = prompt.replace("{config_json_schema}", _CONFIG_JSON_SCHEMA)
        prompt = prompt.replace("{repair_hint}", repair_hint)
        prompt += f"\n\n## DOM 结构摘要\n```json\n{dom_json}\n```"

        try:
            config = await call_llm_json(prompt)
        except Exception:
            repair_hint = "\n## 上次尝试失败\nLLM 返回无法解析为 JSON。"
            continue

        detail_config = config.get("detail") or config
        if not detail_config.get("fields"):
            repair_hint = "\n## 上次尝试失败\n缺少 detail.fields。"
            continue

        result = await try_extract_detail(page, detail_config)
        if result and result.get("content"):
            return detail_config

        repair_hint = (
            f"\n## 上次尝试失败\n"
            f"提取到的正文为空。请修正 content 选择器或 JS 代码。"
        )

    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_explorer.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/explorer.py \
       packages/engine/tests/test_news_explorer.py
git commit -m "feat(news): add explorer agent with DOM summary + LLM config generation"
```

---

## Task 8: collector.py — 主编排（7 Phase）

**Files:**
- Create: `packages/engine/src/engine/pipelines/news_collector/collector.py`
- Test: `packages/engine/tests/test_news_collector.py`

**Interfaces:**
- Consumes: config_schema, config_store, crawler, explorer, screener 全部模块
- Produces: `NewsCollectorPipeline` 类，注册为 `news.collector`

- [ ] **Step 1: 写失败测试**

```python
# packages/engine/tests/test_news_collector.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from engine.registry import PipelineRegistry


class TestNewsCollectorRegistration:
    def test_pipeline_registered(self):
        """Pipeline 自动注册"""
        # import 触发注册
        import engine.pipelines.news_collector.collector  # noqa
        p = PipelineRegistry.get("news.collector")
        assert p is not None
        assert p.metadata.display_name == "资讯采集"
        assert "cron" in p.metadata.trigger_modes
        assert "manual" in p.metadata.trigger_modes


class TestNewsCollectorExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        """execute() 返回 PipelineResult"""
        from engine.pipelines.news_collector.collector import NewsCollectorPipeline
        from engine.base import PipelineResult

        pipeline = NewsCollectorPipeline()
        ctx = MagicMock()
        ctx.logger = MagicMock()
        ctx.logger.step = AsyncMock()
        ctx.db = AsyncMock()
        ctx.db.execute = AsyncMock()
        ctx.db.commit = AsyncMock()
        ctx.execution_id = "test-123"

        config = {
            "sources": [{
                "name": "测试源",
                "base_url": "https://example.com",
                "entries": [{"name": "要闻", "url": "https://example.com/news"}],
            }],
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
        }

        # Mock 所有外部依赖
        with patch("engine.pipelines.news_collector.collector._run_pipeline",
                    new_callable=AsyncMock,
                    return_value=PipelineResult(success=True, summary={"total": 0})):
            result = await pipeline.execute(config, ctx)
            assert result.success is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/engine && uv run pytest tests/test_news_collector.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `collector.py`**

```python
# packages/engine/src/engine/pipelines/news_collector/collector.py
"""NewsCollectorPipeline — 7 Phase 主编排（spec §6）"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.parse import urljoin
from contextlib import asynccontextmanager

from playwright.async_api import Page, async_playwright
from sqlalchemy import text

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.registry import register_pipeline

from .config_schema import resolve_config
from .config_store import load_config, save_config, increment_explore_count
from .crawler import try_extract_items, go_next_page, try_extract_detail
from .explorer import explore_list, explore_detail
from .screener import coarse_screen, fine_screen

# ── 默认参数 ──
_DEFAULT_RATE_LIMIT_MS = 2000
_DEFAULT_SOURCE_SWITCH_MS = 5000
_DEFAULT_MAX_PAGES = 50
_DEFAULT_COARSE_BATCH = 20
_DEFAULT_FINE_CONCURRENCY = 3
_DEFAULT_EXPLORE_RETRIES = 3


@asynccontextmanager
async def _news_browser(config: dict):
    """浏览器生命周期 — 对齐 OA pipeline 模式。"""
    headless = config.get("headless", True)
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            yield page
        finally:
            close_task = asyncio.ensure_future(browser.close())
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
    finally:
        try:
            await pw.stop()
        except Exception:
            pass


async def _rate_limit(ms: int):
    """请求限速。"""
    await asyncio.sleep(ms / 1000)


async def _dedup_urls(db: Any, items: list[dict]) -> list[dict]:
    """URL 去重：内部去重 + DB 去重。"""
    # 内部去重
    seen = {}
    for it in items:
        url = it.get("url", "")
        if url and url not in seen:
            seen[url] = it
    unique = list(seen.values())

    if not unique:
        return []

    # DB 去重
    urls = [it["url"] for it in unique]
    # 分批查询（MySQL IN 限制）
    existing_urls = set()
    for i in range(0, len(urls), 500):
        batch = urls[i:i + 500]
        placeholders = ", ".join(f":u{j}" for j in range(len(batch)))
        params = {f"u{j}": u for j, u in enumerate(batch)}
        result = await db.execute(
            text(f"SELECT link_url FROM documents WHERE link_url IN ({placeholders})"),
            params,
        )
        for row in result.fetchall():
            existing_urls.add(row[0])

    return [it for it in unique if it["url"] not in existing_urls]


async def _insert_documents(db: Any, docs: list[dict]) -> int:
    """批量 INSERT IGNORE INTO documents。返回实际插入数。"""
    inserted = 0
    for doc in docs:
        try:
            await db.execute(
                text("INSERT IGNORE INTO documents "
                     "(category, title, content, digest, insight, "
                     "link_url, doc_date, website_name, score, score_reason) "
                     "VALUES (:category, :title, :content, :digest, :insight, "
                     ":link_url, :doc_date, :website_name, :score, :score_reason)"),
                doc,
            )
            inserted += 1
        except Exception:
            pass
    await db.commit()
    return inserted


async def _write_crawl_log(db: Any, execution_id: str, source_name: str,
                           entry_url: str, page_number: int, items_found: int,
                           status: str, error_message: str | None = None):
    """写入采集日志。"""
    try:
        await db.execute(
            text("INSERT INTO news_crawl_log "
                 "(execution_id, source_name, entry_url, page_number, "
                 "items_found, status, error_message) "
                 "VALUES (:eid, :sn, :eu, :pn, :found, :st, :err)"),
            {"eid": execution_id, "sn": source_name, "eu": entry_url,
             "pn": page_number, "found": items_found, "st": status,
             "err": error_message},
        )
        await db.commit()
    except Exception:
        pass


async def _run_pipeline(config: dict, ctx: ExecutionContext) -> PipelineResult:
    """7 Phase 主流程。"""
    stats = {
        "sources_total": 0,
        "entries_total": 0,
        "entries_skipped": 0,
        "items_crawled": 0,
        "items_after_dedup": 0,
        "items_coarse_pass": 0,
        "items_coarse_reject": 0,
        "items_fine_pass": 0,
        "items_fine_reject": 0,
        "items_inserted": 0,
        "explore_triggered": 0,
        "explore_success": 0,
        "explore_failed": 0,
        "categories": {},
    }

    sources = config.get("sources", [])
    start_date = config.get("start_date", "2026-01-01")
    end_date = config.get("end_date", "2026-12-31")
    preference = config.get("preference")
    rate_limit_ms = config.get("rate_limit_ms", _DEFAULT_RATE_LIMIT_MS)
    source_switch_ms = config.get("source_switch_delay_ms", _DEFAULT_SOURCE_SWITCH_MS)
    max_pages = config.get("max_pages", _DEFAULT_MAX_PAGES)
    coarse_batch = config.get("coarse_batch_size", _DEFAULT_COARSE_BATCH)
    fine_concurrency = config.get("fine_concurrency", _DEFAULT_FINE_CONCURRENCY)
    explore_retries = config.get("explore_max_retries", _DEFAULT_EXPLORE_RETRIES)
    headless = config.get("headless", True)

    stats["sources_total"] = len(sources)

    # ── Phase 1 & 2: 信源遍历 + 翻页采集 ──
    all_items = []

    async with _news_browser({"headless": headless}) as page:
        for src_idx, source in enumerate(sources):
            source_name = source.get("name", "未知信源")
            base_url = source.get("base_url", "")
            entries = source.get("entries", [])

            await ctx.logger.step("phase1", f"信源: {source_name} ({len(entries)} 个入口)")

            # 加载 DB config
            db_config = await load_config(ctx.db, base_url)

            for entry_idx, entry in enumerate(entries):
                entry_name = entry.get("name", f"entry_{entry_idx}")
                entry_url = entry.get("url", "")
                stats["entries_total"] += 1

                await ctx.logger.step("phase1", f"  入口: {entry_name}")

                # 解析 config（信源级 + entry 级覆盖）
                if db_config:
                    resolved = resolve_config(db_config, entry)
                else:
                    resolved = None

                # 打开页面
                try:
                    await page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(3)
                except Exception as e:
                    await ctx.logger.error("phase1", f"  页面加载失败: {e}")
                    await _write_crawl_log(ctx.db, ctx.execution_id, source_name,
                                           entry_url, 0, 0, "error", str(e))
                    stats["entries_skipped"] += 1
                    continue

                # Phase 1: Config 解析 / 探索
                list_config = resolved["list"] if resolved else None
                pagination_config = resolved.get("pagination") if resolved else None
                detail_config = resolved.get("detail") if resolved else None

                items = []
                if list_config:
                    items = await try_extract_items(page, list_config)

                # Config 缺失或失效 → 探索 Agent
                if not items:
                    stats["explore_triggered"] += 1
                    await ctx.logger.step("explorer", f"  触发探索 Agent: {entry_name}")
                    new_config = await explore_list(
                        page, source_name, base_url, ctx.db, explore_retries)
                    if new_config:
                        stats["explore_success"] += 1
                        entry_resolved = resolve_config(
                            {"configs": new_config, "entries": []}, entry)
                        list_config = entry_resolved["list"]
                        pagination_config = entry_resolved.get("pagination")
                        detail_config = entry_resolved.get("detail")
                        items = await try_extract_items(page, list_config)
                    else:
                        stats["explore_failed"] += 1
                        await ctx.logger.error("explorer", f"  探索失败，跳过: {entry_name}")
                        await _write_crawl_log(ctx.db, ctx.execution_id, source_name,
                                               entry_url, 0, 0, "skipped", "探索Agent失败")
                        stats["entries_skipped"] += 1
                        continue

                # Phase 2: 翻页采集
                page_items = list(items)
                for page_num in range(1, max_pages):
                    await _rate_limit(rate_limit_ms)

                    # 日期过滤：检查是否所有 items 都早于 start_date
                    dates = [it.get("date") for it in page_items if it.get("date")]
                    if dates and all(d < start_date for d in dates):
                        break

                    # 翻页
                    if not await go_next_page(page, pagination_config):
                        break

                    await ctx.logger.step("phase2", f"  翻页: {entry_name} 第{page_num + 1}页")

                    new_items = await try_extract_items(page, list_config)
                    if not new_items:
                        break

                    page_items.extend(new_items)

                    await _write_crawl_log(ctx.db, ctx.execution_id, source_name,
                                           entry_url, page_num, len(new_items), "ok")

                # 日期范围过滤
                for it in page_items:
                    d = it.get("date")
                    if d and (d < start_date or d > end_date):
                        continue
                    it["source_name"] = source_name
                    it["detail_config"] = detail_config
                    all_items.append(it)

                stats["items_crawled"] += len(page_items)
                await ctx.logger.step("phase2",
                    f"  {entry_name}: 采集 {len(page_items)} 条")

            # 信源间延迟
            if src_idx < len(sources) - 1:
                await asyncio.sleep(source_switch_ms / 1000)

        # ── Phase 3: URL 去重 ──
        await ctx.logger.step("phase3", f"URL 去重: {len(all_items)} → ...")
        all_items = await _dedup_urls(ctx.db, all_items)
        stats["items_after_dedup"] = len(all_items)
        await ctx.logger.step("phase3", f"去重后: {len(all_items)} 条")

        # ── Phase 4: 粗筛 ──
        await ctx.logger.step("phase4", f"粗筛: {len(all_items)} 条...")
        passed_items = await coarse_screen(
            all_items, start_date, end_date, preference, coarse_batch)
        stats["items_coarse_pass"] = len(passed_items)
        stats["items_coarse_reject"] = len(all_items) - len(passed_items)
        await ctx.logger.step("phase4",
            f"粗筛: pass={len(passed_items)}, reject={stats['items_coarse_reject']}")

        # ── Phase 5: 正文提取 ──
        await ctx.logger.step("phase5", f"正文提取: {len(passed_items)} 条...")
        for i, it in enumerate(passed_items):
            url = it.get("url", "")
            if not url.startswith("http"):
                continue

            await _rate_limit(rate_limit_ms)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(2)
            except Exception:
                continue

            detail_cfg = it.get("detail_config")
            detail = await try_extract_detail(page, detail_cfg)

            if not detail or not detail.get("content"):
                # 探索 Agent detail 模式
                detail_cfg_new = await explore_detail(page, url, explore_retries)
                if detail_cfg_new:
                    detail = await try_extract_detail(page, detail_cfg_new)

            if detail:
                it["content"] = detail.get("content", "")
                it["detail_title"] = detail.get("title", it.get("title", ""))
                if detail.get("date"):
                    it["date"] = detail["date"]
                it["source_text"] = detail.get("source", "")

        # 过滤掉没有正文的
        with_content = [it for it in passed_items if it.get("content")]
        await ctx.logger.step("phase5",
            f"正文提取完成: {len(with_content)}/{len(passed_items)}")

        # ── Phase 6: 细筛 ──
        await ctx.logger.step("phase6", f"细筛: {len(with_content)} 条...")
        sem = asyncio.Semaphore(fine_concurrency)

        async def _fine_one(it):
            async with sem:
                return await fine_screen(it, start_date, end_date)

        fine_tasks = [_fine_one(it) for it in with_content]
        fine_results = await asyncio.gather(*fine_tasks, return_exceptions=True)

        docs_to_insert = []
        for it, result in zip(with_content, fine_results):
            if isinstance(result, Exception) or result is None:
                stats["items_fine_reject"] += 1
                continue
            stats["items_fine_pass"] += 1
            cat = result.get("category", "未知")
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
            docs_to_insert.append({
                "category": cat,
                "title": it.get("detail_title", it.get("title", "")),
                "content": it.get("content", ""),
                "digest": result.get("digest", ""),
                "insight": result.get("insight", ""),
                "link_url": it.get("url", ""),
                "doc_date": result.get("doc_date", it.get("date", start_date)),
                "website_name": it.get("source_name", ""),
                "score": result.get("score"),
                "score_reason": result.get("score_reason", ""),
            })

        await ctx.logger.step("phase6",
            f"细筛: pass={stats['items_fine_pass']}, reject={stats['items_fine_reject']}")

    # ── Phase 7: 入库 + 统计 ──（浏览器已关闭）
    await ctx.logger.step("phase7", f"入库: {len(docs_to_insert)} 条...")
    inserted = await _insert_documents(ctx.db, docs_to_insert)
    stats["items_inserted"] = inserted
    await ctx.logger.step("phase7", f"入库完成: {inserted} 条")

    return PipelineResult(success=True, summary=stats)


@register_pipeline(
    name="news.collector",
    display_name="资讯采集",
    description="采集白名单信源的资讯列表，经粗筛/细筛后入素材库",
    trigger_modes=["cron", "api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            "sources": {
                "type": "array",
                "description": "信源列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "信源名称"},
                        "base_url": {"type": "string", "description": "信源根域名"},
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "preference": {"type": "string", "description": "查询偏好（可选）"},
            "headless": {"type": "boolean", "default": True, "description": "无头模式"},
            "max_pages": {"type": "integer", "default": 50},
            "coarse_batch_size": {"type": "integer", "default": 20},
            "fine_concurrency": {"type": "integer", "default": 3},
            "explore_max_retries": {"type": "integer", "default": 3},
            "rate_limit_ms": {"type": "integer", "default": 2000},
            "source_switch_delay_ms": {"type": "integer", "default": 5000},
        },
        "required": ["sources", "start_date", "end_date"],
    },
)
class NewsCollectorPipeline(BasePipeline):
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        config.setdefault("headless", True)
        config.setdefault("max_pages", _DEFAULT_MAX_PAGES)
        config.setdefault("coarse_batch_size", _DEFAULT_COARSE_BATCH)
        config.setdefault("fine_concurrency", _DEFAULT_FINE_CONCURRENCY)
        config.setdefault("explore_max_retries", _DEFAULT_EXPLORE_RETRIES)
        config.setdefault("rate_limit_ms", _DEFAULT_RATE_LIMIT_MS)
        config.setdefault("source_switch_delay_ms", _DEFAULT_SOURCE_SWITCH_MS)

        try:
            return await _run_pipeline(config, ctx)
        except Exception as e:
            await ctx.logger.error("execute", f"Pipeline 异常: {e}")
            return PipelineResult(success=False, error=str(e))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/engine && uv run pytest tests/test_news_collector.py -v`
Expected: 2 passed

- [ ] **Step 5: 运行全量测试**

Run: `cd packages/engine && uv run pytest -v`
Expected: 全部通过，无回归

- [ ] **Step 6: Commit**

```bash
git add packages/engine/src/engine/pipelines/news_collector/collector.py \
       packages/engine/tests/test_news_collector.py
git commit -m "feat(news): add NewsCollectorPipeline with 7-phase orchestration"
```

---

## Task 9: 端到端验证

**Files:** 无新文件，手动验证

- [ ] **Step 1: 确认 Pipeline 自动发现**

```python
# 在 Python REPL 中验证
from engine.registry import PipelineRegistry
PipelineRegistry.discover()
p = PipelineRegistry.get("news.collector")
print(p.metadata.name)          # news.collector
print(p.metadata.display_name)  # 资讯采集
print(p.metadata.trigger_modes) # ['cron', 'api', 'manual']
```

- [ ] **Step 2: 执行 DDL 创建数据库表**

在 MySQL 中执行 Task 1 Step 1 的 SQL。

- [ ] **Step 3: 设置 LLM 环境变量**

```bash
export LLM_API_KEY="your-api-key"
export LLM_MODEL="gpt-4o"  # 或其他模型
# export LLM_BASE_URL="..."  # 如使用代理
```

- [ ] **Step 4: 手动触发一次采集**

通过 backend API 或直接 Python 脚本，用最小 config 触发：

```python
import asyncio
from unittest.mock import MagicMock
from engine.context import ExecutionContext
from engine.logger import StepLogger
from engine.registry import PipelineRegistry
PipelineRegistry.discover()

async def main():
    pipeline_cls = PipelineRegistry.get("news.collector")
    pipeline = pipeline_cls()
    ctx = ExecutionContext(
        logger=StepLogger("manual-test"),
        db=...,  # 实际 AsyncSession
        minio=None,
        settings=None,
        execution_id="manual-test-001",
    )
    result = await pipeline.execute({
        "sources": [{
            "name": "中国政府网",
            "base_url": "https://www.gov.cn",
            "entries": [{"name": "要闻列表", "url": "https://www.gov.cn/yaowen/liebiao/"}],
        }],
        "start_date": "2026-07-01",
        "end_date": "2026-07-25",
        "headless": False,
        "max_pages": 3,
    }, ctx)
    print(result.success)
    print(result.summary)

asyncio.run(main())
```

- [ ] **Step 5: 检查 documents 表**

```sql
SELECT category, COUNT(*), AVG(score)
FROM documents
GROUP BY category
ORDER BY COUNT(*) DESC;
```

- [ ] **Step 6: 最终 Commit**

```bash
git add -A
git commit -m "feat(news): end-to-end verification complete"
```
