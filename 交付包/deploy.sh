#!/usr/bin/env bash
# deploy.sh — Browser Auto Hub 一键部署（幂等，可重复执行）
#
# .env.docker 是唯一配置源：DB 连接、MinIO、表名、端口均从中解析。
# 无需额外设置环境变量，无需交互输入密码。
#
# 前置条件：
#   - Docker（含 compose 插件）已安装
#   - MySQL 8.0 可达（DATABASE_URL 中的主机地址从部署机可解析）
#   - MinIO 可达（自动建桶：本地 mc 优先，未安装则用 Docker 内 minio/mc）
#
# 用法：
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step() { echo -e "\n${CYAN}▸ $1${NC}"; }
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

cd "$(dirname "$0")"

# ── 前置检查 ──────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker 未安装"
if docker compose version >/dev/null 2>&1; then
    _compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    _compose() { docker-compose "$@"; }
    warn "使用 docker-compose 独立命令（docker compose 插件不可用）"
else
    fail "docker compose 插件 / docker-compose 均未安装"
fi
[ -f .env.docker ] || fail ".env.docker 不存在"

# ══════════════════════════════════════════════════════
# 解析 .env.docker
# ══════════════════════════════════════════════════════
step "解析 .env.docker"

# 辅助：从 .env.docker 读取变量值（跳过注释和空行）
_env_val() { grep "^$1=" .env.docker | head -1 | cut -d= -f2-; }

# ── DATABASE_URL 解析 ──
# 格式：mysql+aiomysql://user:pass@host:port/dbname?charset=utf8mb4
_db_url=$(_env_val DATABASE_URL)
[ -n "$_db_url" ] || fail "DATABASE_URL 未设置"

_db_url_body="${_db_url#*://}"              # user:pass@host:port/dbname?charset=utf8mb4
_db_userpass="${_db_url_body%%@*}"          # user:pass
_db_hostport_db="${_db_url_body#*@}"        # host:port/dbname?charset=utf8mb4
_db_user="${_db_userpass%%:*}"              # user
_db_pass="${_db_userpass#*:}"               # pass
_db_hostport="${_db_hostport_db%%/*}"       # host:port
_db_name="${_db_hostport_db#*/}"            # dbname?charset=utf8mb4
_db_name="${_db_name%%\?*}"                 # dbname
_db_host="${_db_hostport%%:*}"              # host
_db_port="${_db_hostport##*:}"              # port（若 hostport 无 :，则等于 host，此时用默认）
[[ "$_db_port" =~ ^[0-9]+$ ]] || _db_port=3306

ok "MySQL: ${_db_user}@${_db_host}:${_db_port}/${_db_name}"

# ── 是否为 Docker Compose 服务名（需加入同一网络才能解析）──
_needs_docker_dns() {
    local host="$1"
    case "$host" in
        ""|localhost|127.0.0.1|host.docker.internal) return 1 ;;
    esac
    [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && return 1
    return 0
}

# 按服务主机名找到运行中容器所在 Docker 网络（优先带该别名的网络）
_docker_net_for_service() {
    local svc="$1"
    local cid=""

    cid=$(docker ps --format '{{.ID}}\t{{.Names}}' | awk -F'\t' -v s="$svc" '
        $2 == s { print $1; exit }
        index($2, s) { print $1; exit }
    ')

    if [ -z "$cid" ]; then
        case "$svc" in
            mysql)
                cid=$(docker ps --format '{{.ID}}\t{{.Image}}' | awk -F'\t' '$2 ~ /(^|\/)mysql([:]|$)/ { print $1; exit }')
                ;;
            minio)
                cid=$(docker ps --format '{{.ID}}\t{{.Image}}' | awk -F'\t' '$2 ~ /(^|\/)minio\// || $2 ~ /(^|\/)minio([:]|$)/ { print $1; exit }')
                ;;
        esac
    fi

    [ -n "$cid" ] || return 1

    local net=""
    net=$(docker inspect -f '{{range $name, $conf := .NetworkSettings.Networks}}{{range $conf.Aliases}}{{println $name " " .}}{{end}}{{end}}' "$cid" 2>/dev/null \
        | awk -v s="$svc" '$2 == s { print $1; exit }')
    if [ -z "$net" ]; then
        net=$(docker inspect -f '{{range $name, $conf := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$cid" | head -1)
    fi
    [ -n "$net" ] || return 1
    printf '%s' "$net"
}

