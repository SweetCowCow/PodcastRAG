## Context

承接 archived `2026-05-27-chunk-level-retrieval-rca-b20-style` RCA case study（含 2026-05-28 訂正段）+ 2026-05-28 prod DB probe 實證。詳細 root cause 證據在 `docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md` 末段「2026-05-28 訂正」。

現況 `_build_ts_query`（`backend/app/services/rag.py:211-253`）：jieba 切詞 → 過濾純標點 → show-name filter（目前空集合）→ OR 拼接。**沒有 stop-word filter、沒有 1-char drop**（雖然 comment 寫 v4 drop 1-char，實作沒落實）。對 b20 query 產出 16 token OR query，prod 命中 39,323 chunk、GT chunks ts_rank 排在 18K-32K 名被 LIMIT 50 砍掉。

## Goals / Non-Goals

**Goals:**

- 把 b20 query 對應 ts_query 的 prod 命中數從 39K 壓到數百量級
- GT chunks `9543a933` / `f6cd079f` 至少 1 個進 lexical pool top-50
- 對其他既有題型（chat / semantic / keyword 三模式 38 題 baseline）不退步

**Non-Goals:**

- 不動 jieba tokenizer 本體或 custom dict
- 不動 RRF weight / RRF_K / per_side
- 不動 chunking / embedding / prefilter
- 不做 LLM query expansion
- 不新增 admin debug trace（觀察期後再決定）

## Decisions

### Decision 1: Stop-word filter 採「黑名單常數」而非「IDF 動態計算」

**選**：在 `rag.py` 內維護 module-level frozenset `_STOP_WORDS`，列舉 ~50-80 個高頻 stop-word。`_build_ts_query` 在現有「過濾純標點」之後加一層 `if tok in _STOP_WORDS: continue`。

**拒**：對全 corpus 跑 IDF 統計、低於閾值就丟。

**Rationale:**

- 黑名單 transparent、可單元測試、可審計
- IDF 動態計算要每次部署重算、跨 show 行為不一致、debug 困難
- 黑名單漏掉某 stop-word 用 1-char drop（Decision 3）作第二層防線
- 中文 stop-word 收斂在數十個量級（不像英文上百），維護成本低

##### Example: 初始 stop-word list（v1）

中文常用虛詞 / 連接詞 / 疑問詞 / 高頻動詞：

```
的 是 在 為 不 也 都 又 還 就 才 把 被 給 讓 對 跟 和 與 及
這 那 哪 此 該 某 各 每 任 多 少 些 個 件 種
什麼 怎麼 怎樣 如何 為何 為什麼 多少 哪裡 哪些 哪個
我 你 他 她 它 我們 你們 他們 她們 它們 自己
有 沒 沒有 是 不是 會 不會 要 不要 能 不能 可以
了 過 著 啦 嗎 呢 吧 喔 嘛
一 二 三 四 五 六 七 八 九 十 一個 一首 一些 一下 一直
所以 因為 但是 可是 然後 之後 之前 後來
```

英文常用 stop-word：

```
the a an and or but if of in on at to for with by from as is are was were be been being have has had do does did will would can could should may might must
```

具體初版精確 list 在實作時 commit 進 `rag.py`，本 design 列大致範疇供 reviewer 校準預期。

### Decision 2: Stop-word list 寫死在 code，不走 env 或 DB 配置

**選**：`_STOP_WORDS: frozenset[str]` 直接在 `rag.py` 模組頂部。

**拒**：env var / DB table / config file。

**Rationale:**

- stop-word list 變動頻率極低，不需要 runtime hot-reload
- 寫死在 code 跟 unit test 一起 review，change history 走 git
- env 配置會引入「prod 與 staging stop-word 不同」這類隱性 bug
- 之後需要動，再 propose 新 change（簡單）

### Decision 3: 1-char drop 補實作，作為 stop-word filter 的第二層防線

**選**：在 `_build_ts_query` cleaned token loop 內加 `if len(tok) < 2: continue` 條件。

**Rationale:**

