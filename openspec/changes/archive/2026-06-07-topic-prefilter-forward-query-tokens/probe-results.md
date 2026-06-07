# DB probe（task 3.1，2026-06-07 對 prod，show 政大黑音 `45fc2462…`、cap=12）

用實際 `_TRANSCRIPT_TOPIC_SQL`（雙-CTE union）對 prod DB 跑，token 依 task 1.1 的 D2 fallback-only 規則由 agent 實際入參算出。本機 default jieba 與 prod jieba 對這些詞一致（hybrid probe 已確立 prod 把 `Leo王`→`Leo`）。

## 標靶：b23 thin-topic + query fallback

agent 實際入參 `topic="Leo王"`、`query="迪拉跟 Leo王 第一次見面、從不認識到合作夥伴的故事"`。

- `_expand_to_tokens(["Leo王"])` → `['Leo']` → `_discriminating_tokens` = 1 個 **< 2 → 單看 topic gate 關**（符合 prod smoke `prefilter_source=topic_index`、EP107 0/6）。
- D2 fallback 觸發：生效 token = topic ∪ query = `['Leo','迪拉','第一次','見面','認識','合作','夥伴','故事']`（8 個 ≥2 → gate 開）。
- tsquery = `Leo | 迪拉 | 第一次 | 見面 | 認識 | 合作 | 夥伴 | 故事`，`:tokens` 同源（D4）。

| 指標 | 值 |
|---|---|
| union_size | 22（≤ 2×cap=24 ✓）|
| **EP107（`8b3d4c1d`）在 union** | **TRUE ✓** |
| EP107 via coverage arm | TRUE |
| EP107 via ts_rank arm | TRUE（query 的敘述詞 見面/認識 把 EP107 的 ts_rank 也拉進 cap）|

→ query fallback 如設計把 EP107 撈進候選；narrative 敘述詞同時推升 coverage 與 ts_rank 兩 arm。

## 非回歸：enumeration「高雄 美食」（topic 已 ≥2 → query fallback 不觸發）

`_expand_to_tokens(["高雄美食"])` → `['高雄','美食']`（2 個 ≥2）→ **生效 token = topic-only（query 被忽略，D2）**，與本 change 前位元相同。

| 指標 | 值 |
|---|---|
| union_size | 15（與 hybrid change probe 完全一致）|
| EP85（高雄美食新手任務 ← GT 主集）在 union | TRUE ✓ |
| EP140（高雄美食第二彈 ← GT 主集）在 union | TRUE ✓ |

### 結構性非回歸保證
本 change 對 transcript 路徑只在 **topic 鑑別 token <2** 時介入 query；topic≥2 的 enumeration 題生效 token = topic-only，是 **no-op**（程式上 `transcript_tokens = expanded`、SQL 參數逐位相同）。33+3 單元測試的 `query=None` / topic≥2 分支已斷言位元等價。
