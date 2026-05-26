# Eval 策略與三模式拆分

**最後更新**：2026-05-26（chat-rag audit 試水 7 題完，schema + 指標清單 freeze + v2 上線）
**決議來源**：`eval-judge-incorporate-tool-grounding` discuss session + `chat-rag-dataset-audit-2026-05-25` 試水 audit
**Schema v2 上線日期**：2026-05-26（change `eval-judge-incorporate-tool-grounding` apply 完成）
**Baseline 落地**：`docs/case-studies/chat-rag-dataset-audit-2026-05-26-baseline.md`
**Legacy v1 path**：semantic-mode dataset `this-not-that-cool.json` 與其相關 runner (`run_chat_agent_eval.py` 既有 v1 dispatch / `arm_a/b_*.py` bake-off 史檔 / `build_golden_set.py` 半 deprecated) 依 design D1 + `rag-eval-runner` MODIFIED Recall@K 要求保留，靠 `schema_version` 判斷走 v1 還是 v2 path

## 為什麼三模式 eval 要拆

PodcastRAG 對 user 暴露三個查詢模式，但三者**特性、隨機性、輸出形式、該量什麼指標都不同**。把三者放同個 eval pipeline 量，會讓信號互相污染。

| 模式 | 是否 LLM 生成 | 隨機性 | 輸出形式 | 該量的本質 |
|---|---|---|---|---|
| **Keyword 索引** | ❌（純 SQL CTE） | 0 | episode 集合 + chunk 段落 | 是否撈對集合（boolean） |
| **Semantic 搜尋** | ❌（embedding） | 0 | top-K chunks 排序 | 排序品質（IR metric） |
| **Chat (RAG agent)** | ✅ | 高 | NL 答案 + citation | grounded / refusal / multi-turn / 編造 |

→ 拆三份 dataset，三條獨立 eval 流程。

---

## 模式 1：Keyword 索引（pytest，不走 LLM eval pipeline）

**特性**：給定 index 後 input → output 是 deterministic SQL。沒 LLM 隨機性。

### 該量什麼

| 指標 | 算法 |
|---|---|
| `keyword_episode_set_match` | T1/T2/T3 三層輸出的 episode set vs expected |
| `keyword_chunk_position_check` | 命中 chunk 的 timestamp 在期望範圍內 |

### 跑在哪

**`backend/tests/` 下的 PyTest**，不放 `backend/eval/`。

理由：
- 沒 LLM 隨機性 → 不需要 stochastic eval framework
- 不需要 LLM judge → 沒成本問題
- 開發者跑 `pytest` 比跑 eval script 順手
- 跟 chat eval 混在一起反而會被忽略
- 跑頻率：每次改 SQL（CI 紅綠）

### Dataset

`backend/tests/fixtures/keyword_index_regression.json`（暫定），10-15 題涵蓋：
- T1 同段 AND
- T2 跨池 episode AND
- T3 OR fallback
- 邊界 case（空結果、超長 query、特殊字元）

**狀態**：尚未建立。等 `keyword-index-mode` change unpark + apply 時一起做。

---

## 模式 2：Semantic 搜尋（IR metric，無 LLM judge）

**特性**：embedding-based retrieval。給定 model + index 是 deterministic。重點是「對 paraphrase 是否 robust」+「ranking 品質」。

### 該量什麼

| 指標 | 算法 |
|---|---|
| `recall@5` | top-5 chunk 命中 expected chunk |
| `recall@20` | top-20 命中率（reranking 上限） |
| `mrr` | Mean Reciprocal Rank：第一個對的位置倒數 |
| `paraphrase_robustness` | 同問題不同問法 top-5 重疊率 |

### Dataset

`backend/eval/datasets/semantic-retrieval.json`（暫定）

題目特性偏好：
- 短查詢（user 真實搜尋習慣）
- 一題多 paraphrase variant
- expected = chunk_ids 集合（非 episode 集合）

**狀態**：既有 `this-not-that-cool.json` 30 題大致符合，但要加 `paraphrase_variants` 欄位 + 重新 audit。**Backlog**：chat dataset audit 完才動。

---

## 模式 3：Chat (RAG agent)（完整 indicator suite + LLM judge）

**特性**：LLM + tool loop，高隨機性。最複雜的一塊，也是 R3.x 路線主戰場。

### Design types（freeze 自試水 audit）

