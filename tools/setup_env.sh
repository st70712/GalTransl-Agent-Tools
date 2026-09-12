#!/usr/bin/env bash
# 依 engines/<engine>/profile.json 的 python_env 宣告，用 uv 建立該引擎專用的虛擬環境並安裝 requirements。
#
#   bash tools/setup_env.sh <engine>            # 例：bash tools/setup_env.sh unity_textasset
#   bash tools/setup_env.sh <engine> --check    # 只檢查環境是否存在、套件是否齊
#
# 規則（CLAUDE.md §3）：核心工具只用標準庫；引擎若需要第三方套件，必須在 profile.json 宣告
#   "python_env": {"venv": ".venv-unity", "requirements": "requirements.txt", "python": "3.12"}
# 並把套件列在 engines/<engine>/requirements.txt。venv 建在 repo 根目錄（.gitignore 已忽略 .venv*），
# 換機器時重跑本腳本即可重建；不碰 conda 環境。
# Windows：在 Git Bash 執行同一指令；uv 請先 `pip install uv`（或 `winget install astral-sh.uv`），venv 直譯器在 Scripts/python.exe。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${1:-}"; MODE="${2:-}"
[[ -n "$ENGINE" ]] || { echo "用法: $0 <engine> [--check]" >&2; exit 2; }
PROFILE="$REPO/engines/$ENGINE/profile.json"
[[ -f "$PROFILE" ]] || { echo "找不到 $PROFILE" >&2; exit 2; }

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1;; *) WIN=0;; esac
PYTHON="${PYTHON:-$(command -v python3 || command -v python || true)}"
[[ -n "$PYTHON" ]] || { echo "找不到 python3／python" >&2; exit 2; }

read -r VENV REQ PYVER < <("$PYTHON" - "$PROFILE" <<'PY'
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8")).get("python_env") or {}
print(p.get("venv", ""), p.get("requirements", ""), p.get("python", ""))
PY
)
if [[ -z "$VENV" ]]; then echo "$ENGINE 沒有宣告 python_env，用標準庫直譯器即可"; exit 0; fi
VENV_DIR="$REPO/$VENV"
if [[ "$WIN" == 1 ]]; then PYBIN="$VENV_DIR/Scripts/python.exe"; else PYBIN="$VENV_DIR/bin/python"; fi
REQ_FILE="$REPO/engines/$ENGINE/${REQ:-requirements.txt}"

if [[ "$MODE" == "--check" ]]; then
  [[ -x "$PYBIN" ]] || { echo "✗ $VENV 不存在：bash tools/setup_env.sh $ENGINE"; exit 1; }
  "$PYBIN" - "$REQ_FILE" <<'PY' || exit 1
import importlib.metadata as md, re, sys
missing = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.split("#", 1)[0].strip()
    if not line: continue
    name = re.split(r"[<>=!~\[ ]", line, 1)[0]
    try: md.version(name)
    except md.PackageNotFoundError: missing.append(name)
print("✗ 缺套件: " + ", ".join(missing) if missing else "✓ 套件齊全")
sys.exit(1 if missing else 0)
PY
  exit 0
fi

export PATH="$HOME/.local/bin:${LOCALAPPDATA:-}/Programs/uv:${APPDATA:-}/Python/Scripts:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  # pip install uv 會把 uv.exe 裝進該 Python 的 Scripts（Store 版 Python 是 …/LocalCache/local-packages/Python311/Scripts，
  # 不在 PATH）；pip 套件 uv 自帶 find_uv_bin()，問它最準
  UV_BIN="$("$PYTHON" -c 'import uv; print(uv.find_uv_bin())' 2>/dev/null || true)"
  if [[ -n "$UV_BIN" ]]; then
    command -v cygpath >/dev/null 2>&1 && UV_BIN="$(cygpath -u "$UV_BIN")"
    export PATH="$(dirname "$UV_BIN"):$PATH"
    echo "uv 不在 PATH，改用 $UV_BIN"
  fi
fi
if ! command -v uv >/dev/null 2>&1; then
  if [[ "$WIN" == 1 ]]; then
    echo "找不到 uv。Windows 請先安裝：pip install uv   （或 winget install astral-sh.uv），再重跑本腳本" >&2; exit 2
  fi
  echo "安裝 uv（官方腳本 → ~/.local/bin）"; curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
# 設定值：config.local.yaml 覆蓋 config.yaml（與 core/config.py 同序）
cfg() { local v; v="$(grep -E "^$1:" "$REPO/config.local.yaml" 2>/dev/null | head -1 | sed -E 's/^[^:]+:\s*//; s/\s+#.*$//' || true)"
        [[ -n "$v" ]] || v="$(grep -E "^$1:" "$REPO/config.yaml" 2>/dev/null | head -1 | sed -E 's/^[^:]+:\s*//; s/\s+#.*$//' || true)"
        echo "$v"; }
if [[ ! -x "$PYBIN" ]]; then
  # 優先用設定指定的基底直譯器（同機器已存在，免下載），否則讓 uv 準備指定版本（uv 會自行下載）
  BASE="$(cfg python_nllb)"
  if [[ -n "$BASE" && -x "$BASE" ]]; then uv venv --python "$BASE" "$VENV_DIR"; else uv venv --python "${PYVER:-3.12}" "$VENV_DIR"; fi
fi
[[ -f "$REQ_FILE" ]] && uv pip install --python "$PYBIN" -r "$REQ_FILE"
echo "✓ $VENV 就緒：$PYBIN"
"$0" "$ENGINE" --check
