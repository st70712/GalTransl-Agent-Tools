"""``projects/<game>/agt.json``：引擎辨識結果與關卡狀態。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

GATES = (
    "prepare", "roundtrip", "export", "zero_import", "verify", "breakage",
    "smoke_build", "user_boot_ok", "translate", "fix_text", "check_codes",
    "validate", "import", "package", "user_final_ok",
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"engine": None, "gates": {}, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def set_engine(path: Path, match: dict[str, Any]) -> None:
    st = load_state(path)
    st["engine"] = match
    save_state(path, st)


def mark_gate(path: Path, gate: str, ok: bool, summary: str = "") -> None:
    st = load_state(path)
    st.setdefault("gates", {})[gate] = {"ok": ok, "at": _now(), "summary": summary}
    st.setdefault("history", []).append({"gate": gate, "ok": ok, "at": _now(), "summary": summary})
    save_state(path, st)


def gate_ok(path: Path, gate: str) -> bool:
    return bool(load_state(path).get("gates", {}).get(gate, {}).get("ok"))


def format_state(state: dict[str, Any]) -> str:
    eng = state.get("engine") or {}
    lines = [f"引擎: {eng.get('engine', '未辨識')} {eng.get('variant', '')}  "
             f"編碼 {eng.get('source_encoding', '?')}→{eng.get('target_encoding', '?')}"]
    gates = state.get("gates", {})
    for g in GATES:
        info = gates.get(g)
        if info is None:
            mark = "[ ]"
        else:
            mark = "[✓]" if info.get("ok") else "[✗]"
        extra = f"  {info.get('at')}  {info.get('summary', '')}" if info else ""
        lines.append(f"  {mark} {g:<14}{extra}")
    return "\n".join(lines)
