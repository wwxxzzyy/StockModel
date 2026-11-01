#!/usr/bin/env bash
# ==============================================================================
# StockModel Production Deployment Script
# Deploys StockModel and Web Dashboard to remote host (default: modelserver)
# ==============================================================================

set -euo pipefail

# Default configuration
TARGET_HOST="${TARGET_HOST:-modelserver}"
TARGET_USER="${TARGET_USER:-shawn}"
TARGET_PASS="${TARGET_PASS:-password}"
TARGET_PORT="${TARGET_PORT:-8000}"
TARGET_DIR="${TARGET_DIR:-/home/shawn/git/StockModel}"
OPT_SYMLINK="${OPT_SYMLINK:-/opt/stockmodel}"
SKIP_TESTS=false
SERVICE_NAME="stockmodel-web.service"

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Helper logging functions
log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Print help message
show_help() {
    cat << EOF
${BOLD}Usage:${NC} ./deploy.sh [OPTIONS]

${BOLD}Options:${NC}
  -h, --host HOST       Target hostname or IP address (default: modelserver / 192.168.1.36)
  -u, --user USER       Remote SSH username (default: shawn)
  -p, --pass PASS       Remote SSH/sudo password (default: password)
  --port PORT           Web dashboard port (default: 8000)
  --dir DIR             Remote target directory (default: /home/shawn/git/StockModel)
  --skip-tests          Skip running pytest verification before and after deployment
  --help                Show this help message

${BOLD}Examples:${NC}
  ./deploy.sh
  ./deploy.sh --host 192.168.1.36 --user shawn
  ./deploy.sh --skip-tests
EOF
}

# Parse command line options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--host)
            TARGET_HOST="$2"
            shift 2
            ;;
        -u|--user)
            TARGET_USER="$2"
            shift 2
            ;;
        -p|--pass)
            TARGET_PASS="$2"
            shift 2
            ;;
        --port)
            TARGET_PORT="$2"
            shift 2
            ;;
        --dir)
            TARGET_DIR="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BOLD}${CYAN}========================================================================${NC}"
echo -e "${BOLD}       StockModel Alpha Platform: Automated Deployment System       ${NC}"
echo -e "${BOLD}${CYAN}========================================================================${NC}"
echo -e "  Target Host:      ${BOLD}${TARGET_HOST}${NC}"
echo -e "  Target User:      ${BOLD}${TARGET_USER}${NC}"
echo -e "  Target Directory: ${BOLD}${TARGET_DIR}${NC}"
echo -e "  Web Service Port: ${BOLD}${TARGET_PORT}${NC}"
echo -e "  Skip Tests:       ${BOLD}${SKIP_TESTS}${NC}"
echo -e "${CYAN}------------------------------------------------------------------------${NC}"

# 1. Pre-flight local validation
log_info "Performing local pre-flight checks..."
for cmd in sshpass rsync ssh curl; do
    if ! command -v "$cmd" &>/dev/null; then
        log_error "Required local tool '$cmd' is not installed."
        exit 1
    fi
done

# Run local tests first if requested
if [[ "$SKIP_TESTS" == false ]]; then
    log_info "Running local test suite verification..."
    if command -v pytest &>/dev/null; then
        pytest tests/ -q || { log_error "Local test suite failed. Aborting deployment."; exit 1; }
    elif [[ -f ".venv/bin/pytest" ]]; then
        .venv/bin/pytest tests/ -q || { log_error "Local test suite in .venv failed. Aborting deployment."; exit 1; }
    else
        log_warn "pytest not found locally, continuing with remote test check..."
    fi
    log_success "Local pre-flight checks passed."
fi

# SSH and Sudo command wrapper
remote_exec() {
    sshpass -p "$TARGET_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${TARGET_USER}@${TARGET_HOST}" "$@"
}

remote_sudo() {
    local cmd="$1"
    remote_exec "echo '$TARGET_PASS' | sudo -S bash -c '$cmd'"
}

# 2. Connectivity verification
log_info "Verifying SSH connection to ${TARGET_HOST}..."
if ! remote_exec "whoami" &>/dev/null; then
    log_error "Cannot connect via SSH to ${TARGET_USER}@${TARGET_HOST}. Please verify host and credentials."
    exit 1
fi
log_success "SSH connection established successfully."

# 3. Synchronize code files
log_info "Ensuring remote directory structure exists at ${TARGET_DIR}..."
remote_exec "mkdir -p ${TARGET_DIR} $(dirname ${TARGET_DIR})"

