## Problem

`eval-baseline-citation-bug-revalidation` archive 後 case study 對 cross_episode 4 題（b20/b21/b22/b23）做完整放大鏡 audit，user 親自聽 EP129 逐字稿驗證後揭露 b23 是 **四層連鎖失敗 + dataset GT 半標錯**：

- **b23 retrieval miss**：query「迪拉跟 Leo王 怎麼從不認識變成合作夥伴？第一次見面的故事？」走 `search_with_topic_prefilter(topic="迪拉 Leo 王")`，jieba 拆成「迪拉/Leo/王」三個常見 token 在 `episodes.title_tsvector` + `episode_description_chunks.text_tsvector` 召回 **64 個候選集**（幾乎全 show），但 GT 集（EP107｜迪拉的男團夢 + EP116｜Ft. Leo 王）的 GT chunks 在 retrieve_hybrid + Voyage rerank 後沒進 top-5。
- **b23 LLM hallucination**：agent 落到 EP129｜Ft. 小老虎 的 chunk @261.20（內容是「迪拉跟呂安/茉莉書房漫畫播客主持人」的第一次見面故事），LLM 自動把「他/我/國蛋觀眾」全部代詞解析成 Leo 王，產出「Leo 王跟國蛋是觀眾」這種完全錯的答案；citation 表面真實但語意全錯。
- **b23 dataset GT 半標錯**：`ground_truth_chunk_ids_must` 標的 EP116 @187.48 該段實際是「**小老虎**跟 Leo 王相識（迪拉只是搭橋安排演出）」— dataset auditor 看到「迪拉給我安排演出」就誤判成「迪拉 vs Leo 王」。EP107 @1766.87 / @1819.35 兩個 GT chunks 才是真正「迪拉在 Live house 看表演 Leo 王上前自我介紹」的正確場景。
- **b22 dataset GT 缺漏**：`ground_truth_chunk_ids_must=0` 不是因為「沒答案」— transcript 對 **杜宗祐**（ASR 寫成「杜忠祐」）/ **方品融** / **阿名** 都有 5+ chunks 證據（EP119/EP52/EP94/EP141 等），是 dataset auditor 沒挑代表 chunks。
- **b20 retrieve_hybrid 召回根本問題**：`/admin/diagnose/prefilter-rank` 對 b20 揭露 GT 4 個 chunks 中 2 個（@1790.18 / @1808.78）連 retrieve_hybrid top-100 都不在；1 個（@1719.78）在 rank 77 — chunk-level embedding / chunking / lexical 召回出問題。

## Root Cause

三層獨立根因同時存在：

1. **Dataset audit gap**：b23 EP116 GT 標錯（人物搞錯）+ b22 GT 整個沒挑 — 屬於 dataset quality 議題，過去都是 auditor 一次掃一次審，沒做「逐句檢查代詞指向是否與 query 主體一致」這層校對。
2. **`find_episodes_by_topic` 對「人名關係型 query」召回過寬**：topic 索引設計時針對「歌單 / 高雄美食 / 咖啡」這類主題詞，jieba 拆「迪拉 Leo 王」變成三個常見 token，命中所有 title / description 含這些字的集 → 64 候選集。實際上 `episodes.guests` JSONB（`episode-guests-management` archive 完成）已有結構化 guest 資料可用，但 `find_episodes_by_topic` 路徑沒接。
3. **retrieve_hybrid chunk-level 召回失敗**：b20 + b23 都暴露同個現象 — 即使 episode 縮對，集內 GT chunks 排到 17/23/36/77/MISS，rerank top-30 救不到。可能是 chunking 邊界（一段話被切到 2 個 chunk 各拿半個語意）/ embedding 對齊（query 用人名 + 動作但 chunk 是敘事體）/ lexical weight（人名是低頻 keyword 沒被 BM25 推高）。需要 diagnostic 才知道是哪個 lever。

## Proposed Solution

**Phase 1 — Dataset audit fix（先做，立刻解 b23 / b22 scoring noise）**

- 移除 b23 `ground_truth_chunk_ids_must` 中的 `cb96f6f8-58fb-43fd-bbd6-da1b585d9f60@187.48`（EP116 @187.48，標錯，那段是小老虎-Leo 王）
- 視 listing 結果評估是否補 EP119 等真實有迪拉-Leo 王互動 chunks 進 `ground_truth_chunk_ids_acceptable`（不影響 must 分數）
- b22 補 chunk-level GT：杜宗祐（EP119 @919 / EP52 @377 / EP122 @4324 等）+ 方品融（EP94 @1052 / @1073）+ 阿名（15CM @1360）— 用 `ground_truth_chunk_ids_either` 三層結構（任一命中即算）避免分散 chunks 過嚴
- 寫 dataset audit note 紀錄判斷依據（哪段逐字稿、為什麼算 grounding evidence）

**Phase 2 — Retrieval guest 索引接入（解 b23 候選集召回）**

