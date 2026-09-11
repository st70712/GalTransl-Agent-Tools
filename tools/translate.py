#!/usr/bin/env python3
"""統一翻譯驅動：把 script.json 送到本機 Sakura 模型（llama-server，OpenAI 相容 API）翻譯。

母本是 GalTransl-sister/translate_wolf.py；引擎相關的常數（context 優先級／預設跳過、控制碼正則）
全部改讀 engines/<engine>/profile.json，所以同一支程式可以翻任何引擎導出的 script.json。

    PY_NLLB=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python
    $PY_NLLB tools/translate.py -i projects/<game>/exported/script.json --dry-run          # 只看統計，不連線
    $PY_NLLB tools/translate.py -i projects/<game>/exported/script.json --limit 20         # smoke build 用
    $PY_NLLB tools/translate.py -i projects/<game>/exported/script.json                    # 大量翻譯（需 user_boot_ok）

與 translate_wolf.py 的差異：
* 檢查點 .agt_checkpoint.json 以 (source_file, location) 為鍵並記錄原文，重新導出後不會錯位；
  發現舊式 .script_checkpoint.json（位置序號鍵）會拒絕執行。
* 失敗哨兵改判 GalTransl 真正的寫法（trans_by 以 "(Failed)" 結尾），失敗句留空不寫入。
* 每行日誌有時間戳，每批印吞吐與 ETA；--log 同步寫檔。
* 開跑前先打 /health；--dry-run 不 import GalTransl、不連線。
* 找到 projects/<game>/agt.json 且尚未 user_boot_ok 時，沒給 --limit 就拒絕大量翻譯（--force 越過）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core import codes, config, jp, script_json, state  # noqa: E402
from core.profile import EngineProfile, load_profile  # noqa: E402

CHECKPOINT_NAME = ".agt_checkpoint.json"
LEGACY_CHECKPOINT = ".script_checkpoint.json"
FAILED_MARK = "(Failed)"
MODEL_CHOICES = ("galtransl-v3", "sakura-v1.0")


# -- 日誌 ---------------------------------------------------------------------

class Log:
    def __init__(self, path: Path | None):
        self.path = path
        self.fh = path.open("a", encoding="utf-8") if path else None
        if self.fh:
            self.fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} translate.py =====\n")

    def __call__(self, msg: str = "") -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}" if msg else ""
        print(line, flush=True)
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()

    def close(self) -> None:
        if self.fh:
            self.fh.close()


# -- 端點 ---------------------------------------------------------------------

def check_endpoint(endpoint: str, log: Log) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/health", timeout=3) as r:
            body = r.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError) as e:
        log(f"✗ 連不上 {endpoint}/health：{e}")
        log("  先啟動模型伺服器：bash tools/llama_server.sh start")
        return False
    log(f"✓ {endpoint}/health → {body}")
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/v1/models", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        names = [m.get("id", "?") for m in data.get("data", [])]
        log(f"  模型: {', '.join(names) or '?'}")
    except Exception:
        pass
    return True


# -- 翻譯器 -------------------------------------------------------------------

class ScriptTranslator:
    def __init__(self, profile: EngineProfile, input_file: Path, output_file: Path | None,
                 endpoint: str, model_type: str, batch_size: int, dict_files: list[str],
                 skip_translated: bool, skip_contexts: set[str] | None, include_optional: bool,
                 priority_threshold: int, target_encoding: str, limit: int, dry_run: bool,
                 log: Log, galtransl_root: str, ignore_legacy_checkpoint: bool = False,
                 entry_filter: str | None = None):
        self.profile = profile
        self.input_file = input_file
        self.output_file = output_file or input_file
        self.checkpoint_file = input_file.parent / CHECKPOINT_NAME
        self.endpoint = endpoint
        self.model_type = model_type
        self.batch_size = batch_size
        self.dict_files = dict_files
        self.skip_translated = skip_translated
        self.priority_threshold = priority_threshold
        self.target_encoding = target_encoding
        self.limit = limit
        self.dry_run = dry_run
        self.log = log
        self.galtransl_root = galtransl_root
        self.ignore_legacy_checkpoint = ignore_legacy_checkpoint
        self.entry_filter = re.compile(entry_filter) if entry_filter else None

        self.skip_contexts = set(skip_contexts) if skip_contexts is not None else profile.default_skip_contexts()
        if not include_optional:
            self.skip_contexts |= profile.optional_contexts()
        self.counterpart_contexts = profile.counterpart_contexts()
        self.stats: dict[str, Any] = {"total": 0, "translated": 0, "skipped": 0, "failed": 0,
                                      "cached": 0, "by_context": {}}
        self._duplicates: dict[str, list[dict]] = {}
        self._shared_originals: set[str] = set()

    # -- GalTransl 專案設定 -----------------------------------------------

    def _create_config(self) -> Path:
        config_dir = self.input_file.parent / ".galtransl"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.yaml").write_text(f"""# 由 tools/translate.py 產生（每次執行覆寫）
