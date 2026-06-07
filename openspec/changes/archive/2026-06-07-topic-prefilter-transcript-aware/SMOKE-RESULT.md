# Task 5.1 — prod chat smoke 結果（2026-06-06，端到端 NEGATIVE）

部署 commit `599196c`（flag `enable_transcript_topic_prefilter` 預設 on、cap=12）後，
對 prod 打 b23 題 3 次（`backend/scripts/b23_prod_smoke.sh`，admin debug_trace）。

## 發現

| 項目 | 結果 |
|---|---|
| 回歸單元測試 | ✅ 43 passed（episode_finders + guest_dispatch + transcript_aware + topic_prefilter*） |
| DB probe 校準 | ✅ 含動作詞 topic → EP107 排第 3；既有題 EP85 排第 4，皆在 cap=12 內 |
| agent 選的工具（3/3） | ❌ 全部 `search_across_episodes`，**從不** `search_with_topic_prefilter` |
| 本 change 是否被觸發 | ❌ 否——transcript-aware 集選路徑這題完全沒執行到 |
| EP107 進候選 | （N/A，未走本路徑）full-show 撈到 1 個 EP107 chunk，但 EP116 主導 |
| EP107 被正式引用 | ❌ citations = EP116/EP42/EP82 |

## 根因

b23 有**兩個獨立失敗**：
1. **工具 routing**（= b22 維度）：tool 描述已明寫「跨集主題題（例『迪拉跟 Leo 王 怎麼合作』）
   優先 topic-prefilter」，但 agent（gpt-4o）仍選 full-show `search_across_episodes`。
2. **候選集選**需 transcript-aware（= 本 change，已修好 + 驗證）。

本 change 修好 (2)，但被 (1) 擋住——routing 不走 topic-prefilter，本修改就是 dead path。

## 狀態

- task 5.1 **未通過**（端到端未驗到效果）；change **未 archive**。
- 部署維持（flag on）：低 regression——只在 topic-prefilter 路徑 union 加候選、cap 收斂；
  其他真正走 topic-prefilter 的題仍受益。要回退設 `ENABLE_TRANSCRIPT_TOPIC_PREFILTER=false`。
- **待 user 決定下一步**：(i) 開 routing / tool-adherence change（讓 narrative 跨集題真的走
  topic-prefilter，或強制 tool）；(ii) 此題型強制走 topic-prefilter；(iii) 接受 full-show 現況、
  本 change 留著等 routing 修好再驗。
