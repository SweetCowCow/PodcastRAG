## Context

`eval-baseline-citation-bug-revalidation` 完成後（2026-05-27 archive，commit `6d8a7aa`），cross_episode 4 題放大鏡 audit 揭露三層獨立根因。**User 親自聽 EP129 逐字稿**證實 agent 答案是 hallucination（誤把呂安故事套用到 Leo 王），同時也發現 dataset GT 自己也標錯（EP116 @187.48 是小老虎-Leo 王互動，不是迪拉-Leo 王）。

**現狀 / 約束**：
- chat-rag dataset v2 schema 已穩定（must / either / acceptable 三層 chunk GT）
- `episode-guests-management` 已 archive，`episodes.guests` JSONB 已落地（含 EP116 = Ft. 小老虎 + Leo 王 / EP119 = 不一定）
- `chat-agentic-routing` 的 `search_with_topic_prefilter` envelope 已含 `prefilter_episode_count` / `fallback_to_full_pool` / `rerank_applied` / `rerank_input_count` 四欄位
- `POST /admin/diagnose/prefilter-rank` 已有，但目前固定 top-100 + 預設 b20/b21/b23 mini_set，需擴

## Goals / Non-Goals

### Goals
- 修 b23 dataset GT（移除 EP116 標錯部份，視需要補 acceptable）
- 補 b22 chunk-level GT（杜宗祐 / 方品融 / 阿名 三組 either 結構）
- `find_episodes_by_topic` 對「人名關係型 query」改走 guest 索引 dispatch（fallback 保留）
- `search_with_topic_prefilter` envelope 加 `prefilter_source` 觀測欄位
- 對 b20 / b23 chunk-level retrieve_hybrid 出 diagnostic report + root cause 判定

### Non-Goals
- 不動 agent 代詞解析 grounding（b23 L2，留 follow-up）
- 不動 judge prompt（b23 L3，留 follow-up）
- 不動 ASR 錯字（b22 用 ASR 實際儲存名「杜忠祐」）
- 不重跑全 34 題 baseline（只跑變動題 + 對照 4 題）
- 不動 Voyage rerank 參數（已證實非 root lever）
- 不動 chunking / embedding code（Phase 3 純 diagnostic，動 code 留 follow-up）

## Decisions

### Phase 1 dataset audit：保留 EP107 GT，移除 EP116 GT，補 b22 三組 either

**選**：b23 `ground_truth_chunk_ids_must` 只留 EP107 @1766.87 / @1819.35 兩個；EP116 @187.48 移除。b22 補 `ground_truth_chunk_ids_either` 三組（每組代表一個人名的 transcript evidence chunks）。
**因為**：
- EP107 兩段是 user 確認的「迪拉自述 Live house 看 Leo 王表演被搭話」場景，視角正確
- EP116 那段 user 親聽證實是「小老虎-Leo 王相識（迪拉只是搭橋）」，不該算 must
- b22 三人物各自 transcript chunks 散在多集，用 either 結構（任一命中即算）避免 must 過嚴
**Alternative considered**：
- 把 EP116 移到 acceptable 區（不影響分數但保留 hint）— 接受，會做
- 完全不修 GT，等 dataset auditor 全集大 audit 再一次 batch — rejected，b23 重跑時 GT 錯會持續放大噪音

### Phase 2 guest 索引 dispatch：啟發式 + envelope 揭露 source

**選**：在 `find_episodes_by_topic` 內加一段「topic 內含 episodes.guests 任一人名 token」的判斷 → 觸發 guest 索引路徑（用 SQL `episodes.guests @> '[{"name": "Leo 王"}]'::jsonb` 或類似查詢）；不觸發則走原 title / description tsquery 路徑。
**因為**：
- 接最低侵入：保留現有 topic 索引行為當預設
- guest JSONB 已是 first-class data，不用新表
- 啟發式雖然不完美但能解 b23 這類顯式人名 query
**Alternative considered**：
- 新增獨立 tool `find_episodes_by_guest_relationship` — rejected，多一個 tool 增加 agent dispatch 負擔
- LLM entity extractor 先抽人名再選 dispatch — rejected，多一次 LLM call 增加 latency + 成本
- 把 guest 索引完全取代 title/description — rejected，會 break 純主題 query（「歌單」「家常味」這類）