| design_type | 描述 | 試水案例 |
|---|---|---|
| `deep_dive` | 單集深度提問，期望 retrieve 到特定 chunk | b14 / b15 |
| `date_find` | 時間範圍列舉 | b11 |
| `cross_episode` | 跨集合成 / 識別 | b22 |
| `negative` | 前提錯誤 / 節目未提及，應 refuse + 補正確 context | b27 |
| `leading_question_yes` 🆕 | 問題語氣看似 negative trap，但答案其實 YES。核心壓力 = agent 不被疑問語氣誘導 refuse | b29 |
| `multi_turn` | 一般多輪上下文 carry | mt02-mt04 |
| `multi_turn_ordinal` 🆕 | 多輪 + 序數指代（「第三集」「最新一集」），需從前輪 enumeration_state 取 index | mt01 |
| `guest_find` | 列出某來賓上過哪幾集 | 待 audit |

### 該量什麼（依題型分流）

| 指標 | 適用題型 | grader | 試水抓到的洞 |
|---|---|---|---|
| `episode_set_f1` | 列舉題（must / acceptable 兩層） | Code | b29 EP143 漏 / b11 26 集全對 |
| `recall@k` (chunk-level) | deep_dive | Code（支援 must / either / acceptable 三層分組） | b15 R@5=1.0 / b14 R@5=0.67（@1790.18 vs @1808.78 boundary 重疊）|
| `tool_args_correctness` | multi_turn_ordinal / 嚴格參數題 | Code（含 regex pattern match） | mt01 t2 episode_id 必須 = EP131 UUID |
| `answer_factual_correctness` | 所有非拒答題 | **LLM judge**（語意比 expected_answer_summary，含 alias 容錯）| b15 公務人員 ≡ 電信局 substring miss → LLM judge 正解 |
| `refusal_appropriateness` | 所有題（三態：appropriate / should_refuse / should_answer） | LLM judge | b29 LLM judge 必須擋「該 answer 卻 refuse」|
| `citation_grounded` | 答案內含具體 EP / quote / 引文 | Code（regex + substring on tool result）| b27 / b29 grounded 確認 |
| `count_consistency` 🆕 | 列舉題（answer 文字內提到「N 集」） | Code（regex 抓數字 → == `enumeration_total`） | b11 tool 回 26 / answer 寫 27 hallucination |
| `answer_contradict_check` 🆕 | 反問 / 比較 / 對照型題 | LLM judge（檢查 answer 是否違反 question premise） | b14「為什麼不挑振奮歌」agent 卻寫「推薦振奮人心的歌」|
| `ordinal_resolution_check` 🆕 | multi_turn_ordinal | Code（比對 agent resolve 到的 episode_id vs `carry_from` 指向的 index） | mt01 t2 resolve EP55 instead of EP131 |

### Aggregate 規則

**不算跨題型平均**（會被 sub-population 污染）。每個指標獨立報、獨立設 gate。

### Dataset schema（v2，freeze 2026-05-26）

`backend/eval/datasets/chat-rag-golden.json`（暫定，重整 `extended-multi-turn-40.json`）

