#!/usr/bin/env bash
# ===========================================================================
# IssueScope — 数据库初始化脚本
#
# 用法:
#   bash scripts/setup-db.sh               # 启动 PostgreSQL（已有 docker 时）
#   bash scripts/setup-db.sh --reset       # 删除旧数据重新开始
# ===========================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.yml"
DB_CONTAINER="issuescope-postgres"

# ── 检查 Docker ───────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker 未安装。请先安装 Docker："
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# ── 检测 docker compose 子命令 ────────────────────────────────────────────
DOCKER_COMPOSE=""
if docker compose version &>/dev/null; then
    DOCKER_COMPOSE="docker compose"
    echo "[INFO] 使用 docker compose（插件模式）"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE="docker-compose"
    echo "[INFO] 使用 docker-compose（独立命令）"
else
    echo "[ERROR] 未找到 docker compose 或 docker-compose。"
    echo "  请安装 Docker Compose："
    echo "  sudo apt install docker-compose   # 或"
    echo "  sudo dnf install docker-compose   # 或参考 Docker 官方文档"
    exit 1
fi

# ── Docker 用户组检查 ────────────────────────────────────────────────────
if ! docker info &>/dev/null; then
    echo ""
    echo "[WARN] 当前用户无权访问 Docker 守护进程（/var/run/docker.sock）"
    if groups | grep -q '\bdocker\b'; then
        echo "  → 虽在 docker 组中，但组权限未生效（需要重新登录）"
        echo "  请退出当前终端后重新登录，或执行 'newgrp docker' 后重试"
        exit 1
    else
        echo "  → 当前用户不在 docker 用户组中"
        echo ""
        echo "[询问] 是否将当前用户添加到 docker 组？（需 sudo 权限）"
        echo "  1) 是，添加到 docker 组（推荐，添加后需重新登录生效）"
        echo "  2) 否，退出"
        read -r -p "  请选择 [1/2] (默认 1): " group_choice
        group_choice="${group_choice:-1}"
        if [[ "$group_choice" == "1" ]]; then
            sudo usermod -aG docker "$USER" || {
                echo "[ERROR] 添加用户到 docker 组失败"
                exit 1
            }
            echo "[OK] 已添加 $USER 到 docker 组"
            echo ""
            echo "========================================"
            echo "  请执行以下命令使组权限生效："
            echo "    newgrp docker"
            echo "  然后重新运行此脚本："
            echo "    bash $0${*:+ $*}"
            echo "========================================"
            exit 0
        else
            echo ""
            echo "  请手动执行："
            echo "    sudo usermod -aG docker $USER && newgrp docker"
            echo "  或改用 sudo 运行此脚本："
            echo "    sudo bash $0${*:+ $*}"
            exit 1
        fi
    fi
fi

# ── 镜像源配置 ─────────────────────────────────────────────────────────────
configure_mirror() {
    local daemon_file="/etc/docker/daemon.json"

    # ── 检查是否已配置镜像源 ──
    if [[ -f "$daemon_file" ]] && command -v python3 &>/dev/null; then
        local existing_mirrors
        existing_mirrors=$(python3 -c "
import json
try:
    with open('$daemon_file') as f:
        cfg = json.load(f)
    for m in cfg.get('registry-mirrors', []):
        print(m)
except:
    pass
" 2>/dev/null) || true
        if [[ -n "$existing_mirrors" ]]; then
            local mirror_count
            mirror_count=$(echo "$existing_mirrors" | wc -l)
            echo ""
            echo "[INFO] 检测到已配置的 Docker 镜像加速器（共 ${mirror_count} 个）："
            echo "$existing_mirrors" | sed 's/^/    - /'
            echo ""
            echo "[询问] 是否重新配置镜像源？"
            echo "  1) 跳过，使用现有配置"
            echo "  2) 重新配置"
            read -r -p "  请选择 [1/2] (默认 1): " reconfirm
            reconfirm="${reconfirm:-1}"
            if [[ "$reconfirm" == "1" ]]; then
                echo "[SKIP] 跳过镜像配置"
                return
            fi
        fi
    fi

    echo ""
    echo "[询问] 是否配置 Docker 镜像加速器？（中国大陆访问 Docker Hub 可能不稳定）"
    echo "  1) 不配置（直接连接 Docker Hub）"
    echo "  2) 配置镜像 https://docker.1ms.run（推荐）"
    echo "  3) 自定义镜像地址"
    read -r -p "  请选择 [1/2/3] (默认 1): " mirror_choice
    mirror_choice="${mirror_choice:-1}"

    case "$mirror_choice" in
        2) MIRROR_URL="https://docker.1ms.run" ;;
        3) read -r -p "  输入镜像地址: " MIRROR_URL ;;
        *) echo "[SKIP] 跳过镜像配置" ;;
    esac

    if [[ -n "${MIRROR_URL:-}" ]]; then
        echo "[INFO] 配置 Docker 镜像源: $MIRROR_URL"
        if [[ -f "$daemon_file" ]]; then
            # 已有配置文件，追加镜像
            sudo sed -i "s|\"registry-mirrors\": \[[^]]*\]|\"registry-mirrors\": [\"$MIRROR_URL\"]|" "$daemon_file" 2>/dev/null || {
                # sed 失败则重新生成
                local content
                content=$(cat "$daemon_file")
                echo "$content" | python3 -c "
import json,sys
cfg=json.load(sys.stdin)
cfg.setdefault('registry-mirrors',[])
if '$MIRROR_URL' not in cfg['registry-mirrors']:
    cfg['registry-mirrors'].insert(0,'$MIRROR_URL')
json.dump(cfg,sys.stdout,indent=2)
" | sudo tee "$daemon_file" >/dev/null
            }
        else
            echo "{\"registry-mirrors\":[\"$MIRROR_URL\"]}" | sudo tee "$daemon_file" >/dev/null
        fi
        sudo systemctl restart docker
        echo "[OK] 镜像源已配置，Docker 已重启"
    fi
}

