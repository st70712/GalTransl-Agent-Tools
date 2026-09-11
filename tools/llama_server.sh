#!/usr/bin/env bash
# 本機翻譯模型伺服器（llama.cpp llama-server + Sakura-GalTransl GGUF）的啟停腳本。
#
#   bash tools/llama_server.sh start  [--gpu N] [--port P] [--ctx C] [--np N] [--model PATH]
#   bash tools/llama_server.sh status
#   bash tools/llama_server.sh wait   [--timeout 300]
#   bash tools/llama_server.sh stop
#
# 預設值來自 config.yaml（llama_server_bin / model_gguf / llama_host / llama_port / llama_ctx / llama_np / llama_gpu）。
# start 是同步的：背景啟動後會等到 /health 回 ok 才返回；log 與 pid 在 logs/llama-server.{log,pid}。
# stop 只殺自己啟動的 pid（pid 檔），備援是掃 /proc/*/cmdline 找本使用者、含 llama-server 與同一 --port 的行程；絕不 pkill -f。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$REPO/config.yaml"
LOGDIR="$REPO/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/llama-server.log"; PIDFILE="$LOGDIR/llama-server.pid"

cfg() { grep -E "^$1:" "$CFG" 2>/dev/null | head -1 | sed -E 's/^[^:]+:\s*//; s/\s+#.*$//' || true; }

BIN="${AGT_LLAMA_SERVER_BIN:-$(cfg llama_server_bin)}"
MODEL="${AGT_MODEL_GGUF:-$(cfg model_gguf)}"
HOST="${AGT_LLAMA_HOST:-$(cfg llama_host)}"; HOST="${HOST:-127.0.0.1}"
PORT="${AGT_LLAMA_PORT:-$(cfg llama_port)}"; PORT="${PORT:-8080}"
CTX="${AGT_LLAMA_CTX:-$(cfg llama_ctx)}"; CTX="${CTX:-32768}"
NP="${AGT_LLAMA_NP:-$(cfg llama_np)}"; NP="${NP:-16}"
GPU="${AGT_LLAMA_GPU:-$(cfg llama_gpu)}"; GPU="${GPU:-auto}"
TIMEOUT=300

cmd="${1:-status}"; shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) GPU="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --ctx) CTX="$2"; shift 2;;
    --np) NP="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    *) echo "未知參數 $1" >&2; exit 2;;
  esac
done

URL="http://$HOST:$PORT"
health() { curl -fsS --max-time 3 "$URL/health" 2>/dev/null; }
models() { curl -fsS --max-time 3 "$URL/v1/models" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(", ".join(m.get("id","?") for m in d.get("data",[])))' 2>/dev/null || true; }

find_pids() {
  # 只找本使用者、命令列含 llama-server 與 --port $PORT 的行程
  for d in /proc/[0-9]*; do
    [[ -O "$d" ]] || continue
    local c; c="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null || true)"
    [[ "$c" == *llama-server* && "$c" == *"--port $PORT"* ]] && basename "$d"
  done
}

pick_gpu() {
  if [[ "$GPU" != "auto" ]]; then echo "$GPU"; return; fi
  # 挑已用記憶體最少的卡
  nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits 2>/dev/null \
    | sort -t, -k2 -n | head -1 | cut -d, -f1 | tr -d ' '
}

do_status() {
  local pids; pids="$(find_pids | tr '\n' ' ')"
  if h="$(health)"; then
    echo "✓ $URL 可用：$h  模型: $(models)  pid: ${pids:-?}"
    return 0
  fi
  if [[ -n "$pids" ]]; then echo "… 行程 $pids 在跑但 /health 尚未 ok（可能還在載入模型）"; return 1; fi
  echo "✗ $URL 沒有服務。啟動：bash tools/llama_server.sh start"
  return 1
}

do_wait() {
  local t=0
  until health >/dev/null; do
    sleep 2; t=$((t+2))
    if (( t >= TIMEOUT )); then echo "✗ 等了 ${TIMEOUT}s，$URL/health 仍未 ok；看 $LOG" >&2; return 1; fi
  done
  echo "✓ $URL 就緒（${t}s）：$(models)"
}

do_start() {
  if health >/dev/null; then do_status; return 0; fi
  [[ -x "$BIN" ]] || { echo "✗ 找不到 llama-server：$BIN" >&2; exit 1; }
  [[ -f "$MODEL" ]] || { echo "✗ 找不到模型：$MODEL" >&2; exit 1; }
  local gpu; gpu="$(pick_gpu)"
  echo "啟動 llama-server（GPU ${gpu:-未指定}，port $PORT，ctx $CTX，np $NP）"
  echo "  模型: $MODEL"
  echo "  log : $LOG"
  ( [[ -n "$gpu" ]] && export CUDA_VISIBLE_DEVICES="$gpu"
    nohup "$BIN" -m "$MODEL" --host "$HOST" --port "$PORT" -ngl 999 -c "$CTX" -np "$NP" --flash-attn on \
      > "$LOG" 2>&1 & echo $! > "$PIDFILE" )
  echo "  pid : $(cat "$PIDFILE")"
  do_wait
}

do_stop() {
  local pids=""
  [[ -f "$PIDFILE" ]] && pids="$(cat "$PIDFILE")"
  [[ -z "$pids" || ! -d "/proc/$pids" ]] && pids="$(find_pids | tr '\n' ' ')"
  if [[ -z "${pids// /}" ]]; then echo "沒有在跑的 llama-server（port $PORT）"; rm -f "$PIDFILE"; return 0; fi
  echo "停止 pid $pids"
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 15); do sleep 1; local alive=0; for p in $pids; do [[ -d "/proc/$p" ]] && alive=1; done; (( alive )) || break; done
  for p in $pids; do [[ -d "/proc/$p" ]] && kill -9 "$p" 2>/dev/null || true; done
  rm -f "$PIDFILE"; echo "已停止"
}

case "$cmd" in
  start) do_start;;
  status) do_status;;
  wait) do_wait;;
  stop) do_stop;;
  *) echo "用法: $0 start|status|wait|stop [--gpu N] [--port P] [--ctx C] [--np N] [--model PATH] [--timeout S]" >&2; exit 2;;
esac
