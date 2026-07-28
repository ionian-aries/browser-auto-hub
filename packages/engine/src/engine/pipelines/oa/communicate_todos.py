"""OA 沟通待办采集 Pipeline

采集流程（spec 3 2026-07-24 修订三/四）：
1. 主扫描：列表页从标题链接 href 提取通知 ID 预过滤（本轮内不重复收集；
   跨轮去重无效——通知 ID ≠ DB 中的文档 ID），未知条目记录 {task_id, href}；
2. 详情：goto(href) 直达，免疫「新消息置顶」导致的列表位移；task_id 一律取
   落地 URL 中的文档 ID（OA 会将通知页重定向到文档页），权威去重在此完成；
   concurrency（默认 1）控制同 context 并行标签页数（Semaphore 限流）；
3. 复核：详情采集后重载列表完整重扫，有新条目则继续，最多 max_verify_rounds
   轮熔断（默认 2），仍有流入则留待下次调度自愈。
"""

import asyncio
import base64
import json
import re
import time
from urllib.parse import quote, urljoin

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.pipelines.oa.shared.login import LoginError, LoginTimeout, oa_login
from engine.pipelines.oa.shared.browser import oa_browser
from engine.registry import register_pipeline
from engine.table_names import resolve_table

_INBOX_TABLE = resolve_table("inbox_documents", "inbox_documents")

_TITLE_LINK_SELECTOR = 'a.lui_notify_alink[href*="sysNotifyTodo"]'
_EMPTY_TEXT = "当前模块所有工作都已经处理完成"
# 复核轮次上限默认值：新消息流入速度超过扫描速度时熔断，剩余由下次调度自愈
_MAX_VERIFY_ROUNDS = 2


