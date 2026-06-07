# Prod b23 smoke（task 4.1，2026-06-07 部署後 commit 50ac924）

## 回歸測試
`pytest test_episode_finders_transcript_aware.py test_episode_finders.py test_chat_agent_topic_prefilter.py test_chat_agent_topic_routing_nudge.py` → **47 passed**（36 + 11 b22 nudge，無回歸）。

## 端到端 prod chat smoke：EP107 候選 5/5、引用 5/5（修前 0/6）✓

部署 RUNNING（22:37）後對 prod 跑 `b23_prod_smoke.sh` ×5，answer 模型 = gpt-5.1：

| run | agent `topic` | prefilter_source | n | EP107 進候選 | EP107 被引用 |
|---|---|---|---|---|---|
| 1–5 | `Leo王`（仍單 token）| **merged** | 24 | **True** | **True** |

對照修前（commit 2696f4f）：同題 6/6 `topic="Leo王"`、`prefilter_source=topic_index`、n=4、EP107 **0/6**。

### 為什麼這次過了
- topic 仍是單 token `Leo王`（gpt-5.1 行為沒變），但本 change 讓 `_search_with_topic_prefilter` 轉發 `inp.query` 進候選選集 → topic 鑑別 token <2 觸發 D2 fallback → 改用 topic∪query 鑑別 token 開 transcript-aware gate。
- `prefilter_source=merged`（topic_index + transcript 兩來源都貢獻）、`n=24`（= 2×cap，hybrid union 滿載）→ **②-觸發層確實打開**（非修前的 topic_index n=4）。
- ③-排序層（hybrid coverage，已部署）把 EP107 排進 union 兩 arm（見 `probe-results.md`）。

### answer 內容驗證（非 citation 假命中）
run1 answer 直接引用「EP107 | 迪拉的男團夢」並撈出逐字稿埋的初遇敘事：
> 他們本來其實是「網友關係」先開始（EP107）… 在真正見面之前，他們已經在網路上聊過一段時間… 「Leo 在 Facebook 幾乎不放自己的照片」…

→ b23 cross-episode narrative 題（GT=EP107）端到端**第一次真的答對**。三層齊全：① b22 強制 `search_with_topic_prefilter`（已部署）→ ② 本 change 轉發 query 觸發 transcript 路徑 → ③ hybrid coverage 排序（已部署）。
