#!/bin/bash
# Xiaoeknow Spider Skill - Environment Setup Script

set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== Xiaoeknow Spider Skill Environment Check ==="
echo "Skill directory: $SKILL_DIR"
echo ""

# --- 1. Python Virtual Environment ---
echo "--- [1/6] Checking Python virtual environment ---"
VENV_DIR="$SKILL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    echo "  ✓ Virtual environment created."
else
    echo "  ✓ Virtual environment exists: $VENV_DIR"
fi

# Activate and install deps
source "$VENV_DIR/bin/activate"
echo "  Installing/upgrading Python dependencies..."
pip install -q --upgrade pip
pip install -q -r "$SKILL_DIR/requirements.txt"
echo "  ✓ Dependencies installed."
echo ""

# --- 2. Install Playwright Browsers ---
echo "--- [2/6] Installing Playwright Chromium ---"
playwright install chromium
echo "  ✓ Playwright Chromium installed."
echo ""

# --- 3. Check/Create logs directory ---
echo "--- [3/6] Checking logs directory ---"
mkdir -p "$SKILL_DIR/logs"
echo "  ✓ Logs directory ready."
echo ""

# --- 4. Initialize NAS download directory ---
echo "--- [4/6] Checking NAS download directory ---"
DATA_ROOT="${XIAOE_DOWNLOAD_DIR:-/Volumes/nas/xiaoeknow_data/downloads}"
if [ -d "$(dirname "$DATA_ROOT")" ]; then
    mkdir -p "$DATA_ROOT"
    echo "  ✓ NAS download directory ready: $DATA_ROOT"
else
    echo "  ⚠ NAS directory not accessible: $DATA_ROOT"
    echo "  ⚠ Will use local fallback: $SKILL_DIR/xiaoe_downloads"
fi
echo ""

# --- 5. Initialize Database ---
echo "--- [5/6] Initializing database table ---"
python "$SKILL_DIR/init_setup.py"
echo ""

# --- 6. Check .env configuration ---
echo "--- [6/6] Checking .env configuration ---"
ENV_FILE="$SKILL_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "  ✗ .env file NOT found at $ENV_FILE"
    echo "  Creating template .env file..."
    cat > "$ENV_FILE" <<'EOF'
# ==============================================================================
# PostgreSQL 数据库配置 (金融数据中心规范)
# ==============================================================================
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=hub_user
POSTGRES_PASSWORD=hub_password
POSTGRES_DB=financial_hub

# ==============================================================================
# NAS 文件存储路径 (必填，使用绝对路径)
# ==============================================================================
XIAOE_DOWNLOAD_DIR=/Volumes/nas/xiaoeknow_data/downloads
COOKIE_FILE=./xe_cookies.json
EOF
    echo "  ✓ Template .env created. Please edit it:"
    echo "    $ENV_FILE"
    echo ""
    exit 1
else
    source "$ENV_FILE" 2>/dev/null || true
    if [ -z "$POSTGRES_HOST" ] || [ -z "$POSTGRES_USER" ]; then
        echo "  ⚠ .env exists but database configuration is incomplete."
        echo "  Please edit: $ENV_FILE"
        exit 1
    else
        echo "  ✓ .env configured (host: $POSTGRES_HOST, db: $POSTGRES_DB)"
    fi
fi
echo ""

echo "=== All checks passed! ==="
echo ""
echo "Usage:"
echo "  # 启动 API 服务（默认启用客户直达模式）"
echo "  source $VENV_DIR/bin/activate"
echo "  python $SKILL_DIR/api_server.py"
echo ""
echo "  # 交互式下载（直接抓取用户提供的链接）"
echo "  python $SKILL_DIR/xe_crawler.py"