# ── 部署机 MySQL 连接地址 ──
# DATABASE_URL 中的 host.docker.internal 是 Docker 容器内使用的地址；
# deploy.sh 运行在宿主机上，需替换为 127.0.0.1（同一台机器的 MySQL）
if [ "$_db_host" = "host.docker.internal" ]; then
    _deploy_db_host="127.0.0.1"
    ok "部署机连接地址: 127.0.0.1 (host.docker.internal → 宿主机本地)"
else
    _deploy_db_host="$_db_host"
fi

_mysql_net=""
if _needs_docker_dns "$_db_host"; then
    _mysql_net=$(_docker_net_for_service "$_db_host") \
        || fail "无法找到服务 '${_db_host}' 所在 Docker 网络。请确认 MySQL 容器已运行，或把 DATABASE_URL 主机改为可达 IP"
    ok "MySQL Docker 网络: ${_mysql_net}（用于解析 ${_db_host}）"
fi

# ── mysql 客户端（本地优先；服务名主机则必须走 Docker + 同网络）──
# --default-character-set=utf8mb4：防止中文被 latin1 双重编码
if command -v mysql >/dev/null 2>&1 && [ -z "$_mysql_net" ]; then
    _mysql() { mysql --default-character-set=utf8mb4 -h"$_deploy_db_host" -P"$_db_port" -u"$_db_user" -p"$_db_pass" "$@"; }
else
    # 离线环境优先复用本机已有 mysql 镜像（客户常见 mysql:8.4），避免硬编码 8.0 拉不到
    _mysql_img=""
    for _cand in mysql:8.4 mysql:8.0 mysql:latest mysql; do
        if docker image inspect "$_cand" >/dev/null 2>&1; then
            _mysql_img="$_cand"
            break
        fi
    done
    if [ -z "$_mysql_img" ]; then
        docker pull mysql:8.0 >/dev/null 2>&1 || true
        if docker image inspect mysql:8.0 >/dev/null 2>&1; then
            _mysql_img="mysql:8.0"
        else
            fail "本地无 mysql 客户端，且无可用 mysql 镜像（如 mysql:8.4 / mysql:8.0）。请安装 mysql 客户端，或 docker load / tag 一张 mysql 镜像后重试"
        fi
    fi
    if [ -n "$_mysql_net" ]; then
        warn "使用 Docker 内 ${_mysql_img} 执行 DDL（--network ${_mysql_net}）"
    else
        warn "本地 mysql 客户端未安装，使用 Docker 内 ${_mysql_img} 执行 DDL"
    fi
    _mysql() {
        local _args=(--rm -i --add-host "host.docker.internal:host-gateway")
        [ -n "$_mysql_net" ] && _args+=(--network "$_mysql_net")
        docker run "${_args[@]}" "$_mysql_img" mysql --default-character-set=utf8mb4 \
            -h"$_db_host" -P"$_db_port" -u"$_db_user" -p"$_db_pass" "$@"
    }
fi

# ── MinIO ──
_minio_endpoint=$(_env_val MINIO_ENDPOINT)
_minio_ak=$(_env_val MINIO_ACCESS_KEY)
_minio_sk=$(_env_val MINIO_SECRET_KEY)
_minio_bucket=$(_env_val MINIO_BUCKET)
_minio_endpoint="${_minio_endpoint:-http://127.0.0.1:9000}"
_minio_ak="${_minio_ak:-minioadmin}"
_minio_sk="${_minio_sk:-minioadmin}"
_minio_bucket="${_minio_bucket:-browser-auto-hub}"

ok "MinIO: ${_minio_endpoint} → ${_minio_bucket}"

# 从 endpoint 解析主机名（http://minio:9000 → minio）
_minio_host=$(printf '%s' "$_minio_endpoint" | sed -E 's|^[a-zA-Z][a-zA-Z0-9+.-]*://||; s|[:/].*||')
_minio_net=""
if _needs_docker_dns "$_minio_host"; then
    _minio_net=$(_docker_net_for_service "$_minio_host") \
        || fail "无法找到服务 '${_minio_host}' 所在 Docker 网络。请确认 MinIO 容器已运行，或把 MINIO_ENDPOINT 改为可达地址"
    ok "MinIO Docker 网络: ${_minio_net}（用于解析 ${_minio_host}）"
