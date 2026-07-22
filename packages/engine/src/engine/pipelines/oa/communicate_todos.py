"""OA 沟通待办采集 Pipeline"""

import base64
import json
import re
import time

from playwright.async_api import Page, async_playwright

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.pipelines.oa.shared.login import LoginError, LoginTimeout, oa_login
from engine.registry import register_pipeline

_TITLE_LINK_SELECTOR = 'a.lui_notify_alink[href*="sysNotifyTodo"]'
_EMPTY_TEXT = "当前模块所有工作都已经处理完成"


@register_pipeline(
    name="oa.communicate_todos",
    display_name="OA 沟通待办采集",
    description="采集 OA 系统沟通待办列表，提取元数据与附件，写入 inbox_documents 表",
    trigger_modes=["cron", "api", "manual"],
    config_schema={
        "type": "object",
        "properties": {
            "login_url": {
                "type": "string",
                "default": "https://ioa.sd-port.net/login.jsp",
                "description": "OA 登录页地址",
            },
            "username": {"type": "string", "description": "OA 用户名"},
            "password": {"type": "string", "description": "OA 密码"},
            "page_load_timeout": {
                "type": "integer",
                "default": 15000,
                "description": "页面加载超时(ms)",
            },
            "element_visible_timeout": {
                "type": "integer",
                "default": 5000,
                "description": "元素可见超时(ms)",
            },
            "action_settle_timeout": {
                "type": "integer",
                "default": 500,
                "description": "操作后稳定等待(ms)",
            },
            "max_pages": {
                "type": "integer",
                "default": 100,
                "description": "最大采集页数（防止死循环）",
            },
        },
        "required": ["username", "password"],
    },
)
class OaCommunicateTodosPipeline(BasePipeline):
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        config.setdefault("login_url", "https://ioa.sd-port.net/login.jsp")
        config.setdefault("page_load_timeout", 15000)
        config.setdefault("element_visible_timeout", 5000)
        config.setdefault("action_settle_timeout", 500)
        config.setdefault("max_pages", 100)
        headless = config.get("headless", True)
        close_browser = config.get("close_browser", True)

        records: list[dict] = []
        stats = {"total": 0, "inserted": 0, "skipped": 0, "attachment_failures": 0}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            page = await browser.new_page()

            try:
                await ctx.logger.step("login", "登录 OA 系统")
                await oa_login(page, config)

                await ctx.logger.step("locate_list", "定位待办列表")
                frame = await self._find_list_frame(page, config)
                if frame is None:
                    await ctx.logger.step("locate_list", "未找到待办列表 iframe", level="error")
                    return PipelineResult(success=False, error="List iframe not found")

                content = await frame.content()
                if _EMPTY_TEXT in content:
                    await ctx.logger.step("crawl", "待办列表为空，无需采集")
                    return PipelineResult(success=True, summary=stats)

                # 加载已有 task_id 用于去重
                from sqlalchemy import text
                result = await ctx.db.execute(text("SELECT task_id FROM inbox_documents"))
                existing_ids = {row[0] for row in result.fetchall()}

                max_pages = config["max_pages"]
                page_num = 0
                while True:
                    page_num += 1
                    if page_num > max_pages:
                        await ctx.logger.step("crawl", f"已达最大页数限制 ({max_pages})，停止采集")
                        break
                    await ctx.logger.step("crawl", f"采集第 {page_num} 页")

                    links = frame.locator(_TITLE_LINK_SELECTOR)
                    count = await links.count()

                    for i in range(count):
                        record = await self._process_one(
                            frame, links, i, config, ctx, existing_ids, stats
                        )
                        if record:
                            records.append(record)

                    if not await self._has_next_page(frame):
                        break
                    await self._click_next_page(frame, config)

                if records:
                    await ctx.logger.step("save", f"写入数据库 {len(records)} 条")
                    await self._save_records(records, ctx)
                    stats["inserted"] = len(records)

                stats["total"] = stats["inserted"] + stats["skipped"]

            except (LoginError, LoginTimeout) as e:
                await ctx.logger.error("login", str(e))
                return PipelineResult(success=False, error=str(e))
            except Exception as e:
                await ctx.logger.error("crawl", f"Unexpected error: {e}")
                return PipelineResult(success=False, error=str(e))
            finally:
                if close_browser:
                    await browser.close()

        return PipelineResult(success=True, summary=stats)

    async def _find_list_frame(self, page: Page, config: dict):
        """定位 portal_qdport.jsp iframe"""
        timeout = config["page_load_timeout"]
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            for frame in page.frames:
                if "portal_qdport.jsp" in (frame.url or ""):
                    try:
                        await frame.wait_for_selector(
                            f"{_TITLE_LINK_SELECTOR}, :text('{_EMPTY_TEXT}')",
                            timeout=5000,
                        )
                        return frame
                    except Exception:
                        pass
            await page.wait_for_timeout(500)
        return None

    async def _process_one(self, frame, links, index, config, ctx, existing_ids, stats):
        """打开详情页提取元数据，返回 record dict 或 None"""
        page = frame.page
        async with page.context.expect_page() as new_page_info:
            await links.nth(index).click()
        detail_page = await new_page_info.value
        await detail_page.wait_for_load_state("domcontentloaded")

        try:
            url = detail_page.url
            match = re.search(r"fdId=([a-f0-9]+)", url)
            task_id = match.group(1) if match else ""

            if not task_id:
                stats["skipped"] += 1
                return None

            if task_id in existing_ids:
                stats["skipped"] += 1
                return None

            record = await self._extract_meta(detail_page, task_id, config, ctx, stats)
            existing_ids.add(task_id)
            return record
        finally:
            await detail_page.close()

    async def _extract_meta(self, page: Page, task_id: str, config, ctx, stats) -> dict:
        """提取详情页全部元数据"""
        title = await page.title()
        title = re.sub(r"\s*-\s*工作沟通$", "", title)

        creator = ""
        try:
            creator_el = page.locator("a.com_author")
            if await creator_el.count() > 0:
                creator = (await creator_el.first.inner_text()).strip()
        except Exception:
            pass

        base_info = ""
        try:
            base_el = page.locator(".baseInfo")
            if await base_el.count() > 0:
                base_info = await base_el.first.inner_text()
        except Exception:
            pass

        send_time = ""
        time_match = re.search(r"发表于\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", base_info)
        if time_match:
            send_time = time_match.group(1)

        participants = self._extract_names(base_info, "接收者")
        cc_recipients = self._extract_names(base_info, "抄送人")

        summary = ""
        try:
            body_el = page.locator(".cheditor_view")
            if await body_el.count() > 0:
                summary = await body_el.first.inner_text()
        except Exception:
            pass

        attachment_urls = await self._download_attachments(page, task_id, config, ctx, stats)

        return {
            "task_id": task_id,
            "creator": creator,
            "send_time": send_time,
            "title": title,
            "participants": participants,
            "cc_recipients": cc_recipients,
            "summary": summary,
            "attachment_urls": json.dumps(attachment_urls, ensure_ascii=False),
        }

    def _extract_names(self, text: str, label: str) -> str:
        """提取标签后的逗号分隔姓名列表"""
        pattern = rf"{label}[:：]\s*(.+?)(?:\n|$)"
        match = re.search(pattern, text)
        if not match:
            return ""
        raw = match.group(1).strip()
        names = re.split(r"[,，、]", raw)
        return ",".join(n.strip() for n in names if n.strip())

    async def _download_attachments(self, page, task_id, config, ctx, stats) -> list[dict]:
        """通过页面内 fetch 下载附件并上传 MinIO"""
        content = await page.content()
        attach_match = re.search(r"文档附件\((\d+)\)", content)
        if not attach_match or int(attach_match.group(1)) == 0:
            return []

        attachments = []
        timeout = config["page_load_timeout"]

        try:
            await page.wait_for_selector(
                ".work_comm_Content .upload_list_tr_view",
                timeout=timeout,
            )
        except Exception:
            return []

        rows = page.locator(".work_comm_Content .upload_list_tr_view")
        count = await rows.count()

        for i in range(count):
            row = rows.nth(i)
            fd_id = await row.get_attribute("id") or ""
            filename_el = row.locator(".upload_list_filename_view[title]")
            filename = ""
            if await filename_el.count() > 0:
                filename = await filename_el.first.get_attribute("title") or ""

            if not fd_id or not filename:
                continue

            try:
                b64_data = await page.evaluate(
                    """async (fdId) => {
                        const resp = await fetch(
                            `/sys/attachment/sys_att_main/sysAttMain.do?method=download&fdId=${fdId}`,
                            {credentials: 'include'}
                        );
                        const buf = await resp.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let binary = '';
                        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                        return btoa(binary);
                    }""",
                    fd_id,
                )

                file_bytes = base64.b64decode(b64_data)
                object_key = f"{ctx.settings.minio_object_prefix}/attachments/{task_id}/{filename}"
                ctx.minio.upload(object_key, file_bytes)
                presign = ctx.minio.presign_url(object_key)
                attachments.append({"filename": filename, "object_key": object_key, "url": presign, "ok": True})
            except Exception as e:
                stats["attachment_failures"] += 1
                attachments.append({"filename": filename, "url": "", "ok": False, "error": str(e)})

        return attachments

    async def _has_next_page(self, frame) -> bool:
        """判断是否有下一页（当前页/总页数）"""
        result = await frame.evaluate("""() => {
            const texts = document.body.innerText;
            const match = texts.match(/(\\d+)\\/(\\d+)/);
            if (!match) return false;
            return parseInt(match[1]) < parseInt(match[2]);
        }""")
        return bool(result)

    async def _click_next_page(self, frame, config):
        await frame.evaluate("""() => {
            const pager = document.querySelector('.lui_paging_mini, .lui_paging');
            if (!pager) return;
            const tds = pager.querySelectorAll('td');
            for (let i = 0; i < tds.length; i++) {
                if (tds[i].classList.contains('lui_paging_cur') || tds[i].querySelector('.lui_paging_cur')) {
                    const next = tds[i+1];
                    if (next) { const a = next.querySelector('a'); if (a) a.click(); }
                    break;
                }
            }
        }""")
        await frame.page.wait_for_timeout(config["action_settle_timeout"])

    async def _save_records(self, records: list[dict], ctx: ExecutionContext):
        """批量写入 inbox_documents（raw SQL，engine 不可导入 backend models）"""
        import uuid

        from sqlalchemy import text

        insert_sql = text("""
            INSERT INTO inbox_documents (id, task_id, creator, send_time, title, participants, cc_recipients, summary, attachment_urls)
            VALUES (:id, :task_id, :creator, :send_time, :title, :participants, :cc_recipients, :summary, :attachment_urls)
        """)

        for record in records:
            await ctx.db.execute(insert_sql, {
                "id": str(uuid.uuid4()),
                "task_id": record["task_id"],
                "creator": record.get("creator", ""),
                "send_time": record.get("send_time", ""),
                "title": record["title"],
                "participants": record.get("participants", ""),
                "cc_recipients": record.get("cc_recipients", ""),
                "summary": record.get("summary", ""),
                "attachment_urls": record.get("attachment_urls", "[]"),
            })

        await ctx.db.flush()
