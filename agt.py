#!/usr/bin/env python3
"""agt — GalTransl-Agent-Tools 的薄 CLI。

只做三件事：把步驟分派給引擎轉接器、記錄 projects/<game>/agt.json 的關卡狀態、
把「必須依序通過的關卡」串成 `agt gates`。每一步都會印出底層 vendored 腳本的完整指令，
可以直接複製到 shell 重跑。

    $PY agt.py env                     # 先看這台是實機端還是翻譯端（$PY 見 CLAUDE.md §3）
    $PY agt.py engines
    $PY agt.py detect <遊戲目錄|交接包.zip|資料夾>   # 來料判斷：遊戲 / 交接包 / 既有專案
    $PY agt.py init <game> --original <遊戲目錄>
    $PY agt.py gates <game>            # prepare → roundtrip → export → zero-import → verify → breakage
    $PY agt.py handoff pack <game>     # 兩站接力：打包交接包給另一站；unpack 收包
    $PY agt.py status <game>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core import (  # noqa: E402
    TOOLS_DIR,
    codes,
    config,
    fsutil,
    handoff,
    handoff_notes,
    merge,
    registry,
    script_json,
    site,
    state,
)
from core.adapter import (  # noqa: E402
    EngineAdapter,
    EngineMatch,
    Project,
    StepResult,
    format_cmdline,
)
from core.profile import load_profile  # noqa: E402

GATE_SEQUENCE = ("prepare", "roundtrip", "export", "zero_import", "verify", "breakage")
# 要碰 original/ 或 extracted/ 的步驟：翻譯端骨架專案（unpack 建的，沒有 original/）不能跑
NEEDS_GAME = {"prepare", "roundtrip", "export", "zero-import", "import", "verify", "breakage", "package"}


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


def _require_game(p: Project, step: str) -> None:
    if not p.original.exists():
        sys.exit(f"{step} 需要遊戲檔（original/），但 projects/{p.name}/ 沒有——這是翻譯端骨架專案。"
                 f"此步驟要在實機端跑；翻譯端只做 translate / fix_text / check-codes / validate，做完 agt handoff pack。")


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
    intake = handoff.classify(Path(a.dir))
    if intake.kind == "missing":
        sys.exit(f"路徑不存在：{intake.path}")
    if intake.kind in ("bundle_zip", "bundle_dir"):
        man = intake.manifest or {}
        print(f"這是交接包：{intake.path}")
        print(f"  專案 {man.get('game') or '?'}  seq #{man.get('seq', '?')}  "
              f"{man.get('from_site', '?')} → {man.get('to_site', '?')}  引擎 {man.get('engine') or '?'}  "
              f"打包於 {man.get('packed_at', '?')} @ {man.get('host', '?')}")
        print(f"→ $PY agt.py handoff unpack {format_cmdline([str(intake.path)])}")
        return 0
    if intake.kind == "bundle_pool":
        print(f"這個資料夾裡有 {len(intake.candidates)} 個交接包（新→舊）：")
        for c in intake.candidates[:10]:
            print(f"  {c.name}")
        print(f"→ $PY agt.py handoff unpack {format_cmdline([str(intake.path)])}   # 自動取寄給本站、seq 最大的那個")
        return 0
    if intake.kind == "project_dir":
        print(f"這是既有專案 projects/{intake.path.name}/ → $PY agt.py status {intake.path.name}")
        return 0
    if intake.kind == "game_zip":
        print(f"這是完整遊戲的壓縮檔（{'; '.join(intake.hints) or '看不出引擎'}）。")
        print("→ 先解壓到 projects/<game>/original_zip/（日文檔名用 `unzip -O cp932`），再對解開的目錄 agt detect / agt init")
        return 1
    if intake.kind == "unknown":
        print("; ".join(intake.hints))
        return 1
    if intake.hints:
        print("目錄特徵：" + "; ".join(intake.hints))
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
    try:
        kind = fsutil.replace_dir_with_link(original, p.original, rmtree_ok=False)
    except (FileExistsError, OSError) as e:
        sys.exit(str(e))
    print(f"projects/{a.game}/original → {original}（{kind}）")
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
    step = a.command
    if step in NEEDS_GAME:
        _require_game(p, step)
    ad, m = _adapter(p)
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
            if site.current_site() == "workstation":
                print(f"→ 這是 smoke build：照 out/安裝說明.txt 裝進遊戲、`agt playtest {p.name}` 抓崩潰，"
                      f"請使用者目視後 `agt mark {p.name} user_boot_ok`，再 `agt handoff pack {p.name}` 交回翻譯端")
            else:
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
    _require_game(p, "gates")
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
    if site.current_site() == "workstation":
        print(f"\n前六道關卡全過。實機端下一步：量測寫進 HANDOFF.md（含 smoke 樣本的 --filter）→ commit+push → "
              f"`agt handoff pack {a.game}` 交給翻譯端翻 20 條。")
    else:
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


def cmd_env(a) -> int:
    r = site.probe()
    if a.json:
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(site.format_report(r))
    return 0


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _print_notice(notice, peer: str) -> None:
    """印出可直接 SendMessage 的草稿；agt.py 自己永遠不送訊息（送訊息是代理的動作，受權限管）。"""
    print()
    print(handoff_notes.block(notice))
    for w in notice.warnings:
        print(f"  ! {w}")
    if peer:
        print(f"→ 用 SendMessage 把上面整段送給 {peer}"
              "（先 ListAgents 確認名字還在；找不到就把同一段交給使用者人工轉述）")
    else:
        print("→ config.local.yaml 沒設 peer_agent：把上面整段交給使用者請他轉述"
              "（設定方式見 config.local.example.yaml）")


def _handoff_notify(a, here: str) -> int:
    """重印交接通知／回報草稿。訊息送不出去時用這個——重跑 pack 會 seq+1，絕對不可以。"""
    p = _project(a.game)
    info = state.handoff_info(p.state_path)
    seq = int(info.get("seq") or 0)
    peer = config.peer_agent()
    if not seq:
        sys.exit(f"✗ {a.game} 還沒交接過（agt.json 沒有 handoff 區塊）：先 agt handoff pack {a.game}")
    if a.ack:
        _print_notice(handoff_notes.build_ack_message(
            game=p.name, seq=seq, to_site=here, created=False,
            written=int(info.get("unpacked_files") or 0), backups=int(info.get("unpacked_backups") or 0),
            sha256=str(info.get("bundle_sha256") or ""), note=a.note or "", script=str(p.script)), peer)
        return 0

    warnings: list[str] = []
    name = str(info.get("bundle") or "")
    size, sha = int(info.get("bundle_size") or 0), str(info.get("bundle_sha256") or "")
    try:
        found = handoff.resolve_bundle(a.game, site=str(info.get("holder") or "") or None)
        if name and found.name != name:
            warnings.append(f"找到的是 {found.name}，但 agt.json 記的是 {name}——確認是不是同一包")
        d = handoff.digest_bundle(found)
        name, size, sha = found.name, d.size, d.sha256
    except handoff.HandoffError as e:
        warnings.append(f"找不到交接包檔案（{e}）；用的是 pack 當時記在 agt.json 的雜湊")
    if not sha:
        sys.exit(f"✗ 沒有整包 sha256：{name or a.game} 是舊版 pack 出來的，重新 pack 一次才會記錄")

    git = handoff.repo_info()
    notice = handoff_notes.build_pack_message(
        game=p.name, seq=seq, from_site=str(info.get("from_site") or here),
        to_site=str(info.get("holder") or site.other_site(here) or "?"),
        bundle_name=name, size=size, sha256=sha, handoff_md=_read_text(p.root / "HANDOFF.md"),
        repo_branch=git.get("branch") or "", repo_head=git.get("head") or "")
    notice.warnings[:0] = warnings
    _print_notice(notice, peer)
    return 0


def _handoff_check(a, here: str) -> int:
    """唯讀驗證交接包：Drive／rclone 同步完了沒、是不是通知訊息講的那一包。"""
    filt = here if here in site.SITES else None
    try:
        src = handoff.resolve_bundle(a.target, site=filt)
        c = handoff.check_bundle(src, expect_sha256=a.expect_sha256, expect_size=a.expect_size)
    except handoff.HandoffError as e:
        sys.exit(f"✗ {e}")
    man = c.manifest or {}
    seq = man.get("seq") or (handoff.parse_bundle_name(c.path.name) or {}).get("seq", "N")
    print(f"交接包 {c.path}")
    print(f"  size {c.digest.size:,} bytes   sha256 {c.digest.sha256}")
    if man:
        print(f"  #{seq}  {man.get('from_site', '?')} → {man.get('to_site', '?')}  "
              f"專案 {man.get('game') or '?'}  引擎 {man.get('engine') or '?'}  打包於 {man.get('packed_at', '?')}")
        if man.get("repo_branch") or man.get("repo_head"):
            branch = man.get("repo_branch") or "<分支>"
            print(f"  對方 repo：{branch} @ {(man.get('repo_head') or '')[:12]}"
                  f"   ← unpack 前先 git fetch && git checkout {branch} && git pull")
    for w in c.warnings:
        print(f"  ! {w}")
    if not c.ok:
        print(f"✗ 完整性驗證沒過（{len(c.problems)} 項）：")
        for q in c.problems:
            print(f"    {q}")
        print(f"  {handoff.SYNC_HINT}")
        print(f"  要回報給對方的話：「#{seq} 還沒同步完，sha256 不符，晚點再收，先不要重 pack」。")
        return 1
    print("✓ 完整性驗證通過：整包與每個成員都對得上 manifest")
    if not (a.expect_sha256 or a.expect_size):
        print("  ! 沒給 --expect-sha256：只證明這個 zip 自己是完整的，沒證明它是通知訊息講的那一包")
    print(f"→ $PY agt.py handoff unpack {format_cmdline([str(c.path)])}")
    return 0


def cmd_handoff(a) -> int:
    here = site.current_site()
    if a.action == "pack":
        p = _project(a.game)
        to = a.to or site.other_site(here)
        if to is None:
            sys.exit("無法推斷要交給哪一站：請加 --to translator|workstation（或在 config.local.yaml 設 site）")
        try:
            r = handoff.pack(p, to, from_site=here, out_dir=Path(a.out) if a.out else None,
                             include_logs=not a.no_logs, allow_dirty=a.allow_dirty)
        except handoff.HandoffError as e:
            sys.exit(f"✗ {e}")
        print(f"✓ 交接包 #{r.seq} → {to}：{r.bundle}（{len(r.files)} 個檔案）")
        print(f"  size {r.size:,} bytes   sha256 {r.sha256}")
        if r.copied_to:
            print(f"  已複製到共用資料夾：{r.copied_to}")
            if r.copy_verified:
                print("  複本已重讀比對：size 與 sha256 都相同"
                      "（只證明本機寫入完整，**不**證明 Drive／rclone 已上傳完）")
            if r.sidecar:
                print(f"  校驗旁檔：{r.sidecar.name}（對方可 sha256sum -c）")
            print(f"  → 對方收之前應該先驗：agt handoff check {p.name} "
                  f"--expect-sha256 {r.sha256} --expect-size {r.size}")
        else:
            print("  沒有 handoff_dir：請把這個 zip 交給使用者搬到另一站（或放 config.local.yaml 的 handoff_dir）")
        for w in r.warnings:
            print(f"  ! {w}")
        print(f"→ 持棒方現在是 {to}：收到回傳包前，本站不要再改 exported/script.json")
        git = handoff.repo_info()
        _print_notice(handoff_notes.build_pack_message(
            game=p.name, seq=r.seq, from_site=here, to_site=to, bundle_name=r.bundle.name,
            size=r.size, sha256=r.sha256, handoff_md=_read_text(p.root / "HANDOFF.md"),
            repo_branch=git.get("branch") or "", repo_head=git.get("head") or ""),
            config.peer_agent())
        return 0
    if a.action == "check":
        return _handoff_check(a, here)
    if a.action == "notify":
        return _handoff_notify(a, here)
    # unpack
    try:
        r = handoff.unpack(Path(a.src), game=a.game, force=a.force, site=here if here in site.SITES else None,
                           expect_sha256=a.expect_sha256, expect_size=a.expect_size)
    except handoff.HandoffError as e:
        sys.exit(f"✗ {e}")
    p = r.project
    print(f"✓ 收到交接包 #{r.seq} → projects/{p.name}/（{'新建' if r.created else '更新'}，寫入 {len(r.files)} 個檔案）")
    for b in r.backups:
        print(f"  備份：{b}")
    for w in r.warnings:
        print(f"  ! {w}")
    print(state.format_state(state.load_state(p.state_path)))
    if (p.root / "HANDOFF.md").exists():
        print(f"→ 先讀 projects/{p.name}/HANDOFF.md 的最新一段「請對方做」")
    print(f"→ {handoff_notes.next_steps(here, p.name, str(p.script))}")
    _print_notice(handoff_notes.build_ack_message(
        game=p.name, seq=r.seq, to_site=here, created=r.created, written=len(r.files),
        backups=len(r.backups), warnings=r.warnings, script=str(p.script),
        check_ok=True if (a.expect_sha256 or a.expect_size) else None,
        sha256=a.expect_sha256 or ""), config.peer_agent())
    return 0


def cmd_playtest(a) -> int:
    cmd = [sys.executable, str(TOOLS_DIR / "playtest.py"), a.game]
    if a.exe:
        cmd += ["--exe", a.exe]
    cmd += ["--wait", str(a.wait)]
    if a.kill:
        cmd.append("--kill")
    if a.dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd)


# -- 入口 -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("engines", help="列出已接入的引擎").set_defaults(func=cmd_engines)

    s = sub.add_parser("env", help="這台機器是哪一站（實機端／翻譯端）、有哪些能力")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_env)

    s = sub.add_parser("detect", help="來料判斷：遊戲目錄→辨識引擎；交接包→提示 unpack；遊戲 zip→提示解壓")
    s.add_argument("dir", help="遊戲目錄、交接包 zip、放交接包的資料夾，或既有專案目錄")
    s.set_defaults(func=cmd_detect)

    s = sub.add_parser("init", help="建立 projects/<game>/ 並辨識引擎")
    s.add_argument("game")
    s.add_argument("--original", required=True, help="原始遊戲目錄（會做 symlink；Windows 沒權限時退回 junction）")
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

    s = sub.add_parser("handoff", help="兩站接力：pack 打包交接包給另一站 / unpack 收包（docs/two-site.md）")
    hs = s.add_subparsers(dest="action", required=True)
    hp = hs.add_parser("pack", help="打包 agt.json + exported/ + glossary + HANDOFF.md 成 zip（seq+1）")
    hp.add_argument("game")
    hp.add_argument("--to", choices=site.SITES, help="交給哪一站（預設：另一站）")
    hp.add_argument("-o", "--out", help="輸出目錄（預設 projects/<game>/handoff/）")
    hp.add_argument("--no-logs", action="store_true", help="不帶 logs/*.log")
    hp.add_argument("--allow-dirty", action="store_true", help="repo 有未提交變更也照包")
    hu = hs.add_parser("unpack", help="收交接包：合併 agt.json、覆蓋 exported/（先備份）；拒收舊 seq")
    hu.add_argument("src", help="交接包 zip、解開的目錄，或放了多個交接包的資料夾（取最新）")
    hu.add_argument("--game", help="專案名（預設用交接包 manifest 的；兩站應一致）")
    hu.add_argument("--force", action="store_true", help="seq 不比本地新也照收（只越過 seq，不會略過完整性檢查）")
    hu.add_argument("--expect-sha256", help="通知訊息裡的整包 sha256；不符就拒收")
    hu.add_argument("--expect-size", type=int, help="通知訊息裡的整包 size；不符就拒收")
    hc = hs.add_parser("check", help="唯讀驗證交接包完整性（Drive／rclone 同步完了沒）；可無限次重跑")
    hc.add_argument("target", help="遊戲名（自動找 handoff_dir）、交接包 zip，或放交接包的資料夾")
    hc.add_argument("--expect-sha256", help="通知訊息裡的整包 sha256")
    hc.add_argument("--expect-size", type=int, help="通知訊息裡的整包 size")
    hn = hs.add_parser("notify", help="重印交接通知／回報草稿（訊息送不出去時用；重跑 pack 會 seq+1）")
    hn.add_argument("game")
    hn.add_argument("--ack", action="store_true", help="產生收包回報，而不是交接通知")
    hn.add_argument("--note", help="附加一句話")
    s.set_defaults(func=cmd_handoff)

    s = sub.add_parser("playtest", help="實機端：啟動遊戲、等 N 秒、列出新的 crash.dmp／Player.log")
    s.add_argument("game")
    s.add_argument("--exe")
    s.add_argument("--wait", type=float, default=20)
    s.add_argument("--kill", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_playtest)
    return ap


def main(argv: list[str] | None = None) -> int:
    fsutil.utf8_stdio()
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
