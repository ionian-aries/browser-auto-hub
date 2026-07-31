"""LLM 筛选 — 粗筛批量门控 + 细筛单条判断。

- coarse_screen: 按标题批量 pass/reject，不打分、不分类
- fine_screen:   单条 GATE→CLASSIFY→GENERATE→SCORE，含必填字段校验重试
- load_fine_prompt: 加载细筛 prompt 并注入日期范围 + 偏好
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).parent / "prompts"

_PREF_BLOCK = "**用户额外关注**：{preference}"

# pass 结果必填字段（LLM 间歇性漏字段，缺任一即视为无效结果）
_REQUIRED_PASS_FIELDS = ("category", "digest", "insight", "score", "score_reason")


def _load_prompt(
    name: str,
    start_date: str,
    end_date: str,
    preference: str = "",
) -> str:
    """加载 prompt 模板并注入日期范围 + 偏好。"""
    template = (_PROMPT_DIR / name).read_text(encoding="utf-8")
    return (
        template
        .replace("{start_date}", start_date)
        .replace("{end_date}", end_date)
        .replace(
            "{preference}",
            _PREF_BLOCK.format(preference=preference) if preference else "",
        )
    )


def load_fine_prompt(
    start_date: str,
    end_date: str,
    preference: str = "",
) -> str:
    """加载细筛 prompt 并注入日期范围 + 偏好。"""
    return _load_prompt("news-fine.md", start_date, end_date, preference)


# ── 粗筛 ──
async def coarse_screen(
    items: list[dict],
    config: dict,
    start_date: str,
    end_date: str,
    preference: str,
    llm,
    log,
) -> list[dict]:
    """LLM 批量 pass/reject，返回通过的条目。不写入任何新字段。"""
    if not items:
        return []

    batch_size = config.get("coarse_batch_size", 20)
    model = config.get("coarse_model") or llm.setting("llm_coarse_model")
    system_prompt = _load_prompt("news-coarse.md", start_date, end_date, preference)

    # 入口校验: 过滤缺 title 的 item
    valid_items = [it for it in items if it.get("title")]
    skipped = len(items) - len(valid_items)
    if skipped:
        await log.warn("coarse", f"跳过 {skipped} 条缺 title 的条目")
    if not valid_items:
        return []

    # 分批
    batches: list[tuple[int, list[dict]]] = []
    for i in range(0, len(valid_items), batch_size):
        batch_num = i // batch_size + 1
        batches.append((batch_num, valid_items[i : i + batch_size]))
    total_batches = len(batches)
    # 批次并发但 LLM 请求数受上限约束（防 API 限流）
    llm_sem = asyncio.Semaphore(config.get("llm_concurrency", 5))

    async def _process_batch(
        batch_num: int, batch: list[dict],
    ) -> list[dict]:
        """处理单个批次，返回通过的条目。"""
        try:
            payload = {
                "items": [
                    {
                        "id": str(i),
                        "title": it.get("title", ""),
                        "doc_date": it.get("doc_date", ""),
                    }
                    for i, it in enumerate(batch)
                ]
            }
            async with llm_sem:
                data = await llm.ask_json(
                    system_prompt, json.dumps(payload, ensure_ascii=False),
                    model, log, label="粗筛",
                )
            pass_ids = {str(x) for x in data.get("pass_ids", [])}

            # 后验证: 检查 id 是否在预期范围内
            expected_ids = {str(i) for i in range(len(batch))}
            unexpected = pass_ids - expected_ids
            if unexpected:
                await log.warn(
                    "coarse", f"批次 {batch_num}: LLM 返回未知 id {unexpected}，忽略"
                )
                pass_ids &= expected_ids

            batch_passed = [
                it for i, it in enumerate(batch) if str(i) in pass_ids
            ]

            # 后验证: 全部 reject 时发出警告
            if not batch_passed and len(batch) > 0:
                await log.warn(
                    "coarse",
                    f"批次 {batch_num}/{total_batches}: 全部 {len(batch)} 条被 reject",
                )
            else:
                await log.info(
                    "coarse",
                    f"批次 {batch_num}/{total_batches}: "
                    f"{len(batch_passed)}/{len(batch)} 通过",
                    data={"pass_ids": sorted(pass_ids), "response": data},
                )
            return batch_passed

        except json.JSONDecodeError:
            await log.error(
                "coarse", f"批次 {batch_num}/{total_batches}: LLM 返回无效 JSON，跳过"
            )
            return []
        except Exception as e:
            await log.error(
                "coarse", f"批次 {batch_num}/{total_batches}: 调用失败 {e}，跳过"
            )
            return []

    # 所有批次并发执行
    results = await asyncio.gather(
        *[_process_batch(bn, b) for bn, b in batches]
    )
    passed = [it for batch_passed in results for it in batch_passed]

    await log.info("coarse", f"粗筛结果: {len(passed)}/{len(items)} 条通过")
    return passed


# ── 细筛 ──
async def fine_screen(
    item: dict,
    system_prompt: str,
    model: str,
    llm,
    log,
    validate_retries: int = 2,
) -> dict[str, Any]:
    """单条细筛: 构建 user message → LLM → 校验 → 返回结果 dict。

    pass 结果缺必填字段时重试 validate_retries 次，耗尽则抛异常
    （由调用方计 failed，残留行由 cleanup 清理，下次运行重采）。
    LLM 调用失败时抛出异常（由调用方处理重试/失败逻辑）。
    """
    user_msg = (
        f"标题: {item.get('title', '')}\n"
        f"日期: {item.get('doc_date', '')}\n"
        f"来源: {item.get('source', '')}\n\n"
        f"正文:\n{item.get('content', '')}"
    )
    missing: list[str] = []
    for attempt in range(validate_retries + 1):
        result = await llm.ask_json(system_prompt, user_msg, model, log, label="细筛")
        if result.get("decision") != "pass":
            return result
        missing = [
            f for f in _REQUIRED_PASS_FIELDS if result.get(f) in (None, "")
        ]
        if not missing:
            return result
        if attempt < validate_retries:
            await log.warn(
                "detail",
                f"细筛 pass 结果缺字段 {missing}，"
                f"重试 {attempt + 1}/{validate_retries}",
            )
    raise ValueError(f"细筛结果缺必填字段: {missing}（重试耗尽）")
