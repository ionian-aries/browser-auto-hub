-- 02-创建inbox_documents沟通待办表.sql
-- 沟通待办业务表：oa.communicate_todos 采集写入（按 task_id 去重），
-- oa.communicate_forward 读取并回写 fwd/forward_time。运行时自动产生数据，无需种子。
-- 与平台表无 FK 关联（表级独立），但需 01 已建库（USE browser_auto_hub）。
USE browser_auto_hub;

CREATE TABLE IF NOT EXISTS `inbox_documents` (
  `id` varchar(36) NOT NULL COMMENT 'UUID 主键',
  `task_id` varchar(64) NOT NULL COMMENT 'OA 待办 fdId（详情 URL 中的标识）',
  `creator` varchar(255) DEFAULT NULL COMMENT '创建人',
  `send_time` varchar(64) DEFAULT NULL COMMENT '发表时间（页面原文，如 2026-07-21 08:00）',
  `title` text NOT NULL COMMENT '标题',
  `participants` text NOT NULL COMMENT '接收者（逗号分隔姓名）',
  `cc_recipients` text NOT NULL COMMENT '抄送人（逗号分隔姓名）',
  `summary` text COMMENT '正文摘要',
  `attachment_urls` text NOT NULL COMMENT '附件下载 URL（JSON 字符串数组，仅上传成功项）',
  `fwd` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否已转发: 0未转发 1已转发',
  `skip` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否跳过: 0正常 1跳过',
  `forward_time` datetime DEFAULT NULL COMMENT '转发完成时间（UTC）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `task_id` (`task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='沟通待办表（todos 采集写入，forward 消费）';