`prefilter_source` envelope 欄位用 enum: `topic_index` / `guest_index` / `merged`（兩條路徑都跑 union 結果）。預設 `topic_index`，guest 觸發時改 `guest_index`，未來若需混合則用 `merged`。

### Phase 3 retrieve_hybrid diagnostic：先 audit 不動 code

**選**：擴 `/admin/diagnose/prefilter-rank` 加 `top_n` 上限到 500、加 `include_chunking_context` flag（回 GT chunk 前後 2 個 chunks 的 text / start_time / embedding cosine）+ 加 `--items b20,b23` CLI invocation 對 prod 跑一次 → 寫 diagnostic report `docs/case-studies/b23-retrieval-diagnostic-2026-05-27.md`。
**因為**：
- 「chunking 邊界 / embedding 對齊 / lexical weight」三個 lever 都是改動代價大、回滾代價也大的 retrieval 核心，必須先有數據再動
- diagnose endpoint 已存在，擴 schema 比新 endpoint 便宜
**Alternative considered**：
- 直接動 chunking（譬如改 chunk 長度從 X 秒改成 Y 秒）— rejected，無 data 支撐前的 random tune
- 用 LLM rerank（top-100 拿來 LLM 重排）— rejected，chunk-recovery archive 已證實 Zeabur AI Hub 跑不動

### Phase 4 重跑驗證範圍：只跑變動題 + 對照題

**選**：用 `run_chat_agent_eval_v2 --filter-ids b20,b21,b22,b23` 重跑 4 題對比 `baseline-post-citation-fix-2026-05-27.json`。不重跑全 40 turn。
**因為**：
- 變動只影響 cross_episode 4 題 + b22；其他題不受影響
- 成本 ~$0.15 / 跑一次 vs 全集 ~$1
- provenance 落盤含 `prefilter_source` envelope 變動的事實，未來重對齊不靠記憶

## Implementation Contract

**可觀察的交付**：

1. **dataset 修正**：`backend/eval/datasets/extended-multi-turn-40.json` 內 b23 `ground_truth_chunk_ids_must` 從 3 chunks 變 2 chunks（EP116 那個移除）+ b23 audit_note 加修改說明；b22 `ground_truth_chunk_ids_either` 從空變 3 組（每組對應一個人名 evidence chunks）+ b22 audit_note 寫評分邏輯
2. **episode_finders.find_episodes_by_topic 新 dispatch**：當 topic token 命中 `episodes.guests` JSONB 內人名 set 時，走 guest 索引 SQL（明確分支，可在 log 觀察）；測試 fixture 含「topic='Leo 王'」應該優先回傳 guests 含 Leo 王的集
3. **search_with_topic_prefilter envelope 新欄位**：response 含 `prefilter_source` 三態枚舉；agent contract（tool args / 回傳 chunks 結構）不變
4. **POST /admin/diagnose/prefilter-rank 擴**：接 `top_n` 上限 500、新 flag `include_chunking_context=true` 時 GT chunks 連同前後 2 個 chunks 的 text + embedding cosine vs query 一起回
5. **diagnostic case study**：`docs/case-studies/b23-retrieval-diagnostic-2026-05-27.md` 含 b20 / b23 top-500 rank 分布表 + 對前後 chunk text 的觀察 + root cause 判定（chunking / embedding / lexical 哪個）+ follow-up change 建議
6. **重跑數據對齊**：4 題重跑落盤至 `backend/eval/results/baseline-post-b23-fix-<DATE>.json`（local-only，per `.gitignore`）；diff 表納入既有 case study 附錄

