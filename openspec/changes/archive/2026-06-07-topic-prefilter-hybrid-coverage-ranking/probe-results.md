# Hybrid union DB probe（task 2.1，2026-06-07 對 prod）

用實際 `_TRANSCRIPT_TOPIC_SQL`（雙-CTE union）手動代入參數對 prod DB（show 政大黑音 `45fc2462…`、cap=12）跑。

## 標靶：b23（topic「迪拉 Leo王 合作」→ tokens `[迪拉,Leo,合作]`、tsquery `迪拉 | Leo | 合作`）

| 指標 | 值 |
|---|---|
| union_size | 19（≤ 2×cap=24 ✓）|
| **EP107（`8b3d4c1d`）在 union** | **TRUE ✓** |
| EP107 via ts_rank arm | FALSE（ts_rank #27，出 cap，符合根因）|
| EP107 via coverage arm | TRUE（coverage #4）|

→ coverage arm 如設計把 EP107 撈進候選。

## 非回歸：enumeration「高雄 美食」（tokens `[高雄,美食]`、tsquery `高雄 | 美食`）

| 指標 | 值 |
|---|---|
| union_size | 15 |
| EP85（高雄美食新手任務 ← GT 主集）在 union | TRUE ✓ |
| EP140（高雄美食第二彈 ← GT 主集）在 union | TRUE ✓ |
| EP44（異世界美食家：伴手禮）在 union | FALSE |

### EP44 更正（propose 時誤判已修）

propose 階段的非回歸 probe 把 EP44 列為「現況 cap 內（#9）、純 coverage 替換會掉到 #30」的回歸案例。**該判斷是錯的**：當時排序只用 `best_rank DESC`、漏了真實 `_TRANSCRIPT_TOPIC_SQL` 的 `published_at DESC` tiebreak。實測 EP44 best_rank=0.04137 與 EP127/EP113/EP102/EP97/EP94 等一票集打平，加 published_at tiebreak 後 **EP44 真實排第 15 → 本來就不在現況 cap 12**。故 EP44 不在 union 不是本 change 造成的回歸。

### 結構性非回歸保證（比逐集 probe 更強）

union 的 **by_rank arm 與現況 `_TRANSCRIPT_TOPIC_SQL` 完全相同**（top-cap by `MAX(ts_rank)`, `published_at` tiebreak）。故 **union = by_rank ∪ by_coverage ⊇ by_rank = 現況候選集**——本 change 對 transcript 候選來源只增不減，**結構上不可能掉任何現況已選的集**。真正要驗的「既有 GT 主集不掉」已由 EP85/EP140 在 union 確認。
