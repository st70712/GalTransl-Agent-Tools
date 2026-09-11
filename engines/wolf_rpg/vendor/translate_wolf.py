"""
WOLF RPG Editor JSON 翻譯工具 - 使用本地 Sakura 模型

改寫自 GalTransl/text/translate_rpgmaker.py。JSON 結構相同（info + strings），
但針對 Wolf 做了三處必要調整：

1. context 優先級改為 Wolf 的類型，並預設跳過會改變遊戲行為的 condition /
   string_var，以及玩家看不到的 debug。
2. 控制碼改用 Wolf 的精確樣式（\\cself[n] 不會被誤判成 \\c）。
3. 開頭的控制碼（\\E、\\f[n]）在送模型前先摘掉、翻完再接回去，
   不依賴模型自己保留——本遊戲 4164 條對話有 4076 條以 \\E 開頭。

另外在結束時檢查譯文能否以目標編碼（預設 cp950）寫回遊戲。
"""

import json
import re
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import sys
import argparse

GALTRANSL_ROOT = '/raid/home/jimhsieh/GalTransl'
sys.path.insert(0, GALTRANSL_ROOT)
from GalTransl.Backend.SakuraTranslate import CSakuraTranslate
from GalTransl.ConfigHelper import CProjectConfig
from GalTransl.CSentense import CSentense, CTransList
from GalTransl.Dictionary import CGptDict


# Wolf 的控制碼。順序重要：cself 要排在 c 前面，否則 \cself[8] 會被切成 \c；
# sp 要排在 s 前面。用精確列舉而非 \\[A-Za-z]+，否則 "\E BADEND" 這種
# 控制碼後面緊接英文字的情況會把內文一起吃掉。
_WOLF_CODE = (
    r'\\(?:'
    # 多字母的要排在單字母前面，否則 \cself[8] 會被切成 \c、\sp[24] 會被切成 \s
    r'cself\[[^\]]*\]|self\[[^\]]*\]|'
    r'cdb\[[^\]]*\]|udb\[[^\]]*\]|sdb\[[^\]]*\]|'
    r'space\[[^\]]*\]|font\[[^\]]*\]|'
    r'sp\[[^\]]*\]|ax\[[^\]]*\]|ay\[[^\]]*\]|'
    r'c\[[^\]]*\]|f\[[^\]]*\]|v\[[^\]]*\]|s\[[^\]]*\]|r\[[^\]]*\]|'
    # 單字元碼：\> \< \. \! \^ \- \| （換行控制、等待、置中等）
    r'E|[><.!^|-]'
    r')'
)
WOLF_CODE_RE = re.compile(_WOLF_CODE)
# 開頭連續的控制碼，翻譯前摘除、翻完接回。
LEADING_CODE_RE = re.compile(r'^(?:' + _WOLF_CODE + r')+')