- comment block lines 240-253 已記錄 v4 drop 1-char 是 bake-off 勝出方案、但實作沒落實 — 補實作對齊 comment
- CJK 1-char 幾乎全是 stop-word 級高頻字（「的」「不」「在」），對 lexical signal 貢獻極低
- stop-word frozenset 漏列某 1-char（譬如「裡」「呀」），1-char drop 仍會擋掉，雙重 safety net
- 純英文單字（譬如「A」、「I」）也 drop — 對 EP-ref 題型（譬如「EP1」）不受影響，因為「EP1」是整個多字符 token

##### Example: b20 query 套用兩條 filter 後預期 token list

```
原 16 token：
迪拉胖 | 在 | EP134 | 為 | 什麼 | 不 | 挑 | 一首 | 振奮 | 的 |
開工歌 | 他選 | 的 | 歌想表達 | 什麼 | 概念

過 _STOP_WORDS 砍掉：在 / 為 / 什麼 / 不 / 一首 / 的 / 什麼

剩：迪拉胖 | EP134 | 挑 | 振奮 | 開工歌 | 他選 | 歌想表達 | 概念

過 len<2 drop（無 1-char）→ 同上

最終 8 token，全是 multi-char 信號 token。
```

### Decision 4: 兩條 filter 順序：stop-word filter 先、1-char drop 後

**選**：先檢 `_STOP_WORDS` 再檢 `len(tok) < 2`。

**Rationale:**

- stop-word filter 含 multi-char 詞（譬如「什麼」「沒有」），這層不能跳過
- 1-char drop 是「兜底」，stop-word filter 漏網才靠它
- 順序對效能無實質差異（兩個 O(1) check）

## Implementation Contract

**Behavior（observable）:**

- 對 `_build_ts_query(question: str)` API：簽名不變、回傳型別 `str | None` 不變
- 對 `retrieve_hybrid` / `retrieve` / `retrieve_descriptions` / `retrieve_titles`：API 不變，但 lexical pool 結果不同（命中數大幅減少、ranking 更聚焦）
- 對 b20 EP134 案：retrieval 端應撈到 GT chunk `9543a933` 或 `f6cd079f` 至少 1 個進 final top-K
- prod DB probe（同 RCA case study 方法）：相同 query 經新 `_build_ts_query` 後在全 show 命中數從 39K+ 下降到 ~數百

**Interface / data shape:**

- 新增 module-level `_STOP_WORDS: frozenset[str]`（位於 `rag.py` 模組頂部，靠近其他常數）
- `_build_ts_query` 函式體新增兩個 continue check（stop-word in、len < 2）
- 不新增 helper function（兩個 check 是 inline 條件）

**Failure modes:**

- 全 token 被 filter 掉（譬如 user query 「為什麼？」全 stop-word）→ `_build_ts_query` 回 `None`，retrieve 自動 fallback 到 semantic-only（既有行為，line 583-603）
- 1-char drop 邊界：純英文單字 query 譬如「A」會回 None → semantic-only path 接手
- 兩條 filter 都不會拋 exception

**Acceptance criteria:**

1. 本地 unit test `backend/tests/services/test_build_ts_query_filter.py`：
   - `test_b20_query_token_count`：b20 query 切詞後最終 token list 長度 ≤ 10、不含「的/不/什麼/在/為/一首」
   - `test_pure_stopword_query_returns_none`：「為什麼？」這類 query 回 None
   - `test_1char_cjk_dropped`：包含 1-char CJK 的 query，1-char token 不在最終 list
   - `test_multichar_english_preserved`：英文 multi-char token（「EP134」「RAG」）保留
   - `test_stop_words_set_immutable`：`_STOP_WORDS` 是 frozenset
2. Prod DB probe：相同 b20 query ts_query 在百靈果 NEWS show `transcript_chunks` 命中總數從 39,323 降到 < 1,000
3. b20 GT chunks 至少 1 個進 lexical pool top-50（直接 DB probe 確認 ts_rank 排名）
4. 三模式 baseline 達 Success Criteria 全條（chunk_recall_grouped ≥ 0.55、factual ≥ 0.88、hallucinated=0、無 PASS→FAIL）