log_info "Synchronizing codebase via rsync..."
sshpass -p "$TARGET_PASS" rsync -avz --delete \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.egg-info' \
    --exclude='*.pyc' \
    "$SCRIPT_DIR/" "${TARGET_USER}@${TARGET_HOST}:${TARGET_DIR}/"

log_success "Code synchronization complete."

# 4. Remote environment & system dependencies setup
log_info "Configuring remote runtime dependencies (System Native, No venv)..."
remote_sudo "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && \
    apt-get install -y -qq \
        rsync git python3-pip python3-venv python3-fastapi python3-uvicorn python3-httpx \
        python3-numpy python3-scipy python3-pandas python3-sklearn >/dev/null

    # Configure Polars compatibility runtime and Moomoo SDK
    pip install --break-system-packages --quiet 'polars[rtcompat]' 'moomoo-api' >/dev/null 2>&1 || true
    
    # Ensure POLARS_SKIP_CPU_CHECK is persisted
    grep -q 'POLARS_SKIP_CPU_CHECK' /etc/environment || echo 'POLARS_SKIP_CPU_CHECK=1' >> /etc/environment
    echo 'export POLARS_SKIP_CPU_CHECK=1' > /etc/profile.d/polars.sh

    # Setup /opt symlink
    ln -sfn '${TARGET_DIR}' '${OPT_SYMLINK}'

    # Install stockmodel package system-wide
    pip install --break-system-packages --quiet -e '${TARGET_DIR}'

    # Ensure ownership
    chown -R ${TARGET_USER}:${TARGET_USER} '${TARGET_DIR}'
"
log_success "Remote system packages and StockModel engine configured."

# 5. Configure and restart systemd service
log_info "Configuring systemd service '${SERVICE_NAME}'..."
remote_sudo "cat << 'EOF' > /etc/systemd/system/${SERVICE_NAME}
[Unit]
Description=StockModel Quantitative Alpha Web Dashboard & API
After=network.target

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${TARGET_DIR}
Environment=\"POLARS_SKIP_CPU_CHECK=1\"
Environment=\"PATH=/usr/local/bin:/usr/bin:/bin\"
ExecStart=/usr/local/bin/stockmodel serve --host 0.0.0.0 --port ${TARGET_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME} >/dev/null 2>&1
systemctl restart ${SERVICE_NAME}
"
log_success "Service '${SERVICE_NAME}' restarted."

# 6. Post-deployment health verification
log_info "Verifying service health on http://${TARGET_HOST}:${TARGET_PORT}/api/status..."
sleep 3

MAX_RETRIES=10
RETRY_COUNT=0
HEALTH_OK=false

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
    if curl -s -f "http://${TARGET_HOST}:${TARGET_PORT}/api/status" >/dev/null 2>&1; then
        HEALTH_OK=true
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 2
done

if [[ "$HEALTH_OK" == false ]]; then
    log_error "Health check timed out. Checking service status and logs..."
    remote_exec "systemctl status ${SERVICE_NAME} --no-pager -l" || true
    remote_exec "journalctl -u ${SERVICE_NAME} -n 30 --no-pager" || true
    exit 1
fi
log_success "Web dashboard API responded with HTTP 200 OK."

# 7. Run remote tests if requested
if [[ "$SKIP_TESTS" == false ]]; then
    log_info "Running remote pytest validation on ${TARGET_HOST}..."
    remote_exec "cd ${TARGET_DIR} && pytest -v"
    log_success "All remote tests passed successfully on ${TARGET_HOST}."
fi

echo -e "\n${BOLD}${GREEN}========================================================================${NC}"
echo -e "${BOLD}${GREEN}                   DEPLOYMENT COMPLETED SUCCESSFULLY                    ${NC}"
echo -e "${BOLD}${GREEN}========================================================================${NC}"
echo -e "  🌐 Web Dashboard:   ${BOLD}${CYAN}http://${TARGET_HOST}:${TARGET_PORT}/${NC}"
echo -e "  📡 API Status:      ${BOLD}http://${TARGET_HOST}:${TARGET_PORT}/api/status${NC}"
echo -e "  📊 Live Deciles:    ${BOLD}http://${TARGET_HOST}:${TARGET_PORT}/api/rank${NC}"
echo -e "  📈 Backtest Engine: ${BOLD}http://${TARGET_HOST}:${TARGET_PORT}/api/backtest${NC}"
echo -e "  🛠️  Service Name:    ${BOLD}${SERVICE_NAME}${NC}"
echo -e "  📂 Remote Directory: ${BOLD}${TARGET_DIR}${NC} (Symlinked: ${OPT_SYMLINK})"
echo -e "${GREEN}========================================================================${NC}\n"
