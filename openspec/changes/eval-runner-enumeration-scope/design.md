## Context

PodcastRAG 的 eval 框架（`backend/eval/runners/run.py`）目前只支援單一評分路徑：把 retrieved chunks 跟 `ground_truth_chunk_ids` 做 set 交集除以 |relevant|，由 `backend/eval/metrics/recall.py` 提供。空 ground_truth 一律回 `None`，aggregate 階段沉默過濾。

2026-05-13 共草 golden set q24-q30 期間出現三種評分需求：
1. **q01-q23**：傳統 chunk-id 對位（既有行為）
2. **q24「Leo王 ↔ 迪拉合作弧線」**：跨集演進弧線題，命中任一 anchor 或相關段落即算 hit（寬鬆 set-cover）
3. **q25/q26「節目裡有哪些集是歌單 / 講高雄美食」**：catalog-wide 列舉題，要求 retrieval 結果涵蓋指定 episode 集合中的多集，評分用 episode-set recall

`_pending_review.json` 已在 q24/q25/q26 寫了 `scope` 欄位（值 `open_set_lenient` / `enumeration`），但 `_schema.json` 沒規範這個欄位，runner 也不認得 — 純資料側的 placeholder。R3.3 metadata-filter 預計 ship 後 q25/q26 才會成為真正驗收訊號，因此必須先把 runner 評分路徑就緒。

利害關係人：開發者 ssweetcoww（單人專案）；下游消費者是 `eval-runner` markdown report 跟 case study 文件。

## Goals / Non-Goals

### Goals

- 把評分模式變成 schema 第一公民（`eval_mode` 必填欄位）
- Runner 看 `eval_mode` 分岔到三條評分路徑
- 新 metric `episode_set_recall` 獨立 aggregate，markdown report 分段呈現
- 既有 q01-q23 行為與 negative 題排除規則完全不變

### Non-Goals

- 動態 top_k（per-item 提高到 `len(expected_episode_ids)`）— 延後成獨立 change `eval-runner-dynamic-top-k`，原因是會改 retrieval cost / latency aggregation profile，影響面值得獨立 ship 評估
- Hit 門檻 / pass-fail gate — 報原始 recall 數字即可，避免 q25 在 top_k=5 結構性永遠 fail 失去訊號
- R3.3 metadata-filter retrieval 改動本身
- Golden set 題目語意修改（只 migrate 加欄位）

## Decisions

### eval_mode 是 schema 第一公民、每題必填無預設

| 候選 | 描述 | 取捨 |
|---|---|---|
| **A. 每題必填無預設** ✅ | 所有題（含舊題）必須寫 `eval_mode` | 一次性 migration 成本，但避免後續隱含預設導致歧義 |
| B. 預設 `chunk_id`，新題才寫 | 舊題不動，新題寫 enum 值 | 短期成本低，但 schema 真實意圖被預設遮蔽，未來看舊題不知道有沒有想過 mode 問題 |

選 A 因為：(1) golden set 規模小（30 題）migration 成本可忽略；(2) `eval_mode` 是評分契約核心，預設等於把契約藏起來；(3) schema validator 強制每題顯式表態，新 contributor 加題時自然會想 mode 問題。

### enumeration 不設 hit 門檻，報原始 episode_set_recall 數字

| 候選 | 取捨 |
|---|---|
| **C. 報數字不設門檻** ✅ | 沒有 pass-fail 雜訊；趨勢可比較；q25 在 top_k=5 不會結構性紅燈 |
| A. 分題門檻 | 每題自定門檻太主觀；q25 在 top_k=5 只有兩種離散結果，門檻意義稀薄 |
| B. 全域 60% 門檻 + 提高 top_k | retrieval cost / latency aggregation 改動，影響面太大，併進此 change 會稀釋焦點 |

q25 expected 25 集 + top_k=5 → `episode_set_recall` 數學上限 0.20，是已知 ceiling。R3.3 上線後 q25 從目前的 0.04 區間 → 0.20 區間仍是看得到的進步訊號（reach ceiling 也是訊號）。

### Dynamic top_k 拆成獨立後續 change

| 候選 | 取捨 |
|---|---|
| **拆分** ✅ | 評分邏輯先 ship 才能驗 dynamic top_k 是否有效；retrieval cost / latency 影響面值得獨立評估；回滾單純 |
| 合併 | 兩個變動同時 ship 無法歸因；測試矩陣翻倍 |

拆分後，本 change 範圍乾淨：只動 scoring，不動 retrieval input。後續 `eval-runner-dynamic-top-k` 已記入 `docs/roadmap.md` 衍生待 propose 段。

### 與 R3.3 拆分，不合併

| 候選 | 取捨 |
|---|---|
| **獨立 change** ✅ | runner 是 eval 工具層、R3.3 是 retrieval 邏輯層；先 ship runner 才能量 R3.3 baseline 作驗收訊號；R3.3 ~52 tasks 已重 |
| 合併 | 兩件事天然耦合（q25/q26 沒 R3.3 也跑不出高 recall），但職責不同、回滾單元混雜 |