**驗證 done**：
- pytest `backend/tests/test_episode_finders_guest_dispatch.py` 三 scenario 全綠
- prod smoke：對「迪拉跟 Leo 王怎麼從不認識變成合作夥伴」query 觀察 `prefilter_source=guest_index` + `prefilter_episode_count ≤ 10` + 候選集含 EP107 + EP116
- b22 / b23 重跑後 `chunk_recall_grouped ≥ 0.33`（若 Phase 3 揭露需動 retrieve_hybrid 才能達 1.0，則本 change 接受 0.33 作為 Phase 2 成果，動 chunk-level 留 follow-up）
- diagnostic case study 存在且含上述 4 個 section

**Scope in**：dataset audit + guest 索引 dispatch + diagnose endpoint 擴 + diagnostic report + 部份題重跑驗證
**Scope out**：agent 代詞解析 / judge pronoun-attribution / ASR 錯字修正 / chunking-or-embedding code 變更 / Voyage rerank 參數

## Risks / Trade-offs

- **[Risk] guest 索引啟發式判斷錯**：譬如 query「迪拉的開工歌單」也含人名「迪拉」，可能被誤判走 guest 索引 → 錯過原本 topic 索引能找到的 EP134。 → Mitigation：先用「topic 內含 ≥1 人名 token **且** 命中 guests JSONB 人名 set 內 ≥2 個人名」當啟發式（單人名仍走 topic 索引）；fallback 邏輯保留 topic 索引並 union 結果。
- **[Risk] dataset GT 修改影響 archive baselines 對照**：本 change 修 b22 / b23 後，之前 archive 的 `chunk_recall mean 0.283` 數字不再 1:1 對應。 → Mitigation：在 case study 註記「post-b23-fix baseline = X」+ 路線圖標 deprecated 舊數字；provenance metadata 記錄 dataset hash 變動。
- **[Risk] Phase 3 diagnostic 看不出 root cause**：可能 chunking / embedding / lexical 三者各佔一點，沒有單一 lever。 → Mitigation：接受「mixed root cause」結論並建議 follow-up 拆三個獨立 spike（不在本 change scope）。
- **[Trade-off] 只跑變動題 vs 全集**：可能漏掉 dataset / dispatch 變動引發其他題的 regression。 → 對策：同時跑 b21（控制組）+ 隨機抽 4 題 deep_dive 確認沒 regress。

## Migration Plan

1. **Phase 1（無 deploy）**：修 dataset JSON + 寫 audit script + commit
2. **Phase 2（需 deploy）**：episode_finders 改動 → 跑 pytest → push → Zeabur redeploy（backend + worker + dispatcher + beat 4 service）→ smoke b23 query 驗 envelope
3. **Phase 3（無 deploy 改 schema 後 deploy）**：diagnose endpoint 改 + 跑 admin probe → 寫 case study
4. **Phase 4**：重跑 4 題 baseline → diff 表 → archive

**Rollback**：
- Phase 1 dataset：git revert 該 commit 即可
- Phase 2 episode_finders：保留舊 dispatch 為 fallback（env flag `ENABLE_GUEST_DISPATCH` default true，可關），需要 rollback 時 toggle env 不用重 deploy
- Phase 3：純 admin endpoint，無 user-facing impact
- Phase 4：不更動 prod，純 local eval

## Open Questions

- Phase 2 啟發式「≥2 人名 token」是否合理？是否該對單人名 query 也走 guest 索引？等實際跑幾個 query 看結果
- Phase 1 b22 三組 either 內每組要放幾個 chunks？預設 3 個 evidence chunks / 組（總 9 個 either chunks）；要不要更精簡只放 1 chunk / 組（避免 grader noise）— 留 Phase 1 task 內決定
- Phase 3 diagnostic 若揭露 chunking 是 root cause，動 chunking 會否影響其他已 archive 的 retrieval 結論？需 case study 內評估