#### 通用欄位

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` / `design_type` / `source` / `question` | ✅ | 基本識別 |
| `is_multi_turn` | ✅ | bool；true 則 `turns` 是 array |
| `expected_behavior` | ✅ | `"answer" \| "refuse" \| "refusal_with_correction"` |
| `expected_answer_summary` | ✅ | 自然語言（**取代 expected_answer_keywords**）給 LLM judge 比對 |
| `expected_answer_aliases` | 選 | `{標準名: [alias1, alias2]}`；ASR 錯字 + 上下位語意（如「電信局」alias「公務人員」）|
| `audit_status` / `audit_notes` | ✅ | `human-verified-YYYY-MM-DD` |

#### Episode 集合欄位（兩層）

| 欄位 | 用法 |
|---|---|
| `expected_episode_uuids_must` | 必中，少一個扣分 |
| `expected_episode_uuids_acceptable` | bonus；hit 加分，miss 不扣分 |
| `expected_episode_numbers_must / _acceptable` | 同上，人讀友善版（EP編號）|
| `expected_count` | 列舉題的精確集數（搭 `count_consistency`）|
| `expected_top_n_episode_numbers` | 列舉題的 top-N 順序檢查（譬如 mt01 t1 要 DESC top-3 = [142,134,131]）|

#### Tool 欄位

| 欄位 | 用法 |
|---|---|
| `expected_tool_calls_required` | 必須呼叫的 tool 名單 |
| `expected_tool_calls_acceptable` | 可選 tool（不扣分）|
| `expected_tool_args` | 嚴格參數比對；支援 `{"ref_must_match_pattern": "^EP19$\|^第19集$"}` |

#### Chunk-level GT（三層分組，解 chunk overlap）

| 欄位 | 用法 |
|---|---|
| `ground_truth_chunk_ids_must` | 必中 |
| `ground_truth_chunk_ids_either` | 群內擇一即算 hit（解 chunk 跨 boundary 重疊，如 b14 @1790.18 / @1808.78）|
| `ground_truth_chunk_ids_acceptable` | bonus |

#### 反問 / 矛盾檢查

| 欄位 | 用法 |
|---|---|
| `expected_must_contradict_check` | 自然語言描述「answer 不得出現的內容」（如 b14：「不得出現『推薦振奮歌』敘述」）|

#### Multi-turn 專用

| 欄位 | 用法 |
|---|---|
| `turns` | array；單輪題不用 |
| `carry_from` | t2+ 必填；指向前輪取數規則（如「t1.enumeration_episodes[2] sorted by published_at DESC」）|
| `ordinal_resolution_check` | flag；觸發 `ordinal_resolution_check` 指標 |

#### 舊欄位淘汰

- ❌ `expected_answer_keywords`（substring match 對 partial refusal / 語意同義失明）
- ❌ `expected_episode_uuids` 單層（改 must / acceptable 兩層）
- ❌ `ground_truth_chunk_ids` 單層（改 must / either / acceptable 三層）

### Reliability：Pass^K

整個 dataset 對 prod 跑 K=3，量每題 K 次 answer 的 consistency（episode 集合 Jaccard、refusal 是否穩定）。

**Pass^K 是 production reliability metric，不是 judge 穩定性 metric**。

### 跑頻率

每次 prompt / tool / agent loop 動就跑。

---

## Audit 順序

| 順序 | 模式 | 狀態 |
|---|---|---|
| 1 | Chat-RAG | **試水 7 題 done（2026-05-26）→ 等 propose 後批 audit 全 40 題** |
| 2 | Semantic | **Backlog**，chat 完才動 |
| 3 | Keyword | **Backlog**，等 `keyword-index-mode` change apply 時一起做 |

---

## Audit 階段抓到的 Retrieval / Agent 弱點 pattern

試水 7 題揭露 4 個獨立 weakness pattern（已記入相應 follow-up backlog）：

| Pattern | 案例 | 修法方向 | 對應 change |
|---|---|---|---|
| **跨集合成 retrieval miss** | b22 漏方品融/阿名、b29 漏 EP143 | RRF description-source weight 調整 / search query rewrite | `rrf-description-source-weight`（已 backlog）+ 可能要 `retrieval-cross-episode-recall-improvement` |
| **反問題 LLM 兜兩邊話術** | b22 主持人陣容、b14 開工歌 | `answer_contradict_check` 指標擋；prompt 可能無解 | 由新指標偵測；prompt 修法待飽和點後評估 |
| **Agent search query 太抽象** | b14 retrieve 端沒問題，agent query 沒 anchor 到具體實體 | 在 SYSTEM_PROMPT 加 query rewrite hint，但小心 prompt 飽和 | 跟 `agentic-grounding-prompt-tune-v3` 併考 |
| **LLM number hallucination** | b11 tool 回 26 / answer 寫 27 | 新指標 `count_consistency` 偵測；可能加 post-gen number 校對 helper | follow-up TBD |
| **Multi-turn ordinal resolution bug** | mt01 t2 EP55 vs EP131 | server-side detect「第 N 集」literal 預解析 UUID 注入 | `multi-turn-ordinal-mechanical-resolution`（待 propose） |

---

## 待補強清單（重要）

未做但記下來：

- **Semantic dataset 加 paraphrase_variants 欄位 + 重新 audit**
- **Keyword regression PyTest dataset 建立**（10-15 題）+ 對應 PyTest case
- **三模式各自的 Pass^K 策略**（目前只想 chat 模式 Pass^K，semantic/keyword 是否需要 reliability metric 待議）
- **ASR 已知錯字批次修正**（暫名 `asr-known-typos-correction-batch` change）— Eval 短期靠 dataset 的 `expected_answer_aliases` 欄位處理錯字（grader 比對時兩種拼法都算命中）。長期要動 transcribe 管線批次修正全節目 transcript。完整清單見 memory `project_asr_typos_backlog.md`，包含：
  - 杜宗祐 ← 杜忠祐
  - 阿名 ← 阿鳴
  - 方品融 ← 方品龍（mt01 t2 audit 新發現）
  - 坂本龍一 ← 版本聖太郎 / 版本盛泰郎（b14/b29 audit 新發現，推測待確認）
  - 滅火器 ← 咪有企
  - 世運 ← 世韻

## Dataset 欄位約定：`expected_answer_aliases`

題目的 expected answer 可能含名字 / 詞彙有 ASR 錯字 alias 時，欄位結構：

```json
"expected_answer_aliases": {
  "杜宗祐": ["杜忠祐"],
  "阿名": ["阿鳴"]
}
```

Grader 規則：標準名 OR 其 alias 任一在 agent answer 出現都算命中。**Eval 不被 ASR 拖累，未來 T1 修字也不用改 dataset**。
