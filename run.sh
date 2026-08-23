#!/usr/bin/env bash
# ==============================================================================
# CascadeHeal — Production Management Harness
# Usage:
#   ./run.sh          - Restart clean (stop existing, start backend + frontend)
#   ./run.sh start    - Stop any existing services and start fresh
#   ./run.sh stop     - Stop backend and frontend processes
#   ./run.sh restart  - Restart all services
#   ./run.sh status   - Check status of running services
# ==============================================================================

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
BACKEND_PID_FILE="${ROOT_DIR}/.backend.pid"
FRONTEND_PID_FILE="${ROOT_DIR}/.frontend.pid"
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Color Codes
GREEN='\031[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

mkdir -p "${LOG_DIR}"

stop_services() {
    echo -e "${YELLOW}Stopping existing CascadeHeal services...${NC}"
    
    # Kill by stored PIDs if present
    if [ -f "${BACKEND_PID_FILE}" ]; then
        PID=$(cat "${BACKEND_PID_FILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            kill -9 "${PID}" 2>/dev/null || true
            echo -e "  Stopped Backend PID: ${PID}"
        fi
        rm -f "${BACKEND_PID_FILE}"
    fi

    if [ -f "${FRONTEND_PID_FILE}" ]; then
        PID=$(cat "${FRONTEND_PID_FILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            kill -9 "${PID}" 2>/dev/null || true
            echo -e "  Stopped Frontend PID: ${PID}"
        fi
        rm -f "${FRONTEND_PID_FILE}"
    fi

    # Port-level cleanup (ensures no orphaned background tasks remain bound)
    if command -v fuser >/dev/null 2>&1; then
        fuser -k "${BACKEND_PORT}/tcp" 2>/dev/null || true
        fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true
    fi

    # Fallback with lsof
    if command -v lsof >/dev/null 2>&1; then
        BE_PIDS=$(lsof -ti:${BACKEND_PORT} 2>/dev/null || true)
        if [ -n "${BE_PIDS}" ]; then
            kill -9 ${BE_PIDS} 2>/dev/null || true
        fi

        FE_PIDS=$(lsof -ti:${FRONTEND_PORT} 2>/dev/null || true)
        if [ -n "${FE_PIDS}" ]; then
            kill -9 ${FE_PIDS} 2>/dev/null || true
        fi
    fi

    sleep 1
    echo -e "${GREEN}✓ All services stopped successfully.${NC}"
}

start_services() {
    stop_services

    echo -e "${CYAN}Starting CascadeHeal Engine...${NC}"

    # 1. Start Python FastAPI Backend
    echo -n "  Starting Backend (FastAPI on port ${BACKEND_PORT})... "
    cd "${ROOT_DIR}/backend"
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
    if [ ! -f "${PYTHON_BIN}" ]; then
        PYTHON_BIN="python3"
    fi
    
    nohup "${PYTHON_BIN}" -m uvicorn main:app --host 127.0.0.1 --port "${BACKEND_PORT}" --reload > "${LOG_DIR}/backend.log" 2>&1 &
    BACKEND_PID=$!
    echo "${BACKEND_PID}" > "${BACKEND_PID_FILE}"
    echo -e "${GREEN}OK (PID: ${BACKEND_PID})${NC}"

    # 2. Start Next.js Frontend
    echo -n "  Starting Frontend (Next.js on port ${FRONTEND_PORT})... "
    cd "${ROOT_DIR}/frontend"
    nohup npm run dev -- -p "${FRONTEND_PORT}" > "${LOG_DIR}/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo "${FRONTEND_PID}" > "${FRONTEND_PID_FILE}"
    echo -e "${GREEN}OK (PID: ${FRONTEND_PID})${NC}"

    # Wait for health check
    echo -n "  Waiting for backend health check... "
    HEALTH_OK=0
    for i in {1..15}; do
        if curl -s "http://127.0.0.1:${BACKEND_PORT}/rails/health" | grep -q "rails" 2>/dev/null; then
            HEALTH_OK=1
            break
        fi
        sleep 1
    done

    if [ ${HEALTH_OK} -eq 1 ]; then
        echo -e "${GREEN}ONLINE${NC}"
    else
        echo -e "${RED}WARNING (Backend still booting — check logs/backend.log)${NC}"
    fi

    echo -e "\n${GREEN}=================================================================${NC}"
    echo -e "${GREEN}   CascadeHeal Engine Active & Operational                       ${NC}"
    echo -e "${GREEN}=================================================================${NC}"
    echo -e "  ${CYAN}Dashboard UI:${NC}    http://localhost:${FRONTEND_PORT}"
    echo -e "  ${CYAN}Backend Telemetry:${NC} http://localhost:${BACKEND_PORT}"
    echo -e "  ${CYAN}Backend Docs:${NC}      http://localhost:${BACKEND_PORT}/docs"
    echo -e "  ${CYAN}Backend Logs:${NC}      ${LOG_DIR}/backend.log"
    echo -e "  ${CYAN}Frontend Logs:${NC}     ${LOG_DIR}/frontend.log"
    echo -e "${GREEN}=================================================================${NC}\n"
}

check_status() {
    echo -e "${CYAN}CascadeHeal Service Status:${NC}"
    
    BE_STATUS="${RED}OFFLINE${NC}"
    if curl -s "http://127.0.0.1:${BACKEND_PORT}/rails/health" >/dev/null 2>&1; then
        BE_STATUS="${GREEN}ONLINE (http://localhost:${BACKEND_PORT})${NC}"
    fi

    FE_STATUS="${RED}OFFLINE${NC}"
    if curl -s "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
        FE_STATUS="${GREEN}ONLINE (http://localhost:${FRONTEND_PORT})${NC}"
    fi

    echo -e "  Backend API (Port ${BACKEND_PORT}):  ${BE_STATUS}"
    echo -e "  Frontend UI (Port ${FRONTEND_PORT}): ${FE_STATUS}"
}

ACTION="${1:-restart}"

case "${ACTION}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        start_services
        ;;
    status)
        check_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