fi

# ── mc 客户端（本地优先，回退到 Docker 内执行；都没有则跳过建桶）──
_mc_docker_mode=0
_mc_available=0
if command -v mc >/dev/null 2>&1 && [ -z "$_minio_net" ]; then
    _mc() { mc "$@"; }
    _mc_available=1
else
    _mc_img=""
    for _cand in minio/mc minio/mc:latest; do
        if docker image inspect "$_cand" >/dev/null 2>&1; then
            _mc_img="$_cand"
            break
        fi
    done
    if [ -z "$_mc_img" ]; then
        docker pull minio/mc >/dev/null 2>&1 || true
        if docker image inspect minio/mc >/dev/null 2>&1; then
            _mc_img="minio/mc"
        fi
    fi
    if [ -n "$_mc_img" ]; then
        warn "本地 mc 未安装，使用 Docker 内 ${_mc_img} 执行"
        # MinIO endpoint 中的 127.0.0.1/localhost 在容器内不可达，替换为 host.docker.internal
        _mc_endpoint_for_docker="$_minio_endpoint"
        _mc_endpoint_for_docker="${_mc_endpoint_for_docker//127.0.0.1/host.docker.internal}"
        _mc_endpoint_for_docker="${_mc_endpoint_for_docker//localhost/host.docker.internal}"
        # 每次调用先 alias set 再执行实际操作（每次 docker run 是独立容器，alias 不持久化）
        _mc() {
            local _args=(--rm -i --add-host "host.docker.internal:host-gateway" --entrypoint sh)
            [ -n "$_minio_net" ] && _args+=(--network "$_minio_net")
            docker run "${_args[@]}" "$_mc_img" -c "mc alias set deploy '${_mc_endpoint_for_docker}' '${_minio_ak}' '${_minio_sk}' >/dev/null && mc $*"
        }
        _mc_docker_mode=1
        _mc_available=1
    else
        warn "本地无 mc 且无 minio/mc 镜像，跳过自动建桶（请确认桶 ${_minio_bucket} 已在 MinIO 中创建）"
    fi
fi

# ── 业务表名（TABLE_ 前缀） ──
_tbl_inbox=$(_env_val TABLE_inbox_documents)
_tbl_inbox="${_tbl_inbox:-inbox_documents}"
_tbl_ganghang=$(_env_val TABLE_ganghang_materials)
_tbl_ganghang="${_tbl_ganghang:-ganghang_materials}"

ok "业务表: ${_tbl_inbox} / ${_tbl_ganghang}"

# ── 端口 ──
_backend_port=$(_env_val BACKEND_PORT)
_backend_port="${_backend_port:-8901}"
_frontend_port=$(_env_val FRONTEND_PORT)
_frontend_port="${_frontend_port:-3201}"

# ══════════════════════════════════════════════════════
# Step 1: 加载镜像
# ══════════════════════════════════════════════════════
step "加载 Docker 镜像"

_load_image() {
    local tar="$1" name="$2"
    [ -f "$tar" ] || fail "镜像文件缺失: $tar"

    # frontend：青岛港 Docker 20.10 上 tar.gz load 常 invalid diffID / 假成功不换层。
    # 一律走 rootfs import，并先删旧 tag，保证页面资产真正更新。
    if [ "$name" = "browser-auto-hub-frontend:latest" ]; then
        local rootfs="browser-auto-hub-frontend-rootfs.tar"
        [ -f "$rootfs" ] || fail "缺少 frontend rootfs: $rootfs（与 deploy.sh 同目录）"
        docker rmi "$name" >/dev/null 2>&1 || true
        docker import \
          --change 'ENTRYPOINT ["/docker-entrypoint.sh"]' \
          --change 'CMD ["nginx","-g","daemon off;"]' \
          --change 'EXPOSE 80' \
          "$rootfs" "$name" >/dev/null
        ok "$name 已通过 rootfs import 导入"
        return 0
    fi

    if docker load -i "$tar"; then
        ok "$name 已加载"
        return 0
    fi
    fail "$name 导入失败"
}
_load_image browser-auto-hub-backend.tar.gz  "browser-auto-hub-backend:latest"
_load_image browser-auto-hub-frontend.tar.gz "browser-auto-hub-frontend:latest"

