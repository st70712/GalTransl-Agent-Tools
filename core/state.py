"""``projects/<game>/agt.json``：引擎辨識結果、關卡狀態與交接（handoff）資訊。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

GATES = (
    "prepare", "roundtrip", "export", "zero_import", "verify", "breakage",
    "smoke_build", "playtest", "user_boot_ok", "translate", "fix_text", "check_codes",
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


# -- 交接（兩站接力，docs/two-site.md）------------------------------------------

def handoff_info(path: Path) -> dict[str, Any]:
    """``handoff`` 區塊；沒交接過回傳 ``{"seq": 0}``。"""
    return dict(load_state(path).get("handoff") or {"seq": 0})


def set_handoff(path: Path, block: dict[str, Any]) -> None:
    st = load_state(path)
    st["handoff"] = block
    save_state(path, st)


def update_handoff(path: Path, fields: dict[str, Any]) -> None:
    """把 ``fields`` 併進既有的 ``handoff`` 區塊（其餘欄位不動）。"""
    st = load_state(path)
    block = dict(st.get("handoff") or {})
    block.update(fields)
    st["handoff"] = block
    save_state(path, st)


def merge_states(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """unpack 時合併兩站的 agt.json：engine／handoff 取對方的，每個關卡取時間較新的，history 聯集。"""
    out: dict[str, Any] = {**local, **incoming}
    out["engine"] = incoming.get("engine") or local.get("engine")
    gates: dict[str, Any] = {}
    lg, ig = local.get("gates") or {}, incoming.get("gates") or {}
    for g in set(lg) | set(ig):
        a, b = lg.get(g), ig.get(g)
        if a is None or b is None:
            gates[g] = b if a is None else a
        else:
            gates[g] = b if str(b.get("at", "")) >= str(a.get("at", "")) else a
    out["gates"] = {g: gates[g] for g in sorted(gates, key=lambda g: GATES.index(g) if g in GATES else 99)}
    seen: set[tuple] = set()
    hist: list[dict[str, Any]] = []
    for h in (local.get("history") or []) + (incoming.get("history") or []):
        key = (h.get("gate"), h.get("at"), h.get("ok"), h.get("summary"))
        if key not in seen:
            seen.add(key)
            hist.append(h)
    out["history"] = sorted(hist, key=lambda h: str(h.get("at", "")))
    if incoming.get("handoff"):
        out["handoff"] = incoming["handoff"]
    return out


def format_state(state: dict[str, Any]) -> str:
    eng = state.get("engine") or {}
    lines = [f"引擎: {eng.get('engine', '未辨識')} {eng.get('variant', '')}  "
             f"編碼 {eng.get('source_encoding', '?')}→{eng.get('target_encoding', '?')}"]
    ho = state.get("handoff")
    if ho:
        lines.append(f"交接: #{ho.get('seq')} 持棒 {ho.get('holder')}  {ho.get('packed_at', '')}  "
                     f"由 {ho.get('from_site', '?')}@{ho.get('packed_by', '?')}  {ho.get('bundle', '')}")
    else:
        lines.append("交接: 無（單站流程）")
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
