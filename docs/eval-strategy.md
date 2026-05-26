# Eval 策略與三模式拆分

**最後更新**：2026-05-25
**決議來源**：`eval-judge-incorporate-tool-grounding` discuss session

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

### 該量什麼（依題型分流）

| 指標 | 適用題型 | grader 類型 |
|---|---|---|
| `episode_set_f1` | guest_find / date_find / 列舉題 | Code-based |
| `answer_factual_correctness` | 所有非拒答題 | LLM judge（語意比，取代 substring keyword）|
| `citation_grounded` | 答案內含具體 EP / quote 的題 | Code-based（regex 抓 → 對 tool result 做 substring） |
| `refusal_appropriateness` | 所有題（三態：appropriate / should_refuse / should_answer） | LLM judge |
| `tool_args_correctness` | multi_turn / ordinal 題 | Code-based |
| `recall@k` (chunk-level) | 只有 deep_dive 特定 episode 題 | Code-based |

### Aggregate 規則

**不算跨題型平均**（會被 sub-population 污染）。每個指標獨立報、獨立設 gate。

### Dataset

`backend/eval/datasets/chat-rag-golden.json`（暫定，重整 `extended-multi-turn-40.json`）

每題欄位：
- `id` / `design_type` / `question`
- `expected_behavior`：`"answer" | "refuse" | "either"`
- `expected_answer_summary`（自然語言）— **取代 expected_answer_keywords**
- `expected_episode_numbers`（人讀友善，譬如 `["EP143", "EP4"]`）
- `expected_episode_uuids`（machine match 用）
- `expected_tool_args`（只 multi_turn / ordinal 題標）
- `ground_truth_chunk_ids`（只 deep_dive 題標）
- `audit_status` / `audit_notes`

舊欄位淘汰：
- ❌ `expected_answer_keywords`（substring match 對 partial refusal / 語意對但用詞不同失明）
- ❌ `expected_tool_calls_required` / `acceptable`（換成 `expected_tool_args`，更精準）

### Reliability：Pass^K

整個 dataset 對 prod 跑 K=3，量每題 K 次 answer 的 consistency（episode 集合 Jaccard、refusal 是否穩定）。

**Pass^K 是 production reliability metric，不是 judge 穩定性 metric**。

### 跑頻率

每次 prompt / tool / agent loop 動就跑。

---

## Audit 順序

| 順序 | 模式 | 狀態 |
|---|---|---|
| 1 | Chat-RAG | **進行中**（7 題試水起手）|
| 2 | Semantic | **Backlog**，chat 完才動 |
| 3 | Keyword | **Backlog**，等 `keyword-index-mode` change apply 時一起做 |

---

## 待補強清單（重要）

未做但記下來：

- **Semantic dataset 加 paraphrase_variants 欄位 + 重新 audit**
- **Keyword regression PyTest dataset 建立**（10-15 題）+ 對應 PyTest case
- **三模式各自的 Pass^K 策略**（目前只想 chat 模式 Pass^K，semantic/keyword 是否需要 reliability metric 待議）
- **ASR 已知錯字批次修正**（暫名 `asr-known-typos-correction-batch` change）— Eval 短期靠 dataset 的 `expected_answer_aliases` 欄位處理錯字（grader 比對時兩種拼法都算命中）。長期要動 transcribe 管線批次修正全節目 transcript。目前已知錯字：
  - 杜宗祐 ← 杜忠祐（ASR 錯）
  - 阿名 ← 阿鳴（ASR 錯）
  - 滅火器 ← 咪有企（ASR 錯）
  - 世運 ← 世韻（ASR 錯）

## Dataset 欄位約定：`expected_answer_aliases`

題目的 expected answer 可能含名字 / 詞彙有 ASR 錯字 alias 時，欄位結構：

```json
"expected_answer_aliases": {
  "杜宗祐": ["杜忠祐"],
  "阿名": ["阿鳴"]
}
```

Grader 規則：標準名 OR 其 alias 任一在 agent answer 出現都算命中。**Eval 不被 ASR 拖累，未來 T1 修字也不用改 dataset**。