class WolfTranslator:
    """處理 WOLF RPG Editor 導出 JSON 的翻譯器"""

    # Context 優先級（數值越小越優先）
    CONTEXT_PRIORITY = {
        'dialog': 1,        # 對話訊息 - 最優先
        'choice': 2,        # 選項
        'picture_text': 3,  # 文字模式圖片顯示（技能說明等 UI 文字）
        'call_arg': 4,      # 傳給公共事件的字串引數（說話者名字牌就是這個）
        'database': 5,      # 資料庫（道具／技能／武器名稱與說明）
        'game_title': 6,    # 視窗標題
        'string_var': 20,   # 字串變數指派 - 會影響行為
        'condition': 21,    # 字串比較運算元 - 會影響行為
        'debug': 99,        # 除錯訊息 - 玩家看不到
    }

    # 預設跳過：玩家看不到
    DEFAULT_SKIP_CONTEXTS = {'debug'}

    # 預設跳過、需 --include-optional 才翻：翻了會改變遊戲行為
    OPTIONAL_CONTEXTS = {'string_var', 'condition'}

    def __init__(
        self,
        input_file: str,
        output_file: Optional[str] = None,
        checkpoint_file: Optional[str] = None,
        sakura_endpoint: str = 'http://127.0.0.1:8080',
        model_type: str = 'galtransl-v3',
        batch_size: int = 16,
        gpt_dict_files: Optional[List[str]] = None,
        skip_translated: bool = True,
        skip_contexts: Optional[Set[str]] = None,
        include_optional: bool = False,
        priority_threshold: int = 99,
        target_encoding: str = 'cp950',
        limit: int = 0,
    ):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file) if output_file else self.input_file

        if checkpoint_file:
            self.checkpoint_file = Path(checkpoint_file)
        else:
            self.checkpoint_file = self.input_file.parent / f".{self.input_file.stem}_checkpoint.json"

        self.sakura_endpoint = sakura_endpoint
        self.model_type = model_type
        self.batch_size = batch_size
        self.gpt_dict_files = gpt_dict_files or []
        self.skip_translated = skip_translated
        self.priority_threshold = priority_threshold
        self.target_encoding = target_encoding
        self.limit = limit

        self.skip_contexts = skip_contexts if skip_contexts is not None else self.DEFAULT_SKIP_CONTEXTS.copy()
        if not include_optional:
            self.skip_contexts.update(self.OPTIONAL_CONTEXTS)

        self.config_dir = self._create_config()

        self.stats = {
            'total': 0, 'translated': 0, 'skipped': 0,
            'failed': 0, 'cached': 0, 'by_context': {}
        }

    def _create_config(self) -> str:
        config_dir = self.input_file.parent / '.wolf_config'
        config_dir.mkdir(exist_ok=True)

        config_content = f"""# WOLF RPG Sakura 翻譯配置
backendSpecific:
  SakuraLLM:
    endpoints:
      - {self.sakura_endpoint}
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
"""
        config_path = config_dir / 'config.yaml'
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        return str(config_dir)

    # -- I/O ---------------------------------------------------------------

    def load_json(self, file_path: Path) -> Tuple[Dict, List[Dict]]:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'info' in data and 'strings' in data:
            return data['info'], data['strings']
        raise ValueError(f"無效的 JSON 格式（需要 info + strings）: {file_path}")

    def save_json(self, info: Dict, strings: List[Dict], file_path: Path):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({'info': info, 'strings': strings}, f,
                      ensure_ascii=False, indent=2)

    def load_checkpoint(self) -> Dict[str, str]:
        if self.checkpoint_file.exists():
            print(f"📦 找到檢查點: {self.checkpoint_file}")
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                return {str(k): v for k, v in json.load(f).items()}
        return {}

    def save_checkpoint(self, translations: Dict[str, str]):
        tmp = self.checkpoint_file.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)
        tmp.replace(self.checkpoint_file)

    # -- 篩選 ---------------------------------------------------------------

    def is_japanese_text(self, text: str) -> bool:
        """判斷是否含有需要翻譯的日文內容"""
        if not text or not isinstance(text, str):
            return False
        clean = WOLF_CODE_RE.sub('', text).strip()
        if not clean:
            return False
        # 平假名／片假名／半形片假名
        if re.search(r'[぀-ゟ゠-ヿ･-ﾟ]', clean):
            return True
        # 漢字
        if re.search(r'[一-龯]', clean):
            return True
        return False

    def get_context_priority(self, context: str) -> int:
        return self.CONTEXT_PRIORITY.get(context, 50)

    def should_translate(self, entry: Dict) -> bool:
        if self.skip_translated and entry.get('translated'):
            return False
        context = entry.get('context', '')
        if context in self.skip_contexts:
            return False
        if self.get_context_priority(context) > self.priority_threshold:
            return False
        if not self.is_japanese_text(entry.get('original', '')):
            return False
        # condition 的字串會在執行期與別處的值比對。只有當同一段原文也出現在
        # 其他 context 時，翻譯記憶才能保證兩邊被翻成同一句、比較繼續成立；
        # 找不到對應方的就維持原文，寧可留日文也不要讓分支永遠不觸發。
        if context == 'condition' and entry['original'] not in self._shared_originals:
            return False
        return True

    def _build_shared_originals(self, strings: List[Dict]) -> Set[str]:
        """出現在 condition 以外 context 的原文集合。"""
        return {e['original'] for e in strings
                if e.get('context') != 'condition' and e.get('original')}

    # -- 控制碼 -------------------------------------------------------------

    def split_leading_codes(self, text: str) -> Tuple[str, str]:
        """把開頭連續的控制碼摘出來，避免模型把它們吃掉或改寫。"""
        match = LEADING_CODE_RE.match(text)
        if not match:
            return '', text
        return match.group(0), text[match.end():]

    def check_inline_codes(self, original: str, translated: str) -> List[str]:
        """回報譯文中遺失的行內控制碼（僅警告，不自動修）。"""
        lost = []
        for code in set(WOLF_CODE_RE.findall(original)):
            if original.count(code) > translated.count(code):
                lost.append(code)
        return lost

    # -- 翻譯 ---------------------------------------------------------------

    async def translate_batch(self, translator, entries: List[Dict],
                              gpt_dict: Optional[CGptDict] = None) -> List[Dict]:
        if not entries:
            return entries

        trans_list = CTransList()
        prefixes = []
        for i, entry in enumerate(entries):
            prefix, body = self.split_leading_codes(entry['original'])
            prefixes.append(prefix)
            trans_list.append(CSentense(
                pre_jp=body,
                speaker=entry.get('speaker', ''),
                index=i,
            ))

        gpt_dict_content = ""
        if gpt_dict:
            gpt_dict_content = gpt_dict.gen_prompt(trans_list, type="sakura")

        try:
            _num, result_list = await translator.translate(
                trans_list=trans_list,
                gptdict=gpt_dict_content,
                filename="wolf_translation",
            )
            for i, sent in enumerate(result_list):
                if sent.post_zh and sent.trans_by != "failed":
                    entries[i]['translated'] = prefixes[i] + sent.post_zh
            return entries
        except Exception as e:
            print(f"  ⚠️ 批量翻譯出錯: {e}")
            return entries

    def group_entries_by_context(self, entries: List[Dict]) -> Dict[str, List[Dict]]:
        groups: Dict[str, List[Dict]] = {}
        for entry in entries:
            groups.setdefault(entry.get('context', 'unknown'), []).append(entry)
        return groups

    async def translate(self):
        print("=" * 70)
        print("🐺 WOLF RPG JSON 翻譯器 - 使用本地 Sakura 模型")
        print("=" * 70)
        print(f"輸入文件: {self.input_file}")
        print(f"輸出文件: {self.output_file}")
        print(f"模型端點: {self.sakura_endpoint}")
        print(f"批次大小: {self.batch_size}")
        print(f"目標編碼: {self.target_encoding}")
        print(f"跳過類型: {', '.join(sorted(self.skip_contexts)) or '無'}")
        print("=" * 70)
        print()

        print("📖 載入 JSON 資料...")
        info, strings = self.load_json(self.input_file)
        self.stats['total'] = len(strings)
        print(f"   遊戲標題: {info.get('game_title', '未知')}")
        print(f"   共有 {self.stats['total']} 個條目")

        checkpoint = self.load_checkpoint()
        if checkpoint:
            print(f"   檢查點包含 {len(checkpoint)} 個已翻譯條目")
        for entry in strings:
            idx = str(entry['index'])
            if idx in checkpoint:
                entry['translated'] = checkpoint[idx]
                self.stats['cached'] += 1

        self._shared_originals = self._build_shared_originals(strings)

        # 翻譯記憶：同一段原文只翻一次，結果套用到所有相同原文的條目。
        # 這同時保證了 condition 與它的對應方（string_var / database / choice）
        # 會被翻成完全相同的字串，比較才不會失效。
        memory: Dict[str, str] = {}
        for entry in strings:
            if entry.get('translated') and entry.get('original'):
                memory.setdefault(entry['original'], entry['translated'])
        if memory:
            print(f"   翻譯記憶: {len(memory)} 組原文")

        pending = [e for e in strings if self.should_translate(e)]

        # 先用記憶命中，剩下的按原文去重
        reused = 0
        to_translate: List[Dict] = []
        seen: Dict[str, Dict] = {}
        self._duplicates: Dict[str, List[Dict]] = {}
        for entry in pending:
            original = entry['original']
            if original in memory:
                entry['translated'] = memory[original]
                checkpoint[str(entry['index'])] = memory[original]
                reused += 1
                continue
            if original in seen:
                self._duplicates.setdefault(original, []).append(entry)
                continue
            seen[original] = entry
            to_translate.append(entry)

        if self.limit:
            to_translate = to_translate[:self.limit]
            print(f"   ⚠️ 測試模式：只翻譯前 {self.limit} 條")

        deduped = sum(len(v) for v in self._duplicates.values())
        self.stats['skipped'] = self.stats['total'] - len(pending) - self.stats['cached']

        print(f"   待處理: {len(pending)} | 記憶命中: {reused} | "
              f"重複原文: {deduped} | 實際送模型: {len(to_translate)}")
        print(f"   已緩存: {self.stats['cached']} | 跳過: {self.stats['skipped']}")

        context_groups = self.group_entries_by_context(to_translate)
        sorted_contexts = sorted(context_groups, key=self.get_context_priority)
        print("\n   📊 待翻譯條目分布:")
        for ctx in sorted_contexts:
            print(f"      [{self.get_context_priority(ctx):2d}] {ctx}: "
                  f"{len(context_groups[ctx])}")
        print()

        if not to_translate:
            print("✅ 無需翻譯的條目")
            self.save_json(info, strings, self.output_file)
            return

        print("⚙️ 初始化 Sakura 翻譯器...")
        config = CProjectConfig(self.config_dir)

        gpt_dict = None
        if self.gpt_dict_files:
            valid = [f for f in self.gpt_dict_files if Path(f).exists()]
            if valid:
                gpt_dict = CGptDict(valid)
                print(f"   已載入 {len(valid)} 個字典文件")
            else:
                print("   ⚠️ 字典文件不存在，跳過")

        translator = CSakuraTranslate(
            config=config, eng_type=self.model_type,
            endpoint=self.sakura_endpoint, proxy_pool=None,
        )
        print("   ✅ 翻譯器就緒\n")

        print("🚀 開始翻譯...")
        print("=" * 70)

        done = 0
        total_todo = len(to_translate)
        for ctx in sorted_contexts:
            ctx_entries = context_groups[ctx]
            print(f"\n📂 [{ctx}] 優先級 {self.get_context_priority(ctx)}, "
                  f"共 {len(ctx_entries)} 條")
            print("-" * 50)

            for start in range(0, len(ctx_entries), self.batch_size):
                batch = ctx_entries[start:start + self.batch_size]
                bno = start // self.batch_size + 1
                btot = (len(ctx_entries) + self.batch_size - 1) // self.batch_size

                batch = await self.translate_batch(translator, batch, gpt_dict)

                for entry in batch:
                    context = entry.get('context', 'unknown')
                    counts = self.stats['by_context'].setdefault(
                        context, {'success': 0, 'failed': 0})
                    if entry['translated']:
                        checkpoint[str(entry['index'])] = entry['translated']
                        self.stats['translated'] += 1
                        counts['success'] += 1
                        lost = self.check_inline_codes(entry['original'],
                                                       entry['translated'])
                        if lost:
                            print(f"      ⚠️ [{entry['index']}] 控制碼遺失: "
                                  f"{', '.join(lost)}")
                    else:
                        self.stats['failed'] += 1
                        counts['failed'] += 1

                self.save_checkpoint(checkpoint)
                done += len(batch)
                sample = batch[0]
                preview = (sample['translated'] or '(失敗)')[:44].replace('\n', '\\n')
                print(f"   [{ctx} {bno}/{btot}] 累計 {done}/{total_todo} "
                      f"({done / total_todo * 100:.1f}%)  例: {preview}")
                sys.stdout.flush()

                await asyncio.sleep(0.2)

        for entry in strings:
            idx = str(entry['index'])
            if idx in checkpoint:
                entry['translated'] = checkpoint[idx]

        # 把代表句的譯文擴散到所有相同原文的條目
        final_memory: Dict[str, str] = {}
        for entry in strings:
            if entry.get('translated') and entry.get('original'):
                final_memory.setdefault(entry['original'], entry['translated'])
        propagated = 0
        for original, dups in getattr(self, '_duplicates', {}).items():
            translated = final_memory.get(original)
            if not translated:
                continue
            for entry in dups:
                if not entry['translated']:
                    entry['translated'] = translated
                    checkpoint[str(entry['index'])] = translated
                    propagated += 1
        if propagated:
            self.save_checkpoint(checkpoint)
            print(f"\n🔁 相同原文擴散: {propagated} 條")

        print()
        print("=" * 70)
        print("💾 儲存翻譯結果...")
        self.save_json(info, strings, self.output_file)

        print("\n📊 翻譯統計:")
        print(f"   總條目數: {self.stats['total']}")
        print(f"   ✅ 新翻譯: {self.stats['translated']}")
        print(f"   📦 使用緩存: {self.stats['cached']}")
        print(f"   ○ 跳過: {self.stats['skipped']}")
        print(f"   ✗ 失敗: {self.stats['failed']}")
        if self.stats['by_context']:
            print("\n   按類型統計:")
            for ctx, c in sorted(self.stats['by_context'].items(),
                                 key=lambda x: self.get_context_priority(x[0])):
                print(f"      {ctx}: ✓{c['success']} ✗{c['failed']}")

        # 編碼檢查：譯文必須寫得回遊戲
        bad = []
        for entry in strings:
            if not entry['translated']:
                continue
            try:
                entry['translated'].encode(self.target_encoding)
            except UnicodeEncodeError as exc:
                bad.append((entry, entry['translated'][exc.start:exc.end]))
        print(f"\n🔤 {self.target_encoding} 編碼檢查:")
        if bad:
            print(f"   ⚠️ {len(bad)} 條譯文含無法編碼的字元:")
            for entry, ch in bad[:15]:
                print(f"      [{entry['index']}] {ch!r} in "
                      f"{entry['translated'][:40]!r}")
            if len(bad) > 15:
                print(f"      ... 還有 {len(bad) - 15} 條")
            print("   導入時可用 --skip-unencodable 保留原文，或改用其他編碼")
        else:
            print(f"   ✅ 全部譯文都能以 {self.target_encoding} 寫回")

        print("=" * 70)
        print(f"✨ 結果已儲存: {self.output_file}\n")


