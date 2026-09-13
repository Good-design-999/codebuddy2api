#!/bin/bash
# codebuddy2api 重启脚本
# 用法: ./restart.sh [start|stop|restart|status]
# 启动方式与原有保持一致: uv run --env-file .env converter.py --desensitize --log converter.log

set -e
cd "$(dirname "$0")"

PIDFILE=".converter.pid"
LOGFILE="converter.stdout.log"
CMD=(uv run --env-file .env converter.py --desensitize --log converter.log)

get_pid() {
    # 优先读 pidfile；失效则回退到进程查找（限定本仓库路径，避免误伤）
    if [ -f "$PIDFILE" ]; then
        local p
        p=$(cat "$PIDFILE" 2>/dev/null || true)
        if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
            echo "$p"
            return 0
        fi
    fi
    pgrep -f "$(pwd)/.venv/bin/python3 converter.py" 2>/dev/null | head -1
}

do_status() {
    local p
    p=$(get_pid)
    if [ -n "$p" ]; then
        echo "运行中 (PID: $p)"
        curl -s --max-time 3 http://127.0.0.1:8787/health && echo ""
    else
        echo "未运行"
        return 1
    fi
}

do_stop() {
    local p
    p=$(get_pid)
    if [ -z "$p" ]; then
        echo "未运行，无需停止"
        rm -f "$PIDFILE"
        return 0
    fi
    echo "停止服务 (PID: $p)..."
    kill "$p" 2>/dev/null || true
    # 等待退出，最多 10 秒
    for _ in $(seq 1 10); do
        kill -0 "$p" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$p" 2>/dev/null; then
        echo "优雅停止超时，强制结束"
        kill -9 "$p" 2>/dev/null || true
    fi
    # uv 包装进程可能残留
    pkill -f "uv run --env-file .env converter.py" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "已停止"
}

do_start() {
    local p
    p=$(get_pid)
    if [ -n "$p" ]; then
        echo "已在运行 (PID: $p)，如需重启请用 ./restart.sh restart"
        return 0
    fi
    echo "启动服务..."
    nohup "${CMD[@]}" >> "$LOGFILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PIDFILE"
    # 等待端口就绪，最多 15 秒
    for _ in $(seq 1 15); do
        if curl -s --max-time 2 http://127.0.0.1:8787/health > /dev/null 2>&1; then
            echo "启动成功 (PID: $new_pid)"
            echo "健康检查: $(curl -s --max-time 3 http://127.0.0.1:8787/health)"
            echo "管理面板: http://127.0.0.1:8787/dashboard"
            return 0
        fi
        sleep 1
    done
    echo "警告: 15 秒内未通过健康检查，请查看 $LOGFILE"
    tail -20 "$LOGFILE"
    return 1
}

case "${1:-restart}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)  do_status ;;
    *)       echo "用法: $0 [start|stop|restart|status]"; exit 1 ;;
esac
