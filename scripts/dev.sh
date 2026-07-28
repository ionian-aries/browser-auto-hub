#!/usr/bin/env bash
# 一键启动整个项目（后端 + 前端）
# 基础设施（MySQL、MinIO）使用 .env 中配置的外部服务
# Ctrl+C 统一停止所有服务
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}已停止${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 检查 .env
if [ ! -f .env ]; then
    echo -e "${RED}错误: .env 文件不存在${NC}"
    echo "运行: cp .env.example .env 并填写配置"
    exit 1
fi

# 跨平台端口工具（兼容 macOS + Linux）
find_pids_on_port() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti :"$port" 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -tlnp "sport = :$port" 2>/dev/null | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' || true
    else
        (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null && echo "unknown" || true
    fi
}

port_is_listening() {
    local port=$1
    local pids
    pids=$(find_pids_on_port "$port")
    [ -n "$pids" ]
}

# 检查端口占用（合并检测，一次确认）
check_port_conflict() {
    local port=$1
    local service=$2
    local pids
    pids=$(find_pids_on_port "$port")
    if [ -n "$pids" ]; then
        OCCUPIED="${OCCUPIED}${port} "
        echo -e "${YELLOW}${service} (端口 $port) 被占用:${NC}"
        echo "$pids" | while read -r pid; do
            if [ "$pid" = "unknown" ]; then
                printf "  (无法获取进程信息)\n"
            else
                name=$(basename "$(ps -p "$pid" -o comm= 2>/dev/null)" 2>/dev/null || echo "unknown")
                printf "  PID %-6s  %s\n" "$pid" "$name"
            fi
        done
    fi
}

OCCUPIED=""
check_port_conflict 8900 "后端 API (uvicorn)"
check_port_conflict 3200 "前端 Dev Server (vite)"

if [ -n "$OCCUPIED" ]; then
    echo ""
    read -p "  是否清理以上端口？[y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        for port in ${OCCUPIED}; do
            pids=$(find_pids_on_port "$port")
            if [ -n "$pids" ] && [ "$pids" != "unknown" ]; then
                echo "$pids" | xargs kill 2>/dev/null || true
            fi
        done
        sleep 1
        echo -e "${GREEN}  已清理${NC}"
    else
        echo -e "${RED}  已取消，请手动释放端口后重试${NC}"
        exit 1
    fi
fi

# 等待端口就绪
wait_for_port() {
    local port=$1
    local name=$2
    local max_wait=15
    local i=0
    while ! port_is_listening "$port"; do
        sleep 1
        i=$((i + 1))
        if [ $i -ge $max_wait ]; then
            echo -e "${RED}$name 启动超时（端口 $port 未就绪）${NC}"
            exit 1
        fi
    done
}

# 1. 启动后端
echo -e "${BLUE}[1/2] 启动后端...${NC}"
cd "$ROOT_DIR"
uv run uvicorn backend.main:app --reload --port 8900 2>&1 | sed 's/^/  [backend] /' &
BACKEND_PID=$!
wait_for_port 8900 "后端"

# 2. 启动前端
echo -e "${BLUE}[2/2] 启动前端...${NC}"
cd "$ROOT_DIR/packages/frontend"
npx pnpm dev 2>&1 | sed 's/^/  [frontend] /' &
FRONTEND_PID=$!
wait_for_port 3200 "前端"

# 所有服务就绪后输出 banner
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  所有服务已启动！${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  前端:    ${BLUE}http://localhost:3200${NC}"
echo -e "  后端:    ${BLUE}http://localhost:8900${NC}"
echo -e "  API文档: ${BLUE}http://localhost:8900/docs${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  按 ${RED}Ctrl+C${NC} 停止所有服务"
echo ""

# 等待任一进程退出
wait $BACKEND_PID $FRONTEND_PID
