#!/bin/bash
# ============================================================
# 防堵头自动打印脚本
# 每7天没打印就自动打一张，防止喷墨打印机堵头
# ============================================================

set -euo pipefail

# ── 配置 ──
PRINTER="HPDJ2130"          # ← 改成你 CUPS 里的打印机名
CUPS_CONTAINER="cups2"      # ← docker-compose.yml 里 CUPS 服务的容器名
THRESHOLD_DAYS=7
THRESHOLD_SECONDS=$((THRESHOLD_DAYS * 86400))

# 防堵头文案文件（准备两张不同内容的 PDF，脚本会随机打一张）
# ← 改成你 NAS 上实际的防堵头 PDF 路径
FILE1="/your/nas/path/AForprinter/打印防堵头儿文案.pdf"
FILE2="/your/nas/path/AForprinter/打印防堵头儿文案2.pdf"

# Bark 推送（换成你自己的 Bark key，或用环境变量 BARK_KEY 传入）
BARK_KEY="${BARK_KEY:-在此填入你的BarkKey}"
BARK_URL="https://api.day.app/${BARK_KEY}"

# 日志
LOG_FILE="./anti-clog.log"
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ── 获取最近一次打印的完成时间 ──
# lpstat -W completed -o 输出格式：
# HPDJ2130-19  unknown  83968  Mon Jul 27 22:08:58 2026
get_last_print_epoch() {
    local output
    output=$(sudo docker exec "$CUPS_CONTAINER" lpstat -W completed -o 2>/dev/null || true)

    if [ -z "$output" ]; then
        echo ""
        return
    fi

    # 取第一行（最近完成的任务），提取最后5个字段（日期）
    local first_line
    first_line=$(echo "$output" | head -1)
    local date_str
    date_str=$(echo "$first_line" | awk '{print $(NF-4), $(NF-3), $(NF-2), $(NF-1), $NF}')

    if [ -z "$date_str" ]; then
        echo ""
        return
    fi

    # 解析日期为 epoch（CUPS 输出格式: Mon Jul 27 22:08:58 2026）
    local epoch
    epoch=$(date -d "$date_str" +%s 2>/dev/null || echo "")

    echo "$epoch"
}

# ── Bark 推送通知 ──
bark_notify() {
    local title="$1"
    local body="$2"
    curl -s -X POST "$BARK_URL" \
        -H "Content-Type: application/json; charset=utf-8" \
        -d "$(python3 -c "import json; print(json.dumps({'title': '$title', 'body': '$body'}))")" \
        >/dev/null 2>&1 || true
}

# ── 主流程 ──
log "=== 防堵头检查开始 ==="

LAST_EPOCH=$(get_last_print_epoch)

if [ -z "$LAST_EPOCH" ]; then
    log "⚠️ 无法获取打印记录，跳过本次检查"
    exit 0
fi

NOW_EPOCH=$(date +%s)
ELAPSED=$((NOW_EPOCH - LAST_EPOCH))
ELAPSED_DAYS=$((ELAPSED / 86400))

log "上次打印时间: $(date -d "@$LAST_EPOCH" '+%Y-%m-%d %H:%M:%S')"
log "距今已过: ${ELAPSED_DAYS}天 $((ELAPSED % 86400 / 3600))小时"

if [ "$ELAPSED" -lt "$THRESHOLD_SECONDS" ]; then
    REMAIN=$((THRESHOLD_SECONDS - ELAPSED))
    REMAIN_DAYS=$((REMAIN / 86400))
    log "✅ 未超期，剩余 ${REMAIN_DAYS}天，跳过"
    exit 0
fi

# ── 超过7天，执行防堵头打印 ──
log "🚨 已超过 ${THRESHOLD_DAYS} 天未打印，启动防堵头打印！"

# 随机选择文件
if [ $((RANDOM % 2)) -eq 0 ]; then
    PRINT_FILE="$FILE1"
else
    PRINT_FILE="$FILE2"
fi

log "选中文件: $PRINT_FILE"

# 通过 print-web 容器的 API 打印（文件挂载在容器的 /nas_files 下）
REL_PATH="${PRINT_FILE#/vol1/1000/}"  # 去掉前缀，得到相对路径
log "发送打印请求: path=$REL_PATH"

RESULT=$(curl -s -X POST http://localhost:5000/api/print-local \
    -H 'Content-Type: application/json' \
    -d "{\"path\": \"$REL_PATH\"}" 2>/dev/null || echo '{"success": false, "error": "curl failed"}')

SUCCESS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")

if [ "$SUCCESS" = "True" ]; then
    log "✅ 打印任务已发送"
    bark_notify "🖨️ 防堵头工具" "防堵头工具已运行并打印"
    log "✅ Bark 通知已发送"
else
    ERROR=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error', '未知错误'))" 2>/dev/null || echo "解析失败")
    log "❌ 打印失败: $ERROR"
    bark_notify "⚠️ 防堵头工具异常" "打印失败: $ERROR"
fi

log "=== 防堵头检查结束 ==="