- `episode_finders.find_episodes_by_topic` 加 guest 索引路徑：當 topic 包含人名 token 時（簡單啟發式：對照 `episodes.guests` JSONB 內的人名 set），優先回傳「title / description / guests JSONB 任一含該人名」的集
- `search_with_topic_prefilter` tool 不變（agent contract 不動），內部 dispatch 多走一條 guest 索引 fallback
- envelope metadata 多回 `prefilter_source: topic_index | guest_index | merged`，方便後續 audit
- 預期 b23 候選集從 64 集縮到 ~5-10 集（EP107 + EP116 + EP119 等真有 Leo 王的集）

**Phase 3 — retrieve_hybrid chunk-level 召回 diagnostic（diagnostic-first，不急著動 code）**

- 用 `/admin/diagnose/prefilter-rank` 擴大 batch（包含 b20 + b21 + b23 三題）+ 加 `--include-bucket-100-to-500` flag 看 GT chunks 在 top-500 排哪
- 對 b20 GT @1790.18 / @1808.78（top-100 都沒有的兩個）逐 chunk 看：embedding cosine sim vs query / lexical tsquery hit count / 周圍 chunks 排名（找是否 chunking 邊界把 GT 切到無語意的 chunk）
- 對 b23 EP107 GT @1766.87 / @1819.35 在 EP107 內排名分析 — 對照 EP107 全集 chunks 排序看是不是 embedding 沒對到 query
- 出 diagnostic report + decision：要不要動 chunking / embedding / lexical weight，根據 root cause 而定
- 若 diagnostic 揭露需 code 變更，則開 follow-up change（不在本 change scope）

## Non-Goals (optional)

- **Agent 代詞解析 grounding**：b23 L2 LLM hallucination（呂安代詞被誤判成 Leo 王）不在本 change scope，留 `agent-pronoun-grounding` follow-up
- **Judge pronoun-attribution check**：b23 L3 judge 給 factual=0.95 沒抓 hallucination 不在本 change scope，留 `judge-pronoun-attribution-check` follow-up（屬 `eval-judge-incorporate-tool-grounding` 後續）
- **ASR 錯字修正**：杜宗祐 → 杜忠祐 ASR backlog 不在本 change scope，b22 GT 用 ASR 實際儲存的「杜忠祐」標記 + dataset audit note 註明
- **重跑全 34 題 baseline**：dataset 修完只跑變動題（b22 / b23）+ b20/b21 對照，不重跑全集（成本 / 時間 trade-off；provenance 紀錄修改前後 hash）
- **Voyage rerank 參數 tune**：原本 voyage-rerank-tune-b22-b23 的方向已證實非 root lever，本 change 不動 rerank 參數

## Success Criteria

1. **Phase 1 完成**：dataset audit diff 顯示 b23 EP116 GT 移除、b22 三人 chunk-level GT 補上；audit note 詳細到「為什麼這個 chunk 算 grounding evidence」逐條可追
2. **Phase 2 完成**：b23 重跑顯示 prefilter 候選集 ≤ 10 集（從 64 降下來）、`prefilter_source=guest_index` 觸發、GT 集 EP107 + EP116 一定在候選集內；search_with_topic_prefilter tool args 不變 / agent contract 不動
3. **Phase 3 完成**：diagnostic report 含 b20 / b23 chunk-level rank 分布 + root cause 判定（chunking / embedding / lexical）+ follow-up change 提案（如需動 code）
4. b23 chunk_recall（重跑）≥ 0.33（3 chunks 命中 1 個就過 — 取決於 retrieve_hybrid diagnostic 結果，但 episode prefilter 對了之後至少 rank 應該往前移）
5. b22 chunk_recall（重跑）≥ 0.33（杜宗祐 / 方品融 / 阿名 三組 either 任一組命中就算）

## Impact

- Affected specs:
  - `rag-eval-dataset`（MODIFIED Requirement: chunk-level GT audit discipline — 需含代詞指向驗證 + 多人名 query 的 three-tier GT 結構使用準則）
  - `chat-agentic-routing`（MODIFIED Requirement: `search_with_topic_prefilter` envelope 加 `prefilter_source` 欄位 + guest_index dispatch path）
- Affected code:
  - Modified:
    - backend/eval/datasets/extended-multi-turn-40.json（b22 / b23 GT 變動）
    - backend/app/services/episode_finders.py（`find_episodes_by_topic` 加 guest 索引 dispatch）
    - backend/app/services/chat_agent/tools.py（`_search_with_topic_prefilter` 接 envelope 新欄位）
    - backend/app/api/admin/diagnose_prefilter.py（Phase 3 擴 top-500 bucket）
  - New:
    - backend/tests/test_episode_finders_guest_dispatch.py（Phase 2 unit test）
    - backend/eval/scripts/dataset_audit_b22_b23.py（Phase 1 audit log 產出工具，local）
    - docs/case-studies/b23-retrieval-diagnostic-2026-05-27.md（Phase 3 diagnostic report，不入 git）
  - Removed: 無
- Affected ops:
  - 部分題目 baseline 重跑成本 ~$0.3（b20 / b21 / b22 / b23 + 對照 4 題 ≈ 8 題）
  - 不重 deploy 全 backend（Phase 2 是新 dispatch path，舊行為當 fallback 保留）