async def main():
    parser = argparse.ArgumentParser(
        description='WOLF RPG JSON 翻譯工具 - 使用本地 Sakura 模型',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python translate_wolf.py -i exported/script.json
  python translate_wolf.py -i exported/script.json --priority 2   # 只翻對話與選項
  python translate_wolf.py -i exported/script.json --limit 20     # 小樣本測試

Context 優先級:
   1 dialog（對話）        2 choice（選項）      3 picture_text（UI 文字）
   4 database（資料庫）    5 game_title
  20 string_var / 21 condition  - 會改變遊戲行為，預設跳過
  99 debug                      - 玩家看不到，預設跳過
""")
    parser.add_argument('-i', '--input', required=True, help='輸入 JSON 文件')
    parser.add_argument('-o', '--output', help='輸出 JSON（預設覆蓋輸入）')
    parser.add_argument('-e', '--endpoint', default='http://127.0.0.1:8080')
    parser.add_argument('-m', '--model', default='galtransl-v3',
                        choices=['galtransl-v3', 'sakura-v1.0'])
    parser.add_argument('-b', '--batch-size', type=int, default=16)
    parser.add_argument('--dict', nargs='*', help='GPT 字典文件')
    parser.add_argument('--priority', type=int, default=99)
    parser.add_argument('--include-optional', action='store_true',
                        help='一併翻譯 string_var / condition（會改變遊戲行為）')
    parser.add_argument('--skip-contexts', nargs='*')
    parser.add_argument('--no-skip-translated', action='store_true')
    parser.add_argument('--encoding', default='cp950',
                        help='導入遊戲時的目標編碼，用於結束時檢查 (default: cp950)')
    parser.add_argument('--limit', type=int, default=0,
                        help='只翻譯前 N 條（測試用）')
    args = parser.parse_args()

    try:
        translator = WolfTranslator(
            input_file=args.input,
            output_file=args.output,
            sakura_endpoint=args.endpoint,
            model_type=args.model,
            batch_size=args.batch_size,
            gpt_dict_files=args.dict,
            skip_translated=not args.no_skip_translated,
            skip_contexts=set(args.skip_contexts) if args.skip_contexts else None,
            include_optional=args.include_optional,
            priority_threshold=args.priority,
            target_encoding=args.encoding,
            limit=args.limit,
        )
        await translator.translate()
        print("🎉 翻譯完成！")
    except KeyboardInterrupt:
        print("\n\n⚠️ 翻譯被中斷")
        print("💾 進度已存入檢查點，重新執行會從中斷處繼續")
    except Exception as e:
        print(f"\n❌ 發生錯誤: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