@register_pipeline(
    name="oa.communicate_todos",
    display_name="OA 沟通待办采集",
    description="采集 OA 系统沟通待办列表，提取元数据与附件，写入 inbox_documents 表",
    trigger_modes=["cron", "api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "OA 用户名"},
            "password": {"type": "string", "format": "password", "description": "OA 密码"},
            "login_url": {
                "type": "string",
                "default": "https://ioa.sd-port.net/login.jsp",
                "description": "OA 登录页地址",
            },
            "max_pages": {
                "type": "integer",
                "default": 100,
                "description": "最大采集页数（防止死循环）",
            },
            "max_verify_rounds": {
                "type": "integer",
                "default": 2,
                "description": "详情采集后列表级复核的最大轮数（抓采集期间新进消息；熔断防死循环）",
            },
            "concurrency": {
                "type": "integer",
                "default": 1,
                "description": "详情页并发采集数（同一 context 内并行标签页上限；调大需评估 OA 限流）",
            },
            "attachment_download_timeout": {
                "type": "integer",
                "default": 300000,
                "description": "单个附件下载总超时（毫秒，含连接与完整传输）。大附件慢链路需留足时间",
            },
        },
        "required": ["username", "password"],
    },
)
class OaCommunicateTodosPipeline(BasePipeline):
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        config.setdefault("login_url", "https://ioa.sd-port.net/login.jsp")
        # 运行设置类参数由 runner 三级覆盖链注入（系统设置打底）；setdefault 仅作直连兜底
        config.setdefault("page_load_timeout", 15000)
        config.setdefault("element_visible_timeout", 5000)
        config.setdefault("action_settle_timeout", 500)
        config.setdefault("max_pages", 100)
        config.setdefault("max_verify_rounds", _MAX_VERIFY_ROUNDS)
        config.setdefault("concurrency", 1)
        config.setdefault("attachment_download_timeout", 300000)

        records: list[dict] = []
        stats = {
            "total": 0,
            "inserted": 0,
            "skipped": 0,
            "attachment_failures": 0,
            "extract_failures": 0,
        }

        async with oa_browser(config) as page:
            try:
                await ctx.logger.step("login", "登录 OA 系统")
                await oa_login(page, config)
                await ctx.logger.step("login", "登录成功，已进入门户页")

                await ctx.logger.step("locate_list", "定位待办列表")
                frame = await self._find_list_frame(page, config)
                if frame is None:
                    await ctx.logger.step("locate_list", "未找到待办列表 iframe", level="error")
                    return PipelineResult(success=False, error="List iframe not found")
                await ctx.logger.step("locate_list", "找到待办列表 iframe")

                content = await frame.content()
                if _EMPTY_TEXT in content:
                    await ctx.logger.step("crawl", "待办列表为空，无需采集")
                    return PipelineResult(success=True, summary=stats)

                # 加载已有 task_id 用于去重
                from sqlalchemy import text
                result = await ctx.db.execute(text(f"SELECT task_id FROM {_INBOX_TABLE}"))
                existing_ids = {row[0] for row in result.fetchall()}
                await ctx.logger.step("load_existing", f"加载已有记录 {len(existing_ids)} 条用于去重")

                total_count = await self._get_total_count(frame)
                if total_count is not None:
                    await ctx.logger.step("crawl", f"待办总数：共 {total_count} 条")

                # 主扫描：列表级通知 ID 预过滤（减少详情页打开次数），权威去重在 _open_detail
                pending = await self._scan_all_pages(
                    frame, config, ctx, existing_ids, stats, count_skips=True
                )

                # 详情采集 + 复核熔断：复核发现新条目则继续，最多 max_verify_rounds 轮
                verify_round = 0
                max_verify_rounds = config["max_verify_rounds"]
                # Semaphore 限流并行标签页；Lock 串行共享状态访问——步骤日志写库
                # 与写记录共用同一 AsyncSession（不可并发），existing_ids 延迟去重的
                # check-then-add 跨 await 有竞态（spec 3 2026-07-24 修订四）
                semaphore = asyncio.Semaphore(max(1, config["concurrency"]))
                shared_lock = asyncio.Lock()
                while True:
                    results = await asyncio.gather(*(
                        self._open_detail(
                            page, item, config, ctx, stats, existing_ids,
                            semaphore, shared_lock,
                        )
                        for item in pending
                    ))
                    records.extend(r for r in results if r)

                    if verify_round >= max_verify_rounds:
                        if pending:
                            await ctx.logger.step(
                                "verify",
                                f"复核已达 {max_verify_rounds} 轮上限，本轮仍有新消息流入，"
                                "如有遗漏将由下次调度补采",
                                level="warn",
                            )
                        break

                    verify_round += 1
                    await ctx.logger.step(
                        "verify", f"第 {verify_round} 轮复核：重载列表检查新进消息"
                    )
                    # 重载回第 1 页；frame 引用随页面失效，需重新定位
                    await page.reload(wait_until="domcontentloaded")
                    frame = await self._find_list_frame(page, config)
                    if frame is None:
                        await ctx.logger.step(
                            "verify", "复核时未找到列表 iframe，结束复核", level="warn"
                        )
                        break
                    pending = await self._scan_all_pages(
                        frame, config, ctx, existing_ids, stats, count_skips=False
                    )
                    if not pending:
                        await ctx.logger.step("verify", "复核无新条目，列表已稳定")
                        break
                    await ctx.logger.step(
                        "verify", f"复核发现 {len(pending)} 条新条目，继续采集"
                    )

                if records:
                    # 日志必须在写库成功之后——先记日志后写库会在写库失败时留下
                    # 「已写入」的假成功记录（2026-07-24 fwd 无默认值事件的教训）
                    await self._save_records(records, ctx)
                    stats["inserted"] = len(records)
                    await ctx.logger.step("save", f"写入数据库 {len(records)} 条")

                stats["total"] = stats["inserted"] + stats["skipped"]
                await ctx.logger.step(
                    "summary",
                    f"采集完成：新增 {stats['inserted']} 条，跳过 {stats['skipped']} 条，"
                    f"详情失败 {stats['extract_failures']} 条，"
                    f"附件失败 {stats['attachment_failures']} 个",
                )

            except (LoginError, LoginTimeout) as e:
                await ctx.logger.error("login", str(e))
                return PipelineResult(success=False, error=str(e))
            except Exception as e:
                await ctx.logger.error("crawl", f"Unexpected error: {e}")
                return PipelineResult(success=False, error=str(e))

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

    @staticmethod
    def _extract_fd_id(text: str) -> str | None:
        """从 href/URL 中提取 fdId（task_id），无则返回 None。"""
        match = re.search(r"fdId=([a-f0-9]+)", text or "")
        return match.group(1) if match else None

    async def _scan_all_pages(
        self, frame, config, ctx, existing_ids, stats, count_skips
    ) -> list[dict]:
        """列表级全量扫描：逐页读取标题链接 href 提取 fdId 去重（不开详情页）。

        注意：列表 href 中的 fdId 是通知记录 ID，非文档 ID（两者不同）。
        此处去重仅防止同一通知在本轮扫描中被重复收集；权威去重在 _open_detail
        中基于详情页落地 URL 的文档 ID 完成。

        返回未知条目 [{task_id, href}]；href 无 fdId 的个别条目 task_id 置 None，
        延迟到详情页 URL 判定。count_skips=False（复核轮）时不重复累计 skipped。
        """
        pending: list[dict] = []
        max_pages = config["max_pages"]
        page_num = 0
        unchanged_streak = 0
        while True:
            page_num += 1
            if page_num > max_pages:
                await ctx.logger.step(
                    "crawl",
                    f"已达最大页数限制 ({max_pages})，停止扫描",
                    level="warn",
                )
                break

            links = frame.locator(_TITLE_LINK_SELECTOR)
            count = await links.count()
            new_on_page = 0
            for i in range(count):
                href = await links.nth(i).get_attribute("href") or ""
                task_id = self._extract_fd_id(href)
                if task_id is not None:
                    if task_id in existing_ids:
                        if count_skips:
                            stats["skipped"] += 1
                        continue
                    # 扫描期即登记，漂移导致的同一条目跨页重复出现只收集一次
                    existing_ids.add(task_id)
                pending.append(
                    {"task_id": task_id, "href": urljoin(frame.url, href)}
                )
                new_on_page += 1
            await ctx.logger.step(
                "crawl", f"第 {page_num} 页共 {count} 条，新条目 {new_on_page} 条"
            )

            if not await self._has_next_page(frame):
                await ctx.logger.step("pagination", "已到最后一页，列表扫描完成")
                break
            fp_before = await self._fingerprint(frame)
            await self._click_next_page(frame, config)
            fp_after = await self._fingerprint(frame)
            if fp_before == fp_after:
                unchanged_streak += 1
                await ctx.logger.step(
                    "pagination",
                    f"翻页后列表未变化（指纹相同，连续 {unchanged_streak} 次）",
                    level="warn",
                )
                if unchanged_streak >= 2:
                    await ctx.logger.step(
                        "pagination", "连续 2 次翻页未生效，终止扫描", level="warn"
                    )
                    break
            else:
                unchanged_streak = 0
        return pending

    async def _open_detail(
        self, page: Page, item: dict, config, ctx, stats, existing_ids,
        semaphore: asyncio.Semaphore, shared_lock: asyncio.Lock,
    ) -> dict | None:
        """goto(href) 直达详情页提取元数据；单条失败计数后继续，不中断执行。

        task_id 必须从详情页落地 URL 提取（文档 ID），而非列表 href 中的通知 ID。
        OA 服务器会将 sysNotifyTodo.do?fdId=通知ID 重定向到实际文档页（fdId=文档ID），
        两者是不同的值。forward pipeline 的 showid= 参数需要文档 ID。

        semaphore 限制同 context 并行标签页数；shared_lock 串行日志写库
        （共享 AsyncSession）与 existing_ids 延迟去重的 check-then-add。
        """
        async with semaphore:
            detail = await page.context.new_page()
            try:
                await detail.goto(item["href"], wait_until="domcontentloaded")
                # 兜底前端 JS 跳转：服务端 302 时 goto 已跟随（URL 已是文档页，零开销）；
                # URL 仍停留在通知页 = JS 跳转（等导航完成）或文档已删除（等超时后跳过）
                if "sysNotifyTodo" in detail.url:
                    try:
                        await detail.wait_for_url(
                            lambda u: "sysNotifyTodo" not in u, timeout=5000
                        )
                    except PlaywrightTimeoutError:
                        pass
                if "sysNotifyTodo" in detail.url:
                    stats["extract_failures"] += 1
                    async with shared_lock:
                        await ctx.logger.step(
                            "extract",
                            f"详情页未跳转到文档页（文档可能已删除），跳过：{item['href'][:80]}",
                            level="warn",
                        )
                    return None
                # 始终从详情页落地 URL 提取 task_id（文档 ID，非列表 href 中的通知 ID）
                # OA 会将 sysNotifyTodo.do?fdId=通知ID 重定向到实际文档页（fdId=文档ID）
                task_id = self._extract_fd_id(detail.url)
                if not task_id:
                    stats["extract_failures"] += 1
                    async with shared_lock:
                        await ctx.logger.step(
                            "extract",
                            f"详情页 URL 无 task_id，跳过：{item['href'][:80]}",
                            level="warn",
                        )
                    return None
                async with shared_lock:
                    if task_id in existing_ids:
                        stats["skipped"] += 1
                        await ctx.logger.step(
                            "extract", f"{task_id[:8]} 已存在，跳过（延迟去重）"
                        )
                        return None
                    existing_ids.add(task_id)

                record = await self._extract_meta(
                    detail, task_id, config, ctx, stats, shared_lock
                )
                async with shared_lock:
                    await ctx.logger.step(
                        "extract", f"{record['title'][:50]}（task_id={task_id[:8]}）"
                    )
                return record
            except Exception as e:
                stats["extract_failures"] += 1
                async with shared_lock:
                    await ctx.logger.error(
                        "extract",
                        f"详情采集失败：{item.get('task_id') or item['href'][:60]} - {e}",
                    )
                return None
            finally:
                await detail.close()

    async def _extract_meta(
        self, page: Page, task_id: str, config, ctx, stats,
        shared_lock: asyncio.Lock,
    ) -> dict:
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

        attachment_urls = await self._download_attachments(
            page, task_id, config, ctx, stats, shared_lock
        )

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

    async def _download_attachments(
        self, page, task_id, config, ctx, stats, shared_lock: asyncio.Lock
    ) -> list[str]:
        """通过页面内 fetch 下载附件并上传 MinIO，返回成功项的代理下载 URL 列表"""
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
        async with shared_lock:
            await ctx.logger.step("attachment", f"检测到 {count} 个附件，开始下载上传")

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
                # 校验响应：无校验时 OA 错误页（503/登录页 HTML）会被当附件保存
                # （2026-07-28 事故：Apache 反代 hang 300s 后返回 503 HTML，被当 PDF 上传）
                b64_data = await page.evaluate(
                    """async ({ fdId, timeoutMs }) => {
                        const controller = new AbortController();
                        const timer = setTimeout(() => controller.abort(), timeoutMs);
                        try {
                            const resp = await fetch(
                                `/sys/attachment/sys_att_main/sysAttMain.do?method=download&fdId=${fdId}`,
                                { credentials: 'include', signal: controller.signal }
                            );
                            if (!resp.ok) {
                                throw new Error(`HTTP ${resp.status}`);
                            }
                            const ct = resp.headers.get('content-type') || '';
                            if (ct.includes('text/html')) {
                                throw new Error(`返回 HTML 而非文件（${ct}），可能服务器错误或登录失效`);
                            }
                            const buf = await resp.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            // 分块转换：逐字节 fromCharCode 对大附件极慢
                            let binary = '';
                            const CHUNK = 0x8000;
                            for (let i = 0; i < bytes.length; i += CHUNK) {
                                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
                            }
                            return btoa(binary);
                        } catch (e) {
                            if (e.name === 'AbortError') throw new Error(`附件下载超时（${timeoutMs}ms）`);
                            throw e;
                        } finally {
                            clearTimeout(timer);
                        }
                    }""",
                    {"fdId": fd_id, "timeoutMs": config["attachment_download_timeout"]},
                )

                file_bytes = base64.b64decode(b64_data)
                # 前缀完全决定存储路径（spec 1 二十五次修订：删除硬编码 attachments 段）
                object_key = f"{ctx.settings.minio_object_prefix}/{task_id}/{filename}"
                # boto3 为同步调用，to_thread 避免阻塞事件循环（并发详情页互不影响）
                await asyncio.to_thread(ctx.minio.upload, object_key, file_bytes)
                # 平台代理下载地址（spec 1 二十三次修订：预签名退役，URL 永不过期）；
                # safe="/" 保留 key 内路径分隔，中文文件名百分号编码
                url = f"{ctx.settings.public_base_url}/api/files/{quote(object_key, safe='/')}"
                # attachment_urls 仅收成功项的 URL 字符串（spec 3 2026-07-24 修订二）；
                # 失败附件由 stats 计数 + 日志记录，不入数组
                attachments.append(url)
                async with shared_lock:
                    await ctx.logger.step("attachment", f"附件已上传：{filename}")
            except Exception as e:
                stats["attachment_failures"] += 1
                async with shared_lock:
                    await ctx.logger.error("attachment", f"附件下载失败：{filename} - {e}")

        return attachments

    async def _get_page_fraction(self, frame) -> tuple[int, int] | None:
        """获取当前页/总页数，无分页组件返回 None。"""
        cur = frame.locator("span.lui_paging_t_page_info_current")
        total = frame.locator("span.lui_paging_t_page_info_total_page")
        if await cur.count() == 0 or await total.count() == 0:
            return None
        cur_text = (await cur.first.inner_text()).strip()
        total_text = (await total.first.inner_text()).strip()
        if not cur_text.isdigit() or not total_text.isdigit():
            return None
        return int(cur_text), int(total_text)

    async def _has_next_page(self, frame) -> bool:
        """当前页 < 总页数 且下一页按钮可用（末页时 hasnext 变为 notnext）。"""
        frac = await self._get_page_fraction(frame)
        if not frac:
            return False
        has_btn = await frame.locator("a.lui_paging_t_hasnext").count() > 0
        return frac[0] < frac[1] and has_btn

    async def _click_next_page(self, frame, config):
        btn = frame.locator("a.lui_paging_t_hasnext")
        if await btn.count() == 0:
            raise RuntimeError("下一页按钮不可用")
        await btn.first.click()
        # 等列表区域稳定：标题链接或空态文本出现
        title_link = frame.locator(_TITLE_LINK_SELECTOR).first
        empty = frame.get_by_text(_EMPTY_TEXT)
        await title_link.or_(empty).wait_for(
            state="visible", timeout=config["page_load_timeout"]
        )
        await frame.page.wait_for_timeout(config["action_settle_timeout"])

    async def _fingerprint(self, frame) -> str:
        """页码 + 首末标题，用于检测翻页是否生效。"""
        links = frame.locator(_TITLE_LINK_SELECTOR)
        count = await links.count()
        first = (await links.first.inner_text()).strip() if count else ""
        last = (await links.nth(count - 1).inner_text()).strip() if count else ""
        frac = await self._get_page_fraction(frame)
        frac_str = f"{frac[0]}/{frac[1]}" if frac else ""
        return f"{frac_str}|{first}|{last}"

    async def _get_total_count(self, frame) -> int | None:
        """从分页区域提取总条数（「共N条」）。"""
        paging = frame.locator(".lui_paging_total_left")
        scope = paging if await paging.count() > 0 else frame
        locator = scope.get_by_text(re.compile(r"共\s*\d+\s*条"))
        if await locator.count() == 0:
            return None
        text = await locator.first.inner_text()
        m = re.search(r"共\s*(\d+)\s*条", text)
        return int(m.group(1)) if m else None

    async def _save_records(self, records: list[dict], ctx: ExecutionContext):
        """批量写入 inbox_documents（raw SQL，engine 不可导入 backend models；表名由 TABLE_ 环境变量配置；
        id 为 BIGINT 自增主键，不显式赋值，由数据库生成）"""
        from sqlalchemy import text

        insert_sql = text(f"""
            INSERT INTO {_INBOX_TABLE} (task_id, creator, send_time, title, participants, cc_recipients, summary, attachment_urls)
            VALUES (:task_id, :creator, :send_time, :title, :participants, :cc_recipients, :summary, :attachment_urls)
            ON DUPLICATE KEY UPDATE
                creator = VALUES(creator),
                send_time = VALUES(send_time),
                title = VALUES(title),
                participants = VALUES(participants),
                cc_recipients = VALUES(cc_recipients),
                summary = VALUES(summary),
                attachment_urls = VALUES(attachment_urls)
        """)

        for record in records:
            await ctx.db.execute(insert_sql, {
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
