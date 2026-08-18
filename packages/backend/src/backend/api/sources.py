"""信源管理只读 API — 从 engine 的 sources.json 读取信源 + entry 展示数据。

返回结构信息（字段名集合、变体数、分页、自定义 entry 计数），
不暴露 configs 中的 CSS 选择器值（spec 4 §2.7 / spec 6 §7）。
"""
import json
from pathlib import Path

import engine.pipelines.port_maritime_info.harvest as _harvest
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/sources", tags=["sources"])

# 从 engine 包定位 sources.json（dev/workspace/Docker 均适用，与 harvest.py 同一路径）
_SOURCES_FILE = Path(_harvest.__file__).parent / "sources.json"


class SourceEntryOut(BaseModel):
    entry_name: str
    url: str
    has_override: bool


class SourceOut(BaseModel):
    source_name: str
    base_url: str
    entry_count: int
    entries: list[SourceEntryOut]
    list_fields: list[str]
    detail_fields: list[str]
    detail_variant_count: int
    has_pagination: bool
    entries_with_override: int


@router.get("", response_model=list[SourceOut])
async def list_sources():
    """返回全部信源及其 entry（只读，含采集结构信息，不含 configs 选择器值）。"""
    data = json.loads(_SOURCES_FILE.read_text(encoding="utf-8"))
    result = []
    for s in data.get("sources", []):
        cfg = s.get("configs", {})
        list_fields = list(cfg.get("list", {}).get("fields", {}).keys())
        detail_cfgs = cfg.get("detail", [])
        detail_fields = (
            list(detail_cfgs[0].get("fields", {}).keys()) if detail_cfgs else []
        )
        entries_raw = s.get("entries", [])
        entries_with_override = sum(1 for e in entries_raw if e.get("list"))
        result.append(
            SourceOut(
                source_name=s["source_name"],
                base_url=s["base_url"],
                entry_count=len(entries_raw),
                entries=[
                    SourceEntryOut(
                        entry_name=e["entry_name"],
                        url=e["url"],
                        has_override=bool(e.get("list")),
                    )
                    for e in entries_raw
                ],
                list_fields=list_fields,
                detail_fields=detail_fields,
                detail_variant_count=len(detail_cfgs),
                has_pagination=bool(cfg.get("pagination")),
                entries_with_override=entries_with_override,
            )
        )
    return result