# ══════════════════════════════════════════════════════
# Step 2: 建库建表（IF NOT EXISTS，幂等）
# ══════════════════════════════════════════════════════
step "建库建表（IF NOT EXISTS）"

# ── 平台表 DDL ──
_mysql <<PLATFORM_SQL
CREATE DATABASE IF NOT EXISTS \`$_db_name\`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE \`$_db_name\`;

-- 流水线注册表
CREATE TABLE IF NOT EXISTS \`pipelines\` (
  \`id\` varchar(36) NOT NULL COMMENT 'UUID 主键',
  \`name\` varchar(100) NOT NULL COMMENT '流水线标识，如 oa.communicate_todos',
  \`display_name\` varchar(200) NOT NULL COMMENT '中文显示名',
  \`description\` text NOT NULL COMMENT '描述',
  \`trigger_modes\` json NOT NULL COMMENT '支持的触发方式，如 ["cron","api","manual"]',
  \`config_schema\` json DEFAULT NULL COMMENT 'config 的 JSON Schema（前端动态渲染表单）',
  \`status\` enum('active','disabled','archived') NOT NULL DEFAULT 'active' COMMENT '状态；非 active 不可触发',
  \`version\` varchar(50) NOT NULL DEFAULT '1.0.0' COMMENT '代码声明版本，sync 按版本差异决定是否更新定义',
  \`created_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  \`updated_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`ix_pipelines_name\` (\`name\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='流水线注册表（启动自动同步）';

-- 调度定义表
CREATE TABLE IF NOT EXISTS \`schedules\` (
  \`id\` varchar(36) NOT NULL COMMENT 'UUID 主键',
  \`pipeline_id\` varchar(36) NOT NULL COMMENT '关联 pipelines.id',
  \`name\` varchar(200) NOT NULL COMMENT '调度名称',
  \`trigger_type\` enum('cron','interval','once') NOT NULL COMMENT '触发类型：cron表达式/固定间隔/单次',
  \`cron_expr\` varchar(100) DEFAULT NULL COMMENT 'cron 表达式（trigger_type=cron 时必填）',
  \`interval_seconds\` int DEFAULT NULL COMMENT '间隔秒数（trigger_type=interval 时必填）',
  \`run_at\` datetime(6) DEFAULT NULL COMMENT '执行时刻（trigger_type=once 时必填，UTC）',
  \`config_override\` json DEFAULT NULL COMMENT '执行入参；调度触发时原样作为 execution.config',
  \`enabled\` tinyint(1) NOT NULL COMMENT '是否启用',
  \`max_retries\` int NOT NULL COMMENT '失败自动重试次数',
  \`retry_delay_seconds\` int NOT NULL COMMENT '重试间隔秒数',
  \`created_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  \`updated_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (\`id\`),
  KEY \`pipeline_id\` (\`pipeline_id\`),
  CONSTRAINT \`schedules_ibfk_1\` FOREIGN KEY (\`pipeline_id\`) REFERENCES \`pipelines\` (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='调度定义表';

-- 执行记录表
CREATE TABLE IF NOT EXISTS \`task_executions\` (
  \`id\` varchar(36) NOT NULL COMMENT 'UUID 主键',
  \`pipeline_id\` varchar(36) NOT NULL COMMENT '关联 pipelines.id',
  \`schedule_id\` varchar(36) DEFAULT NULL COMMENT '调度触发时关联 schedules.id，否则 NULL',
  \`trigger_type\` enum('scheduled','api','manual') NOT NULL COMMENT '触发方式',
  \`status\` enum('pending','running','success','failed','cancelled') NOT NULL COMMENT '执行状态',
  \`config\` json DEFAULT NULL COMMENT '本次执行的入参快照',
  \`retry_count\` int NOT NULL COMMENT '已重试次数',
  \`started_at\` datetime DEFAULT NULL COMMENT '开始时间（UTC）',
  \`finished_at\` datetime DEFAULT NULL COMMENT '结束时间（UTC）',
  \`error_message\` text COMMENT '失败原因',
  \`result_summary\` json DEFAULT NULL COMMENT '业务统计（如采集/转发条数）',
  \`pipeline_version\` varchar(50) DEFAULT NULL COMMENT '触发时 pipeline 版本快照',
  \`created_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (\`id\`),
  KEY \`pipeline_id\` (\`pipeline_id\`),
  KEY \`schedule_id\` (\`schedule_id\`),
  CONSTRAINT \`task_executions_ibfk_1\` FOREIGN KEY (\`pipeline_id\`) REFERENCES \`pipelines\` (\`id\`),
  CONSTRAINT \`task_executions_ibfk_2\` FOREIGN KEY (\`schedule_id\`) REFERENCES \`schedules\` (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行记录表（运行时自动写入）';

-- 步骤日志表
CREATE TABLE IF NOT EXISTS \`task_logs\` (
  \`id\` varchar(36) NOT NULL COMMENT 'UUID 主键',
  \`execution_id\` varchar(36) NOT NULL COMMENT '关联 task_executions.id',
  \`timestamp\` datetime(6) NOT NULL DEFAULT (utc_timestamp(6)) COMMENT '日志时间（UTC，微秒精度）',
  \`level\` enum('info','warn','error') NOT NULL COMMENT '级别',
  \`step_name\` varchar(100) NOT NULL COMMENT '步骤名，如 login / crawl / forward[xxxxxxxx]',
  \`message\` text NOT NULL COMMENT '日志内容',
  PRIMARY KEY (\`id\`),
  KEY \`execution_id\` (\`execution_id\`),
  CONSTRAINT \`task_logs_ibfk_1\` FOREIGN KEY (\`execution_id\`) REFERENCES \`task_executions\` (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行步骤日志表（运行时自动写入）';

-- 系统设置表
CREATE TABLE IF NOT EXISTS \`system_settings\` (
  \`key\` varchar(100) NOT NULL COMMENT '设置键，如 run_headless / run_default_max_retries',
  \`value\` text NOT NULL COMMENT '设置值（统一按字符串存储）',
  \`updated_at\` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (\`key\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统设置表（代码默认值兜底，无需种子）';
PLATFORM_SQL

ok "平台 5 表就绪"

# ── 业务表 DDL（表名动态，来自 TABLE_inbox_documents） ──
_mysql <<INBOX_SQL
USE \`$_db_name\`;

CREATE TABLE IF NOT EXISTS \`$_tbl_inbox\` (
  \`id\` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  \`task_id\` varchar(64) NOT NULL COMMENT 'OA 文档 fdId（详情页落地 URL 中的标识，非列表 href 中的通知 ID）',
  \`creator\` varchar(255) DEFAULT NULL COMMENT '创建人',
  \`send_time\` varchar(64) DEFAULT NULL COMMENT '发表时间（页面原文，如 2026-07-21 08:00）',
  \`title\` text NOT NULL COMMENT '标题',
  \`participants\` text NOT NULL COMMENT '接收者（逗号分隔姓名）',
  \`cc_recipients\` text NOT NULL COMMENT '抄送人（逗号分隔姓名）',
  \`summary\` text COMMENT '正文摘要',
  \`attachment_urls\` text NOT NULL COMMENT '附件下载 URL（JSON 字符串数组，仅上传成功项）',
  \`fwd\` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否已转发: 0未转发 1已转发(历史) 2已转发',
  \`skip\` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否跳过: 0正常 1跳过',
  \`forward_time\` datetime DEFAULT NULL COMMENT '转发完成时间（UTC）',
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`task_id\` (\`task_id\`),
  KEY \`idx_inbox_documents_fwd_send\` (\`fwd\`, \`send_time\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='沟通待办表（todos 采集写入，forward 消费）';
INBOX_SQL

ok "业务表 ${_tbl_inbox} 就绪"

# ── 港航素材表 DDL（表名动态，来自 TABLE_ganghang_materials；结构与在线库一致） ──
_mysql <<GANGHANG_SQL
USE \`$_db_name\`;

CREATE TABLE IF NOT EXISTS \`$_tbl_ganghang\` (
  \`id\` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  \`category\` varchar(50) NOT NULL COMMENT '13个中文分类之一',
  \`title\` varchar(500) NOT NULL COMMENT '原始标题',
  \`content\` longtext NOT NULL COMMENT '正文全文',
  \`digest\` text NOT NULL COMMENT '成稿正文',
  \`insight\` text COMMENT '战略参考',
  \`link_url\` varchar(1000) NOT NULL COMMENT '原文URL',
  \`execution_id\` varchar(36) DEFAULT NULL COMMENT '最后写入的执行ID',
  \`doc_date\` date NOT NULL COMMENT '发布日期',
  \`website_name\` varchar(255) NOT NULL COMMENT '信源名称',
  \`score\` decimal(3,1) DEFAULT NULL COMMENT '资讯类评分（固定类NULL）',
  \`score_reason\` varchar(500) DEFAULT NULL COMMENT '评分理由（固定类NULL）',
  \`created_at\` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  \`updated_at\` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后写入时间',
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`idx_link_url\` (\`link_url\`(255)),
  KEY \`idx_category\` (\`category\`),
  KEY \`idx_doc_date\` (\`doc_date\`),
  KEY \`idx_website\` (\`website_name\`),
  KEY \`idx_execution\` (\`execution_id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
GANGHANG_SQL

ok "业务表 ${_tbl_ganghang} 就绪"

# ══════════════════════════════════════════════════════
# Step 3: MinIO 建桶（已存在则跳过）
# ══════════════════════════════════════════════════════
step "MinIO 桶检查"

if [ "$_mc_available" != "1" ]; then
    warn "跳过建桶检查，请确认 MinIO 中已有桶: ${_minio_bucket}"
else
    # 本地模式需先设 alias（Docker 模式已在 _mc 函数内部完成）
    if [ "$_mc_docker_mode" = "0" ]; then
        _mc alias set deploy "$_minio_endpoint" "$_minio_ak" "$_minio_sk" >/dev/null 2>&1 || true
    fi

    if _mc ls "deploy/$_minio_bucket" >/dev/null 2>&1; then
        ok "桶 $_minio_bucket 已存在，跳过"
    else
        _mc mb "deploy/$_minio_bucket" 2>&1
        ok "桶 $_minio_bucket 已创建"
    fi
fi

# ══════════════════════════════════════════════════════
# Step 4: 启动服务
# ══════════════════════════════════════════════════════
step "启动服务（docker compose）"

# --force-recreate：同 tag latest 换了镜像内容时，纯 up -d 可能继续跑旧容器
_compose -f docker-compose.prod.yml --env-file .env.docker up -d --force-recreate --remove-orphans
ok "服务已启动"

# DATABASE_URL / MINIO 使用 compose 服务名时，API 容器必须加入同一网络才能解析
# 兼容旧服务名 backend 与青岛港 bah-api
_backend_cid=$(docker ps -qf "name=bah-api" | head -1)
[ -z "$_backend_cid" ] && _backend_cid=$(docker ps -qf "name=browser-auto-hub-backend" | head -1)
if [ -n "$_backend_cid" ]; then
    if [ -n "$_mysql_net" ]; then
        if docker network connect "$_mysql_net" "$_backend_cid" 2>/dev/null; then
            ok "bah-api/backend 已加入 MySQL 网络: ${_mysql_net}"
        else
            ok "bah-api/backend 已在 MySQL 网络 ${_mysql_net}（或无需重复连接）"
        fi
    fi
    if [ -n "$_minio_net" ] && [ "$_minio_net" != "$_mysql_net" ]; then
        if docker network connect "$_minio_net" "$_backend_cid" 2>/dev/null; then
            ok "bah-api/backend 已加入 MinIO 网络: ${_minio_net}"
        else
            ok "bah-api/backend 已在 MinIO 网络 ${_minio_net}（或无需重复连接）"
        fi
    fi
fi

# ══════════════════════════════════════════════════════
# Step 5: 等待后端就绪 + 种子数据
# ══════════════════════════════════════════════════════
step "等待后端就绪"

_max_wait=60
_waited=0

while ! curl -sf "http://localhost:${_backend_port}/api/pipelines" >/dev/null 2>&1; do
    sleep 2
    _waited=$((_waited + 2))
    if [ $_waited -ge $_max_wait ]; then
        warn "后端在 ${_max_wait}s 内未就绪，请检查日志:"
        warn "  docker compose -f docker-compose.prod.yml logs bah-api"
        warn "种子数据需后端启动后执行，请稍后重跑 deploy.sh"
        break
    fi
    echo -ne "  等待中... ${_waited}s\r"
done
echo

if curl -sf "http://localhost:${_backend_port}/api/pipelines" >/dev/null 2>&1; then
    ok "后端已就绪（${_waited}s）"

    step "写入种子数据（默认调度，幂等，部署即可用）"

    _mysql -D "$_db_name" <<'SEED_SQL'
-- 默认调度：每 10 分钟执行一次 oa.communicate_todos（沟通待办采集）。
-- 幂等：已存在「同 pipeline + interval 600s」的调度时不再插入。
-- 前提：pipelines 表已有 oa.communicate_todos 行（后端启动时自动同步）。
-- config_override 显式列出全部业务参数，便于部署后在前端直接微调。
INSERT INTO schedules
  (id, pipeline_id, name, trigger_type, interval_seconds, config_override, enabled, max_retries, retry_delay_seconds)
SELECT
  UUID(),
  p.id,
  '每10分钟采集沟通待办',
  'interval',
  600,
  JSON_OBJECT(
    'username', 'ceshiyong4',
    'password', 'G7@kLp9#wQnR$2x',
    'login_url', 'https://ioa.sd-port.net/login.jsp',
    'max_pages', 100,
    'max_verify_rounds', 2,
    'concurrency', 1
  ),
  1,
  0,
  60
FROM pipelines p
WHERE p.name = 'oa.communicate_todos'
  AND NOT EXISTS (
    SELECT 1 FROM schedules s
    WHERE s.pipeline_id = p.id
      AND s.trigger_type = 'interval'
      AND s.interval_seconds = 600
  );

-- 默认调度：每天 06:00（北京时间）采集前一日的港航信息。
-- 时区换算（容器无 TZ 设置，APScheduler 与 today 解析均按 UTC）：
--   北京 06:00 = UTC 前一天 22:00，故 cron_expr = '0 22 * * *'；
--   触发瞬间 UTC 日历日（如 7-30）恰是北京刚结束的那一天（北京已是 7-31 06:00），
--   因此 start/end 必须用 today（UTC 当日 = 北京昨天）——若照搬 08:00 版本的
--   today-1，会解析成北京"前天"，系统性错一天。
--   result_summary.period 显示的日期即北京"前一天"，核对语义不变。
--   若容器日后设 TZ=Asia/Shanghai，需把 cron_expr 改为 '0 6 * * *'、start/end 改为 today-1。
-- 采前一天而非当天 23 点：窗口完整闭合，23:00~24:00 发布的文章不会系统性遗漏；
--   当天 0~6 点的文章次日作为"昨天"被采，T+1 内全部入库（月刊无时效压力）。
-- sources 省略 = 全部信源：执行时刻展开为 sources.json 全量，后续新增信源自动纳入，免维护。
-- 迁移：本任务由此前 08:00（UTC '0 0 * * *'）版本调整为 06:00；若旧调度已随先前
--   部署入库，先删除避免双跑同一窗口（幂等，无旧行则无影响）。
-- 幂等：已存在「同 pipeline + 同 cron_expr」的调度时不再插入。
-- 重试：失败 10 分钟后自动重试 1 次（无人值守任务的网络抖动兜底）。
DELETE s FROM schedules s
JOIN pipelines p ON p.id = s.pipeline_id
WHERE p.name = 'port_maritime_info.harvest'
  AND s.trigger_type = 'cron'
  AND s.cron_expr = '0 0 * * *';

INSERT INTO schedules
  (id, pipeline_id, name, trigger_type, cron_expr, config_override, enabled, max_retries, retry_delay_seconds)
SELECT
  UUID(),
  p.id,
  '每日06:00采集前一日港航信息',
  'cron',
  '0 22 * * *',
  JSON_OBJECT(
    'start_date', 'today',
    'end_date', 'today'
  ),
  1,
  1,
  600
FROM pipelines p
WHERE p.name = 'port_maritime_info.harvest'
  AND NOT EXISTS (
    SELECT 1 FROM schedules s
    WHERE s.pipeline_id = p.id
      AND s.trigger_type = 'cron'
      AND s.cron_expr = '0 22 * * *'
  );
SEED_SQL

    ok "种子数据写入完成"
fi

# ══════════════════════════════════════════════════════
# 完成
# ══════════════════════════════════════════════════════
echo
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} 部署完成${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo
echo "  后端 API:  http://localhost:${_backend_port}/api/pipelines"
echo "  前端页面:  http://localhost:${_frontend_port}"
echo
echo "  查看日志:  docker compose -f docker-compose.prod.yml logs -f"
echo "  停止服务:  docker compose -f docker-compose.prod.yml down"
echo "  重启服务:  docker compose -f docker-compose.prod.yml restart"