### 新 metric 用獨立欄位 episode_set_recall 而非塞進 recall_at_k

per-item record 新增 `episode_set_recall` 欄位（mode=enumeration 才有值，其他 mode 為 None）。aggregate 階段把兩 metric 分開計算 mean。markdown report 表格從單行 Recall 變兩行：chunk-based n=X / enumeration n=Y。

不混用 `recall_at_k` 欄位的原因：chunk-id 對位跟 episode-set 召回語義不同，混在一起算 mean 沒意義；分開欄位讓 history runs 可以 join 比較。

## Implementation Contract

### 觀察到的行為（acceptance）

跑完 `python -m backend.eval.runners.run --dataset backend/eval/datasets/this-not-that-cool.json` 後：

1. **Schema 驗證**：`backend/eval/datasets/_schema.json` validator 對任何缺 `eval_mode` 的 item 報錯；對 `eval_mode="enumeration"` + 空 `expected_episode_ids` 報錯
2. **Per-item record**：每題 JSON 紀錄含 `eval_mode` 欄位；mode=enumeration 的題 record 含 `episode_set_recall: float`，mode=chunk_id 不含此欄位（或為 None）
3. **Aggregate**：報表 JSON 含兩個獨立 group：
   - `metrics.chunk_based.recall_at_k_mean`（既有，n 不含 enumeration 題）
   - `metrics.enumeration.episode_set_recall_mean`（新，僅 enumeration 題）
4. **Markdown report 表格**：從單行 Recall 變兩行，分別標 `(chunk, n=X)` 與 `(enumeration, n=Y)`
5. **既有負面題行為**：q07/q10 等 `eval_mode=chunk_id` + 空 ground_truth 仍 `recall_at_k=None`、沉默排除（不出現在 chunk_based aggregate mean 但仍計入 `n` 總題數）— 不變
6. **q25/q26 不再消失**：跑完 markdown report 必須看到 enumeration 段的 `n=2` 與對應 recall 數字（≤ 0.20 / ≤ 0.83 視 retrieval 表現）

### 介面 / 資料形狀

`_schema.json` definitions.Item 新增：
```
"eval_mode": { "enum": ["chunk_id", "open_set_lenient", "enumeration"] }
```
required 加 `eval_mode`。`expected_episode_ids` 描述更新並由 oneOf / allOf 規則表達條件 required。

per-item record 新增：
```
"eval_mode": "chunk_id" | "open_set_lenient" | "enumeration"
"episode_set_recall": float | null      # 僅 enumeration mode 非 null
```

### 範圍邊界

**In scope**: schema 加欄位 + migrate 30 題 + runner 評分 dispatch + 新 metric + report 拆段
**Out of scope**: 動態 top_k；hit 門檻；R3.3 retrieval 改動；題目語意修改；judge 模型更動

## Risks / Trade-offs

- **q25 在 top_k=5 數學上限 0.20** → 接受：作為 R3.3 對照組仍有訊號，且為 dynamic-top-k change 預埋動機
- **舊 case study / report 比較會看到 metric 表格從單行變兩行** → 接受：分段才是正確語意；release log 與 case study 註記 metric schema 變動日期即可
- **`open_set_lenient` 評分定義仍偏寬鬆（命中任一 anchor 即 1.0）** → 接受：q24 是唯一用例，未來增多再回頭規範
- **schema 加 required 欄位是 breaking** → Mitigation：同 change 內把 30 題全 migrate；validator 在 CI 跑，落地前必綠
- **enumeration metric 與 chunk metric 分開後，「overall recall」概念消失** → Mitigation：markdown report 明確標 n=X / n=Y，不再呈現混合 overall；release log 與 archive design 註明此 metric schema 改動

## Migration Plan

1. 改 `_schema.json` 加 `eval_mode` enum + 條件 required
2. 寫一次性 migration script 或手動回填 `this-not-that-cool.json`（q01-q23）+ `_pending_review.json`（q24-q30）
3. 跑 schema validator 確認 30 題全綠
4. 改 runner（dispatch + 新 metric + aggregate + markdown report）
5. 跑既有 q01-q23 一輪，確認 chunk_based recall 數字與 ship 前一致（regression 守門）
6. 跑 q24-q30，確認 enumeration 段出現 + 數字合理（q26 預期 > q25）
7. 進 staging review、commit、push

**Rollback**：本 change 純 eval 工具層改動，不動 prod retrieval。Rollback = revert commit + 撤回 schema 變動；舊 q01-q23 不會壞，q24-q30 改回原狀。

## Open Questions

- `episode_set_recall` helper 放 `backend/eval/metrics/recall.py` 同檔還是新檔 `enumeration.py`？apply 階段視 LOC 規模決定（< 30 行則同檔）
- migration 用手動 sed 還是寫一次性 script？apply 階段視題數與一致性需求決定（30 題手動可控）