**Scope boundaries:**

- 修改範圍鎖 `backend/app/services/rag.py` 內 `_build_ts_query` 函式 + 新增 `_STOP_WORDS` 常數
- 不動 retrieve_hybrid / retrieve / retrieve_descriptions / retrieve_titles 函式本體
- 不動其他 retrieval 層（chunking / embedding / RRF weight / prefilter / RRF merge）
- 不動 jieba tokenizer service / custom dict
- 不動 admin debug trace、不動 endpoint signature
- 不動 golden set / dataset

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Stop-word list 過嚴誤砍某題型關鍵 token（譬如「什麼是 RAG」砍掉「什麼」） | 純疑問句靠 semantic 側為主（embedding cos sim 對抽象問題本來就比 lexical 強）；per-question regression check 是 hard gate |
| 1-char drop 把某些單字 CJK 重要詞砍掉（譬如人名「習」、地名「京」） | 黃金測試集 38 題目前無 1-char 關鍵 token 題型；觀察 baseline diff，必要時開 follow-up 加 1-char 例外白名單 |
| Stop-word list 沒涵蓋到的 stop-word（譬如「自己」漏列） | 1-char drop 是兜底；prod redeploy 後第二輪 trace 觀察補列 |
| Lexical signal 過弱（全 query 都 stop-word + 1-char） | 既有 `_build_ts_query` return None → semantic-only fallback，行為不變 |
| 三模式中 keyword search 模式衝擊較大（高度依賴 lexical） | 三模式都跑 baseline、per-question regression check；若 keyword 退步明顯，調整 stop-word list 或加 keyword-mode 專用例外 |

## Migration Plan

1. **Phase 1a — code 改 + 本地 test**：rag.py 加 `_STOP_WORDS` + 兩條 filter；pytest 新檔全綠
2. **Phase 1b — local probe**：python 跑 `_build_ts_query` 對 b20 query，確認輸出 token 數從 16 → ~8
3. **Phase 1c — prod redeploy**：commit + push（webhook 不穩用 `zeabur service redeploy --id <backend-svc-id> -y -i=false`）；Monitor + deployment list 等 RUNNING + commit SHA 對齊
4. **Phase 1d — prod DB probe**：用 `mcp__podcastrag-pg__query` 跑相同 b20 ts_query，確認命中數從 39K 降到 < 1K、GT chunks rank 進 top-50
5. **Phase 1e — 三模式 baseline**：chat / semantic / keyword 三模式 eval，落地 `backend/eval/results/baseline-stopword-filter-2026-05-28-{mode}.json`
6. **Phase 1f — diff + 達標判定**：跑 `diff_baselines.py` vs `baseline-post-judge-v2-2026-05-27.json`；寫 case study；達標判定 PASS / PARTIAL / FAIL
7. **Phase 1g — 達標決議**：
   - 全達標 → archive；Phase 2/3 不啟動
   - 部分達標 → archive + propose `retrieve-hybrid-per-side-widen` 或 `retrieve-hybrid-noise-flood-safety-net`（R4）
   - 退步 → revert prod；case study 記錄 root cause；不 archive；回 discuss

**Rollback**：git revert + zeabur redeploy；或先動 `_STOP_WORDS` 內容（譬如移除誤殺的詞）再決定要不要全 revert。

## Open Questions

- 初版 `_STOP_WORDS` 涵蓋範圍：先列保守版（~50 詞）還是激進版（~150 詞）？採保守版先跑 baseline，看殘餘 noise pattern 再加
- 三模式中是否有 mode 需要不同 stop-word policy？預期 chat / semantic 共用，keyword 模式可能要弱化 stop-word filter — 留 baseline 結果定
- 之後是否需要把 stop-word filter 提到 `tokenizer` 模組共用？目前 jieba tokenize 結果只有 `_build_ts_query` 一個 consumer；提前抽出反而過度設計
