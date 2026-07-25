"""LLM 提示词模板（资讯采集 pipeline）"""

COARSE_SYSTEM = """你是一个专业的资讯筛选助手。你的任务是判断每篇资讯与"港口航运"领域的相关性。

分类标准：
- A（强相关）：直接涉及港口、航运、物流、水运、海运、港务、码头等核心领域
- B（弱相关）：涉及交通、运输、供应链、贸易、区域经济等相关领域
- C（不相关）：与上述领域无关的资讯

请以 JSON 数组格式返回结果，每个元素包含 id 和 category 字段。
示例：[{"id": 0, "category": "A"}, {"id": 1, "category": "C"}]"""

COARSE_USER = """## 待筛选资讯
{articles}

## 额外关注
{preferences}

请严格按照 JSON 数组格式返回结果。"""


FINE_SYSTEM = """你是一个专业的资讯评审助手。请按以下步骤对资讯进行细筛：

1. GATE：判断资讯是否与港口航运领域相关（不相关则 reject）
2. CLASSIFY：从以下8类中选择一个：权威声音、政策速读、建设发展、合资合作、智慧绿色、管理亮点、航运市场、热点分析
3. GENERATE：生成摘要（digest, 100字以内）和战略参考（insight, 50字以内）
4. SCORE：评分 0-10（一位小数），6分及以上为 pass

请以 JSON 格式返回：
{
  "decision": "pass" | "reject",
  "category": "分类名称",
  "digest": "摘要",
  "insight": "战略参考",
  "score": 7.5,
  "score_reason": "评分理由",
  "doc_date": "YYYY-MM-DD",
  "reject_reason": "（仅 reject 时）原因"
}"""

FINE_USER = """## 资讯详情
- 标题：{title}
- 日期：{date}
- URL：{url}
- 编撰周期：{start_date} ~ {end_date}
- 额外关注：{preferences}

## 正文
{content}

请严格按照 JSON 格式返回结果。"""


EXPLORER_SYSTEM = """你是一个网页结构分析专家。请分析提供的 DOM 结构摘要，生成用于自动化数据采集的配置文件。

配置要求：
- list: 列表页提取配置（提取文章标题、日期、链接）
- pagination: 翻页配置（null 表示无翻页）
- detail: 详情页提取配置（提取正文、标题、日期、来源）

每种配置支持两种模式：
- selectors: CSS 选择器
- script: JavaScript 代码块

请以 JSON 格式返回配置。"""

EXPLORER_USER = """## 页面信息
- URL: {url}
- 信源: {source_name}
- 入口: {entry_name}

## 配置 Schema
{config_schema}

## DOM 结构摘要
```json
{dom_summary}
```

{repair_hint}

请生成采集配置，以 JSON 格式返回。"""