# ── 重置 ───────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--reset" ]]; then
    echo "[INFO] 停止并删除旧容器、旧数据..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" down -v
    echo "[OK] 已清理"
fi

# ── 配置镜像源 ─────────────────────────────────────────────────────────────
configure_mirror

# ── 启动 PostgreSQL ───────────────────────────────────────────────────────
echo "[INFO] 启动 PostgreSQL (pgvector/pg16)..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d

# ── 等待就绪 ──────────────────────────────────────────────────────────────
echo "[INFO] 等待数据库就绪..."
for i in $(seq 1 30); do
    if docker exec "$DB_CONTAINER" pg_isready -U issuescope -d issuescope &>/dev/null; then
        echo "[OK] 数据库已就绪 (localhost:5432)"
        break
    fi
    if [[ "$i" -eq 30 ]]; then
        echo "[ERROR] 数据库启动超时，请检查日志：$DOCKER_COMPOSE logs postgres"
        exit 1
    fi
    sleep 1
done

# ── 验证 pgvector ─────────────────────────────────────────────────────────
echo "[INFO] 验证 pgvector 扩展..."
docker exec "$DB_CONTAINER" psql -U issuescope -d issuescope -c "
    CREATE EXTENSION IF NOT EXISTS vector;
" >/dev/null
echo "[OK] pgvector 已就绪"

# ── 输出连接信息 ───────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  数据库连接信息"
echo "========================================"
echo "  Host:     localhost"
echo "  Port:     5432"
echo "  User:     issuescope"
echo "  Password: issuescope"
echo "  Database: issuescope"
echo "  URL:      postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope"
echo ""
echo "  在 backend/.env 中设置 DATABASE_URL 使用此连接。"
echo "========================================"

# ── 配置 backend/.env 中的数据库连接 ───────────────────────────────────────
ENV_FILE="backend/.env"
ENV_EXAMPLE="backend/.env.example"

configure_env() {
    echo ""
    echo "[询问] 是否更新后端环境变量中的数据库连接配置？"
    echo "  1) 是，写入数据库连接参数"
    echo "  2) 否，跳过"
    read -r -p "  请选择 [1/2] (默认 1): " env_choice
    env_choice="${env_choice:-1}"
    [[ "$env_choice" != "1" ]] && echo "[SKIP] 跳过环境变量配置" && return

    # ── 检查 .env 是否存在 ──
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$ENV_EXAMPLE" ]]; then
            echo "[INFO] $ENV_FILE 不存在，从 $ENV_EXAMPLE 创建..."
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            echo "[OK] 已创建 $ENV_FILE"
        else
            echo "[ERROR] $ENV_EXAMPLE 也不存在，无法创建 .env 文件"
            echo "  请手动创建 $ENV_FILE 并写入："
            echo "  DATABASE_URL=postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope"
            return
        fi
    fi

    # ── 检查是否已有 DATABASE_URL ──
    if grep -q '^DATABASE_URL=' "$ENV_FILE"; then
        local current_url
        current_url=$(grep '^DATABASE_URL=' "$ENV_FILE" | sed 's/^DATABASE_URL=//')
        echo ""
        echo "[INFO] $ENV_FILE 中已有 DATABASE_URL："
        echo "  当前值: $current_url"
        echo "  建议值: postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope"
        echo ""
        echo "[询问] 是否更新 DATABASE_URL？"
        echo "  1) 更新为建议值（推荐）"
        echo "  2) 保持不变"
        read -r -p "  请选择 [1/2] (默认 1): " update_choice
        update_choice="${update_choice:-1}"
        if [[ "$update_choice" != "1" ]]; then
            echo "[SKIP] 保持现有 DATABASE_URL"
            return
        fi
        # 替换 DATABASE_URL 行
        if sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope|" "$ENV_FILE" 2>/dev/null; then
            echo "[OK] 已更新 $ENV_FILE 中的 DATABASE_URL"
        else
            echo "[ERROR] 更新 $ENV_FILE 失败，请手动修改"
        fi
    else
        # 文件存在但没有 DATABASE_URL，追加
        echo "" >> "$ENV_FILE"
        echo "# 数据库连接（由 setup-db.sh 自动写入）" >> "$ENV_FILE"
        echo "DATABASE_URL=postgresql+psycopg://issuescope:issuescope@localhost:5432/issuescope" >> "$ENV_FILE"
        echo "[OK] 已在 $ENV_FILE 末尾追加 DATABASE_URL"
    fi
}

configure_env
