# Prod b23 smoke（task 4.1，2026-06-07 部署後 commit 2696f4f）

## 回歸測試
`pytest test_episode_finders_transcript_aware.py test_episode_finders.py test_chat_agent_topic_prefilter.py` → **33 passed**。

## 端到端 prod chat smoke：0/6（但**未觸發**本 change 的修正路徑）

部署後對 prod 跑 `b23_prod_smoke.sh` ×6，answer 模型 = gpt-5.1：

| run | agent 傳的 `topic` | prefilter_source | EP107 進候選 | EP107 被引用 |
|---|---|---|---|---|
| 1–6 | `Leo王`（穩定 6/6）| `topic_index` | False | False |

實際 tool args（每次都一樣的形狀）：
```
{"topic": "Leo王", "query": "迪拉跟 Leo王 第一次見面、從不認識到合作夥伴的故事"}
```

### 為什麼 0/6 不是本 change 的失敗
- gpt-5.1 此刻穩定地**把實體放 `topic`、把敘述放 `query`** → `topic="Leo王"` → jieba `['Leo']` = **1 個鑑別 token**。
- transcript 候選來源的觸發 gate 是 `_discriminating_tokens(expanded) >= 2`（本 change **明確不改**，proposal Non-Goals）。1 token < 2 → 走 `topic_index`（title/desc 比對，命中 EP7/EP144 等 4 集）→ **transcript 路徑與其中的 hybrid-coverage 排序整個沒被執行**。
- 對照部署前同支 smoke：gpt-5.1 當時把 `迪拉 Leo王 合作`（3 token）全塞 `topic` → 那才是修前 0/4 的測量條件。模型在「topic vs query 怎麼拆」上會飄；今天穩定拆成單 token。

### 本 change 修正的效力 → 由 DB probe（task 2.1）apples-to-apples 證明
用**會觸發路徑的同一個 3-token topic**「迪拉 Leo王 合作」直接對 prod DB 跑 hybrid union SQL：
- 修前（純 `MAX(ts_rank)`）：EP107 排 #27 → 出 cap、不進候選。
- 修後（hybrid union）：EP107 經 coverage arm #4 → **進 union 候選**（見 `probe-results.md`）。

→ 本 change 在它作用的層（transcript SQL 排序）已證明正確。prod chat smoke 的 `>0/4` 標準被**上游 topic-arg 生成**汙染（agent 把鑑別內容放進 `query` 而非 `topic`），那是本 change 範疇外（proposal 明列「不改觸發 gate、不改 agent routing/tool = b22 範疇」）。

## 衍生發現（b23 端到端真正的剩餘缺口）
b23 端到端要可靠引用 EP107，除了本 change（排序）外，還需上游讓 transcript 路徑**被觸發**——即 prefilter 的 token 來源不能只看 `topic`，需納入 `query`（或 topic 太薄時 fallback 用 query）。此為**新 follow-up**，與 b22-cross-episode-topic-routing 範疇重疊，應併入評估。
