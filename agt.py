#!/usr/bin/env python3
"""agt — GalTransl-Agent-Tools 的薄 CLI。

只做三件事：把步驟分派給引擎轉接器、記錄 projects/<game>/agt.json 的關卡狀態、
把「必須依序通過的關卡」串成 `agt gates`。每一步都會印出底層 vendored 腳本的完整指令，
可以直接複製到 shell 重跑。

    PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python
    $PY agt.py engines
    $PY agt.py detect <遊戲目錄>
    $PY agt.py init <game> --original <遊戲目錄>
    $PY agt.py gates <game>            # prepare → roundtrip → export → zero-import → verify → breakage
    $PY agt.py status <game>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core import codes, config, merge, registry, script_json, state  # noqa: E402
from core.adapter import EngineAdapter, EngineMatch, Project, StepResult  # noqa: E402
from core.profile import load_profile  # noqa: E402

GATE_SEQUENCE = ("prepare", "roundtrip", "export", "zero_import", "verify", "breakage")


# -- 共用 -------------------------------------------------------------------

def _project(name: str) -> Project:
    p = Project.from_name(name)
    if not p.root.exists():
        sys.exit(f"專案 {name} 不存在：{p.root}（先 agt init）")
    return p


def _adapter(p: Project) -> tuple[EngineAdapter, EngineMatch]:
    m = p.match()
    if m is None:
        sys.exit(f"{p.name} 尚未辨識引擎（agt init 或 agt detect 後用 --engine 指定）")
    return registry.get(m.engine, config.python_stdlib()), m


def _finish(p: Project, gate: str, r: StepResult) -> int:
    state.mark_gate(p.state_path, gate, r.ok, r.summary)
    print(f"{'✓' if r.ok else '✗'} {gate}: {r.summary.splitlines()[-1] if r.summary else ''}")
    if r.log_path:
        print(f"  log: {r.log_path}")
    return 0 if r.ok else 1


def _script(p: Project, arg: str | None) -> Path:
    s = Path(arg) if arg else p.script
    if not s.exists():
        sys.exit(f"找不到 {s}（先 agt export）")
    return s


def _profile_for(p: Project):
    side = script_json.load_sidecar(p.script) if p.script.exists() else None
    if side and side.get("engine"):
        return load_profile(side["engine"])
    m = p.match()
    return load_profile(m.engine) if m else None


# -- 子命令 -----------------------------------------------------------------

def cmd_engines(_a) -> int:
    for name in registry.engine_names():
        prof = load_profile(name)
        print(f"{name:<18} {prof.display_name}  變體: {', '.join(prof.variants) or '-'}  別名: {', '.join(prof.aliases)}")
    return 0


def cmd_detect(a) -> int:
    matches = registry.detect(Path(a.dir))
    if not matches:
        print("沒有任何引擎認得這個目錄。看 docs/engines.md 的特徵表，可能需要新的轉接器（/new-adapter）。")
        return 1
    for m in matches:
        print(f"{m.engine:<18} 信心 {m.confidence:.2f}  變體 {m.variant or '-'}  "
              f"編碼 {m.source_encoding}→{m.target_encoding}")
        for e in m.evidence:
            print(f"    - {e}")
    return 0 if matches[0].confidence >= registry.MIN_CONFIDENCE else 1


def cmd_init(a) -> int:
    p = Project.from_name(a.game)
    original = Path(a.original).resolve()
    if not original.exists():
        sys.exit(f"原始遊戲目錄不存在：{original}")
    p.ensure_dirs()
    if p.original.is_symlink() or p.original.exists():
        if p.original.is_symlink():
            p.original.unlink()
        elif not any(p.original.iterdir()):
            p.original.rmdir()
        else:
            sys.exit(f"{p.original} 已存在且非空，不覆蓋")
    p.original.symlink_to(original)
    print(f"projects/{a.game}/original → {original}")
    if a.engine:
        cls = registry.load_adapter_class(a.engine)
        m = cls.detect(original) or EngineMatch(engine=a.engine, confidence=1.0, evidence=["使用者指定"])
        m.engine = a.engine
    else:
        m = registry.best(original)
        if m is None:
            state.save_state(p.state_path, {"engine": None, "gates": {}, "history": []})
            print("無法自動辨識引擎。用 agt detect 看證據，或 agt init --engine <name> 指定。")
            return 1
    if a.variant:
        m.variant = a.variant
        v = load_profile(m.engine).variant(a.variant)
        m.source_encoding = v.get("source_encoding", m.source_encoding)
        m.target_encoding = v.get("target_encoding", m.target_encoding)
    state.set_engine(p.state_path, m.to_dict())
    print(f"引擎: {m.engine} {m.variant}  編碼 {m.source_encoding}→{m.target_encoding}")
    for e in m.evidence:
        print(f"    - {e}")
    return 0


def cmd_step(a) -> int:
    p = _project(a.game)
    ad, m = _adapter(p)
    step = a.command
    if step == "prepare":
        return _finish(p, "prepare", ad.prepare(p, m))
    if step == "roundtrip":
        return _finish(p, "roundtrip", ad.roundtrip(p))
    if step == "export":
        prev = None
        if a.merge:
            prev = script_json.load(Path(a.merge))
        if p.script.exists() and not a.merge:
            backup = p.exported / f"script.backup-{__import__('datetime').datetime.now():%Y%m%d-%H%M%S}.json"
            backup.write_bytes(p.script.read_bytes())
            print(f"既有 script.json 已備份到 {backup.name}")
        r = ad.export(p)
        if r.ok and prev is not None:
            data = script_json.load(p.script)
            carried, dropped = merge.by_location(data["strings"], prev["strings"])
            script_json.save(data, p.script)
            r.summary += f"；--merge 接續 {carried} 條舊譯文，{dropped} 條對不上"
            print(r.summary)
        return _finish(p, "export", r)
    if step == "zero-import":
        return _finish(p, "zero_import", ad.zero_import(p))
    if step == "validate":
        return _finish(p, "validate", ad.validate(p, _script(p, a.script)))
    if step == "check-codes":
        return _finish(p, "check_codes", run_check_codes(p, _script(p, a.script)))
    if step == "import":
        s = _script(p, a.script)
        if not a.skip_code_check:
            r = run_check_codes(p, s)
            state.mark_gate(p.state_path, "check_codes", r.ok, r.summary)
            if not r.ok:
                print("✗ 控制碼檢查有必須處理的問題，拒絕導入（先跑 tools/fix_text.py，或 --skip-code-check）")
                return 1
        return _finish(p, "import", ad.import_(p, s))
    if step == "verify":
        return _finish(p, "verify", ad.verify(p))
    if step == "breakage":
        return _finish(p, "breakage", ad.breakage_test(p))
    if step == "package":
        r = ad.package(p)
        rc = _finish(p, "package", r)
        if r.ok and not state.gate_ok(p.state_path, "user_boot_ok"):
            state.mark_gate(p.state_path, "smoke_build", True, "package 完成，等使用者實機開啟後 agt mark <game> user_boot_ok")
            print("→ 這是 smoke build：請把 out/ 交給使用者實機開啟，確認後 `agt mark", p.name, "user_boot_ok`")
        return rc
    sys.exit(f"未知步驟 {step}")


def run_check_codes(p: Project, script: Path) -> StepResult:
    prof = _profile_for(p)
    if prof is None:
        return StepResult(ok=False, summary="找不到 profile（沒有 sidecar 也沒有引擎）")
    data = script_json.load(script)
    s = codes.report(prof, data["strings"])
    text = codes.format_summary(s)
    print(text)
    return StepResult(ok=s.fatal == 0, summary=text.splitlines()[0])


def cmd_gates(a) -> int:
    p = _project(a.game)
    ad, m = _adapter(p)
    runners = {
        "prepare": lambda: ad.prepare(p, m),
        "roundtrip": lambda: ad.roundtrip(p),
        "export": lambda: ad.export(p),
        "zero_import": lambda: ad.zero_import(p),
        "verify": lambda: ad.verify(p) if p.translated.exists() and any(p.translated.iterdir())
        else _verify_via_zero(ad, p),
        "breakage": lambda: ad.breakage_test(p),
    }
    for gate in GATE_SEQUENCE:
        print(f"\n===== 關卡 {gate} =====")
        rc = _finish(p, gate, runners[gate]())
        if rc:
            print(f"\n關卡 {gate} 失敗，停止。修好後重跑 agt gates {a.game}。")
            return rc
    print("\n前六道關卡全過。下一步：smoke build（tools/translate.py --limit 20 → fix_text → check-codes → import → package），")
    print("交給使用者實機開啟後 `agt mark <game> user_boot_ok`，才可以大量翻譯。")
    print(state.format_state(state.load_state(p.state_path)))
    return 0


def _verify_via_zero(ad: EngineAdapter, p: Project) -> StepResult:
    """gates 階段還沒有譯文：用零翻譯導入到 translated，再跑 verify。"""
    blank = p.exported / ".zero.json"
    script_json.save(script_json.blank_translations(script_json.load(p.script)), blank)
    try:
        r = ad.import_(p, blank)
        if not r.ok:
            return r
        return ad.verify(p)
    finally:
        blank.unlink(missing_ok=True)


def cmd_mark(a) -> int:
    p = _project(a.game)
    if a.gate not in state.GATES:
        sys.exit(f"未知關卡 {a.gate}；可用：{', '.join(state.GATES)}")
    state.mark_gate(p.state_path, a.gate, not a.failed, a.note or "由使用者確認")
    print(state.format_state(state.load_state(p.state_path)))
    return 0


def cmd_status(a) -> int:
    p = _project(a.game)
    print(f"專案 {p.name}  ({p.root})")
    print(state.format_state(state.load_state(p.state_path)))
    if p.script.exists():
        print("\n" + script_json.format_stats(script_json.load(p.script)))
    return 0


# -- 入口 -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("engines", help="列出已接入的引擎").set_defaults(func=cmd_engines)

    s = sub.add_parser("detect", help="辨識遊戲目錄的引擎")
    s.add_argument("dir")
    s.set_defaults(func=cmd_detect)

    s = sub.add_parser("init", help="建立 projects/<game>/ 並辨識引擎")
    s.add_argument("game")
    s.add_argument("--original", required=True, help="原始遊戲目錄（會做 symlink）")
    s.add_argument("--engine", help="強制指定引擎名稱")
    s.add_argument("--variant", help="強制指定變體（2.x/3.x/MV/MZ）")
    s.set_defaults(func=cmd_init)

    for step, help_ in (("prepare", "解包／定位資料樹"), ("roundtrip", "往返驗證（硬性關卡）"),
                        ("export", "導出 script.json"), ("zero-import", "零翻譯導入必須與原始資料相同"),
                        ("validate", "譯文檢查"), ("check-codes", "控制碼硬關卡"),
                        ("import", "導入譯文到 translated/"), ("verify", "結構驗證"),
                        ("breakage", "刻意破壞必須被攔下"), ("package", "打包到 out/")):
        s = sub.add_parser(step, help=help_)
        s.add_argument("game")
        if step in ("validate", "check-codes", "import"):
            s.add_argument("script", nargs="?", help="預設 exported/script.json")
        if step == "export":
            s.add_argument("--merge", metavar="PREV.json", help="以 (source_file, location) 接續舊譯文")
        if step == "import":
            s.add_argument("--skip-code-check", action="store_true")
        s.set_defaults(func=cmd_step)

    s = sub.add_parser("gates", help="依序跑前六道關卡，任一失敗即停")
    s.add_argument("game")
    s.set_defaults(func=cmd_gates)

    s = sub.add_parser("mark", help="記錄使用者實機確認（例如 user_boot_ok）")
    s.add_argument("game")
    s.add_argument("gate")
    s.add_argument("--failed", action="store_true")
    s.add_argument("--note")
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("status", help="關卡狀態與翻譯進度")
    s.add_argument("game")
    s.set_defaults(func=cmd_status)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