backendSpecific:
  SakuraLLM:
    endpoints:
      - {self.endpoint}
    rewriteModelName: ""

plugin:
  filePlugin: file_galtransl_json
  textPlugins:
    - text_common_normalfix

proxy:
  enableProxy: false
  proxies:
    - address: ""
      username: ""
      password: ""

dictionary:
  defaultDictFolder: "dict"
  usePreDic: false
  usePostDic: false
  preDict: []
  postDict: []
  gpt.dict: []

problemAnalyze:
  GPT35: []
  arinashiDict: {{}}

common:
  gpt.numPerRequestTranslate: {self.batch_size}
  workersPerProject: 1
  sortBy: "name"
  language: "zh-tw"
  splitFile: "no"
  save_steps: 1
  linebreakSymbol: "auto"
  skipH: false
""", encoding="utf-8")
        return config_dir

    # -- 檢查點 -------------------------------------------------------------

    @staticmethod
    def key(entry: dict) -> str:
        return f"{entry['source_file']}\t{entry['location']}"

    def load_checkpoint(self) -> dict[str, dict[str, str]]:
        legacy = self.input_file.parent / LEGACY_CHECKPOINT
        if legacy.exists() and not self.ignore_legacy_checkpoint:
            self.log(f"✗ 發現舊式檢查點 {legacy}（以位置序號為鍵）。")
            self.log("  重新導出後條目數一變它就會把譯文寫錯位（2026-07-15 Angle 專案 545 條錯位事故）。")
            self.log("  請確認不需要後刪掉它，或加 --ignore-legacy-checkpoint 略過。")
            raise SystemExit(3)
        if not self.checkpoint_file.exists():
            return {}
        try:
            data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if data.get("version") != 2 or data.get("engine") != self.profile.name:
            self.log(f"⚠️ 檢查點版本／引擎不符（{data.get('version')}/{data.get('engine')}），忽略")
            return {}
        return data.get("entries", {})

    def save_checkpoint(self, entries: dict[str, dict[str, str]]) -> None:
        tmp = self.checkpoint_file.with_suffix(".tmp")
        payload = {"version": 2, "engine": self.profile.name,
                   "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "entries": entries}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.checkpoint_file)

    # -- 篩選 ---------------------------------------------------------------

    def priority(self, context: str) -> int:
        return self.profile.priority(context)

    def should_translate(self, entry: dict) -> bool:
        if self.skip_translated and entry.get("translated"):
            return False
        ctx = entry.get("context", "")
        if ctx in self.skip_contexts:
            return False
        if self.priority(ctx) > self.priority_threshold:
            return False
        if not jp.is_japanese_text(entry.get("original", ""), self.profile.codes.any_re):
            return False
        # 例如 Wolf 的 condition：只有同一段原文也出現在其他 context，翻譯記憶才能保證兩邊一致
        if ctx in self.counterpart_contexts and entry["original"] not in self._shared_originals:
            return False
        return True

    def _build_shared_originals(self, strings: list[dict]) -> set[str]:
        return {e["original"] for e in strings
                if e.get("context") not in self.counterpart_contexts and e.get("original")}

    # -- 控制碼 -------------------------------------------------------------

    def split_leading_codes(self, text: str) -> tuple[str, str]:
        m = self.profile.codes.leading_re.match(text)
        if not m or not m.group(0):
            return "", text
        return m.group(0), text[m.end():]

    # -- 翻譯 ---------------------------------------------------------------

    @staticmethod
    def _failed(sent: Any) -> bool:
        post = getattr(sent, "post_zh", "") or ""
        by = getattr(sent, "trans_by", "") or ""
        return (not post) or by.endswith(FAILED_MARK) or post.startswith(FAILED_MARK)

    async def translate_batch(self, translator: Any, entries: list[dict], gpt_dict: Any,
                              backend: dict[str, Any]) -> list[dict]:
        if not entries:
            return entries
        CSentense, CTransList = backend["CSentense"], backend["CTransList"]
        trans_list = CTransList()
        prefixes: list[str] = []
        for i, entry in enumerate(entries):
            prefix, body = self.split_leading_codes(entry["original"])
            prefixes.append(prefix)
            trans_list.append(CSentense(pre_jp=body, speaker=entry.get("speaker", "") or "", index=i))
        gpt_dict_content = gpt_dict.gen_prompt(trans_list, type="sakura") if gpt_dict else ""
        try:
            _num, result_list = await translator.translate(
                trans_list=trans_list, gptdict=gpt_dict_content, filename="agt_translation")
        except Exception as e:  # GalTransl 內部已重試多次；這裡只記錄，整批留空下次再來
            self.log(f"  ⚠️ 批量翻譯出錯: {e!r}")
            return entries
        for i, sent in enumerate(result_list):
            if not self._failed(sent):
                entries[i]["translated"] = prefixes[i] + sent.post_zh
        return entries

    def _load_backend(self) -> dict[str, Any]:
        root = self.galtransl_root
        if not (Path(root) / "GalTransl").is_dir():
            raise SystemExit(f"GALTRANSL_ROOT={root} 底下沒有 GalTransl 套件；設定環境變數 GALTRANSL_ROOT 或 config.yaml 的 galtransl_root")
        if root not in sys.path:
            sys.path.insert(0, root)
        from GalTransl.Backend.SakuraTranslate import CSakuraTranslate  # type: ignore
        from GalTransl.ConfigHelper import CProjectConfig  # type: ignore
        from GalTransl.CSentense import CSentense, CTransList  # type: ignore
        from GalTransl.Dictionary import CGptDict  # type: ignore
        return {"CSakuraTranslate": CSakuraTranslate, "CProjectConfig": CProjectConfig,
                "CSentense": CSentense, "CTransList": CTransList, "CGptDict": CGptDict}

    # -- 主流程 -------------------------------------------------------------

    async def run(self) -> int:
        log = self.log
        log("=" * 70)
        log(f"🌸 translate.py  引擎 profile: {self.profile.name}（{self.profile.display_name}）"
            + ("  [DRY-RUN]" if self.dry_run else ""))
        log(f"輸入: {self.input_file}   輸出: {self.output_file}")
        log(f"端點: {self.endpoint}   模型: {self.model_type}   批次: {self.batch_size}   目標編碼: {self.target_encoding}")
        log(f"跳過 context: {', '.join(sorted(self.skip_contexts)) or '無'}   優先級門檻: {self.priority_threshold}")
        log("=" * 70)

        data = script_json.load(self.input_file)
        info, strings = data["info"], data["strings"]
        self.stats["total"] = len(strings)
        log(f"📖 {info.get('game_title', '?')}：{len(strings)} 條")

        checkpoint = self.load_checkpoint()
        restored = 0
        for e in strings:
            saved = checkpoint.get(self.key(e))
            if saved and saved.get("o") == e["original"] and not e.get("translated"):
                e["translated"] = saved["t"]
                restored += 1
        if checkpoint:
            log(f"   檢查點: {len(checkpoint)} 條，其中 {restored} 條套回（原文不同的已忽略）")
        self.stats["cached"] = restored

        self._shared_originals = self._build_shared_originals(strings)

        memory: dict[str, str] = {}
        for e in strings:
            if e.get("translated") and e.get("original"):
                memory.setdefault(e["original"], e["translated"])
        if memory:
            log(f"   翻譯記憶: {len(memory)} 組原文")

        pending = [e for e in strings if self.should_translate(e)]
        if self.entry_filter:
            pending = [e for e in pending if self.entry_filter.search(f"{e['source_file']}#{e['location']}")]
            log(f"   --filter {self.entry_filter.pattern!r}：篩到 {len(pending)} 條")
        reused = 0
        to_translate: list[dict] = []
        seen: set[str] = set()
        for e in pending:
            o = e["original"]
            if o in memory:
                e["translated"] = memory[o]
                checkpoint[self.key(e)] = {"o": o, "t": memory[o]}
                reused += 1
                continue
            if o in seen:
                self._duplicates.setdefault(o, []).append(e)
                continue
            seen.add(o)
            to_translate.append(e)
        if self.limit:
            to_translate = to_translate[:self.limit]
            log(f"   ⚠️ 測試模式：只送前 {self.limit} 條")
        deduped = sum(len(v) for v in self._duplicates.values())
        self.stats["skipped"] = len(strings) - len(pending) - self.stats["cached"]
        log(f"   待處理 {len(pending)} | 記憶命中 {reused} | 重複原文 {deduped} | 實際送模型 {len(to_translate)}")

        groups: dict[str, list[dict]] = {}
        for e in to_translate:
            groups.setdefault(e.get("context", "unknown"), []).append(e)
        ordered = sorted(groups, key=lambda c: (self.priority(c), c))
        log("   📊 待翻譯分布:")
        for c in ordered:
            log(f"      [{self.priority(c):2d}] {c}: {len(groups[c])}")

        if self.dry_run:
            log("")
            log("🔍 dry-run：前幾條的「開頭控制碼／本文」拆分（開頭碼不送模型，翻完接回）")
            for e in to_translate[:max(self.limit, 10) if self.limit else 10]:
                prefix, body = self.split_leading_codes(e["original"])
                log(f"   [{e['index']}] {e.get('context')}  prefix={prefix!r}  body={body[:60]!r}")
            log("dry-run 結束，未寫入任何檔案。")
            return 0

        if not to_translate:
            log("✅ 沒有需要翻譯的條目")
            self._finish(data, strings, checkpoint, propagated=0)
            return 0

        if not check_endpoint(self.endpoint, log):
            return 2

        log("⚙️ 載入 GalTransl 後端...")
        backend = self._load_backend()
        config_dir = self._create_config()
        cfg = backend["CProjectConfig"](str(config_dir))
        gpt_dict = None
        valid = [f for f in self.dict_files if Path(f).exists()]
        if valid:
            gpt_dict = backend["CGptDict"](valid)
            log(f"   字典: {', '.join(valid)}")
        elif self.dict_files:
            log(f"   ⚠️ 字典檔不存在，跳過: {self.dict_files}")
        translator = backend["CSakuraTranslate"](config=cfg, eng_type=self.model_type,
                                                 endpoint=self.endpoint, proxy_pool=None)
        log("   ✅ 翻譯器就緒")
        log("🚀 開始翻譯")

        done = 0
        total = len(to_translate)
        t0 = time.monotonic()
        for ctx in ordered:
            ctx_entries = groups[ctx]
            log(f"📂 [{ctx}] 優先級 {self.priority(ctx)}，共 {len(ctx_entries)} 條")
            btot = (len(ctx_entries) + self.batch_size - 1) // self.batch_size
            for start in range(0, len(ctx_entries), self.batch_size):
                batch = ctx_entries[start:start + self.batch_size]
                bno = start // self.batch_size + 1
                batch = await self.translate_batch(translator, batch, gpt_dict, backend)
                for e in batch:
                    counts = self.stats["by_context"].setdefault(e.get("context", "?"), {"success": 0, "failed": 0})
                    if e.get("translated"):
                        checkpoint[self.key(e)] = {"o": e["original"], "t": e["translated"]}
                        self.stats["translated"] += 1
                        counts["success"] += 1
                        rep = codes.check_entry(self.profile, e["original"], e["translated"])
                        if rep.fatal:
                            log(f"      ⚠️ [{e['index']}] {'; '.join(rep.problems)}")
                    else:
                        self.stats["failed"] += 1
                        counts["failed"] += 1
                self.save_checkpoint(checkpoint)
                done += len(batch)
                elapsed = time.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                eta = (total - done) / rate if rate > 0 else 0.0
                preview = (batch[0].get("translated") or "(失敗)")[:44].replace("\n", "\\n")
                log(f"   [{ctx} {bno}/{btot}] 累計 {done}/{total} ({done / total:.1%})  "
                    f"{rate:.2f} 條/s  ETA {int(eta // 60):02d}:{int(eta % 60):02d}  例: {preview}")
                await asyncio.sleep(0.2)

        # 把代表句的譯文擴散到所有相同原文的條目（保證 condition 與對應方一致）
        final_memory: dict[str, str] = {}
        for e in strings:
            if e.get("translated") and e.get("original"):
                final_memory.setdefault(e["original"], e["translated"])
        propagated = 0
        for o, dups in self._duplicates.items():
            t = final_memory.get(o)
            if not t:
                continue
            for e in dups:
                if not e.get("translated"):
                    e["translated"] = t
                    checkpoint[self.key(e)] = {"o": o, "t": t}
                    propagated += 1
        if propagated:
            self.save_checkpoint(checkpoint)
        elapsed = time.monotonic() - t0
        log(f"⏱ 模型時間 {elapsed / 60:.1f} 分，平均 {total / elapsed if elapsed else 0:.2f} 條/s")
        self._finish(data, strings, checkpoint, propagated)
        return 0

    def _finish(self, data: dict, strings: list[dict], checkpoint: dict, propagated: int) -> None:
        log = self.log
        if propagated:
            log(f"🔁 相同原文擴散: {propagated} 條")
        data["info"]["string_count"] = len(strings)
        script_json.save(data, self.output_file)
        log(f"💾 已儲存 {self.output_file}")
        s = self.stats
        log(f"📊 總 {s['total']} | 新翻譯 {s['translated']} | 檢查點 {s['cached']} | 跳過 {s['skipped']} | 失敗 {s['failed']}")
        for ctx, c in sorted(s["by_context"].items(), key=lambda kv: self.priority(kv[0])):
            log(f"      {ctx}: ✓{c['success']} ✗{c['failed']}")

        bad: list[tuple[dict, str]] = []
        for e in strings:
            t = e.get("translated")
            if not t:
                continue
            try:
                t.encode(self.target_encoding)
            except UnicodeEncodeError as exc:
                bad.append((e, t[exc.start:exc.end]))
        if bad:
            log(f"🔤 {self.target_encoding} 編碼檢查：{len(bad)} 條含無法編碼的字元（fix_text.py 會處理／報告）")
            for e, ch in bad[:10]:
                log(f"      [{e['index']}] {ch!r} in {e['translated'][:40]!r}")
        else:
            log(f"🔤 {self.target_encoding} 編碼檢查：✅ 全部可寫回")

        summary = codes.report(self.profile, strings)
        for line in codes.format_summary(summary, show_examples=3).splitlines():
            log(line)
        if summary.fatal:
            log(f"➡ 下一步：tools/fix_text.py 會把 {summary.fatal} 條必須處理的退回原文；再 tools/check_codes.py 確認 0 條")


# -- CLI ------------------------------------------------------------------------

def resolve_profile(script: Path, engine: str | None) -> tuple[EngineProfile, dict | None]:
    side = script_json.load_sidecar(script)
    if engine:
        return load_profile(engine), side
    if side and side.get("engine"):
        return load_profile(side["engine"]), side
    info = json.loads(script.read_text(encoding="utf-8")).get("info", {})
    if info.get("engine"):
        try:
            return load_profile(info["engine"]), side
        except FileNotFoundError:
            pass
    raise SystemExit("無法決定引擎：加 --engine <name>，或確認 exported/.agt.json sidecar 存在")


def find_project_state(script: Path) -> Path | None:
    cand = script.resolve().parent.parent / "agt.json"
    return cand if cand.exists() else None


def main(argv: list[str] | None = None) -> int:
    cfg = config.load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", required=True, type=Path, help="script.json")
    ap.add_argument("-o", "--output", type=Path, help="輸出（預設覆蓋輸入）")
    ap.add_argument("--engine", help="引擎名（預設從 exported/.agt.json 或 info.engine 推斷）")
    ap.add_argument("-e", "--endpoint", default=cfg["endpoint"])
    ap.add_argument("-m", "--model", default="galtransl-v3", choices=MODEL_CHOICES)
    ap.add_argument("-b", "--batch-size", type=int, default=16)
    ap.add_argument("--dict", nargs="*", default=[], help="GPT 字典檔（原文->譯文 // 備註）；projects/<game>/glossary.txt 會自動加入")
    ap.add_argument("--priority", type=int, default=99, help="只翻優先級 <= 此值的 context")
    ap.add_argument("--include-optional", action="store_true", help="一併翻 profile 標為 optional 的 context")
    ap.add_argument("--skip-contexts", nargs="*", help="要跳過的 context（取代 profile 預設）")
    ap.add_argument("--no-skip-translated", action="store_true", help="已有譯文的也重翻")
    ap.add_argument("--target-encoding", help="結尾編碼檢查用（預設 sidecar / info.encoding / utf-8）")
    ap.add_argument("--limit", type=int, default=0, help="只送前 N 條（smoke build 用）")
    ap.add_argument("--filter", help="只處理 source_file#location 符合此正則的條目（例如 Data_Event，讓 smoke build 落在開場）")
    ap.add_argument("--dry-run", action="store_true", help="只印統計與拆分，不連線、不寫檔")
    ap.add_argument("--log", type=Path, help="同步寫入的 log 檔（專案佈局下預設 projects/<game>/logs/translate-<ts>.log）")
    ap.add_argument("--force", action="store_true", help="尚未 user_boot_ok 也允許大量翻譯")
    ap.add_argument("--ignore-legacy-checkpoint", action="store_true")
    args = ap.parse_args(argv)

    if not args.input.exists():
        sys.exit(f"找不到 {args.input}")
    profile, side = resolve_profile(args.input, args.engine)
    target_encoding = args.target_encoding or (side or {}).get("target_encoding") \
        or json.loads(args.input.read_text(encoding="utf-8")).get("info", {}).get("encoding") or "utf-8"

    log_path = args.log
    state_path = find_project_state(args.input)
    if log_path is None and state_path is not None:
        logs_dir = state_path.parent / "logs"
        if logs_dir.is_dir() and not args.dry_run:
            log_path = logs_dir / f"translate-{datetime.now():%Y%m%d-%H%M%S}.log"
    log = Log(log_path)

    dict_files = list(args.dict)
    if state_path is not None:
        glossary = state_path.parent / "glossary.txt"
        if glossary.exists() and str(glossary) not in dict_files:
            dict_files.append(str(glossary))

    if state_path is not None and not args.dry_run and not args.limit and not args.force:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        if not st.get("gates", {}).get("user_boot_ok", {}).get("ok"):
            log("✗ 這個專案還沒有通過實機開啟確認（agt.json gates.user_boot_ok）。")
            log("  先做 smoke build：--limit 20 → fix_text → check_codes → agt import/verify/package → 請使用者實機開啟")
            log("  → 確認後 `agt mark <game> user_boot_ok`。真的要直接大量翻譯請加 --force。")
            return 4

    tr = ScriptTranslator(
        profile=profile, input_file=args.input, output_file=args.output, endpoint=args.endpoint,
        model_type=args.model, batch_size=args.batch_size, dict_files=dict_files,
        skip_translated=not args.no_skip_translated,
        skip_contexts=set(args.skip_contexts) if args.skip_contexts is not None else None,
        include_optional=args.include_optional, priority_threshold=args.priority,
        target_encoding=target_encoding, limit=args.limit, dry_run=args.dry_run, log=log,
        galtransl_root=os.environ.get("GALTRANSL_ROOT") or cfg["galtransl_root"],
        ignore_legacy_checkpoint=args.ignore_legacy_checkpoint, entry_filter=args.filter,
    )
    try:
        rc = asyncio.run(tr.run())
        if state_path is not None and not args.dry_run:
            note = f"limit={args.limit}" if args.limit else "大量翻譯"
            state.mark_gate(state_path, "translate", rc == 0,
                            f"{note}：新翻譯 {tr.stats['translated']}，失敗 {tr.stats['failed']}")
        return rc
    except KeyboardInterrupt:
        log("⚠️ 中斷；進度已在檢查點，重跑會接續")
        return 130
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
