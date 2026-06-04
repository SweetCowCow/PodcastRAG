## Summary

對 retrieval-rerank-via-voyage 的 PARTIAL 結果做**全管線 root cause 確認** — 對 b22 / b23 兩題逐一驗證 chat agent → search_with_topic_prefilter → voyage_rerank → citation collector → grader 整條 pipeline 每階段的 I/O 是否符合預期，**只在 root cause 明確之後**才提下一步補救。本 change 不預設答案是 doc payload、不預設答案是 agent routing — 由 diagnose 決定。

## Motivation

Follow-up from `retrieval-rerank-via-voyage`（archived 2026-05-27，commit `336c69d`，PARTIAL）。第二輪 eval 數據：

- **改善題**：b20 0.000→0.250、b21 0.400→0.600（cross_episode chunk_recall）
- **退步題**：b23 0.333→0.000（chunk_recall）、b22 factual 0.65→0.30、b23 factual 0.8→0.4
- 大盤：cross_episode chunk_recall mean 0.244→0.283（marginal up）、factual mean 0.803→0.700（−0.10）

前案例研究列了**兩條候選假說**：

1. b23 → rerank-2.5 對「跨集 narrative 合成」型問題 signal 弱（GT 散在 2 個 episodes）
2. b22 → listing-shape，agent routing 受 chunks 變動干擾

但這兩條都是**推測**。直接跑 doc payload ablation 等於在沒確認 root cause 的情況下花 24 query × judge cost 做實驗 — **如果真因是其他階段（譬如 voyage doc bytes 跟我想的不一樣 / index mapping 有 off-by-one / 某 chunk 沒帶 episode_title），ablation 跑完還是不會解**。

更紀律的做法：**先沿著管線每階段對 b22 / b23 跑單題 query，每階段 dump I/O 對比預期**，root cause 明確才寫程式修。前 session 的 latent citation bug（_AGENTIC_SEARCH_TOOLS 漏 prefilter tool）就是因為沒做這層驗證、把 grader 結果當絕對信號吃下去才被隱藏到 Voyage eval 才暴露。

## Proposed Solution

**兩階段**：

### Stage A — Pipeline I/O Audit（必跑，無 code 改動）

對 b22 / b23 兩題各走一遍：

1. **Grader sanity**：手算 b21（已知 chunk_recall=0.6 的對照組）GT vs citations 對應關係，確認 grader 算分公式跟現場一致 — 避免 grader bug 再次掩蓋真因
2. **Agent topic extraction**：抓 LLM 抽出的 `topic` 字串（args.topic）— 對 b22 應該是哪個關鍵字？對 b23 應該是哪個？
3. **`find_episodes_by_topic` output**：用該 topic 跑 episode_finders，看 candidate episodes 集合 — b23 的兩個 GT episodes 都在裡面嗎？
4. **`retrieve_hybrid(k=30)` pool composition**：候選池 30 chunks 是哪些？GT chunks 命中幾個？rank 落在哪？（task 1.1 of retrieval-cross-episode-chunk-recovery 已有 admin endpoint `POST /admin/diagnose/prefilter-rank`，重用）
5. **Voyage doc payload bytes**：實際送 voyage 的 documents 陣列是什麼？編碼？長度？特殊字元？
6. **Voyage response parse**：voyage 回的 results 陣列 raw 內容 — index / relevance_score 全列；驗 index 範圍是否 ∈ [0, 30)
7. **Index → chunks mapping**：voyage_rerank 用 index 拿到的 chunks 是否真的對應原 retrieve_hybrid pool 同一位置（off-by-one / dedup bug 排查）
8. **Citation collector pickup**：`tc.result_full` 內 chunks 是否完整進 citation pool？經 sort + top-K 後 GT 還在嗎？
9. **Grader 看的 citations**：grader 拿到的 citations 陣列跟 collector 輸出一致？

每步輸出落地到 `docs/case-studies/voyage-rerank-pipeline-audit-2026-05-27.md`，每階段附「實際輸出 vs 預期輸出 vs 結論（match / drift）」三欄。

### Stage B — Targeted fix（只在 Stage A 確認 root cause 後）

依 Stage A 結論定範圍。可能落點：

- **doc payload 問題** → 加 `doc_format` ablation（原 proposal scope）
- **agent routing 問題（b22 走錯 path）** → 修 routing rules 或 prompt
- **voyage response index 問題** → 修 voyage_rerank 內部
- **citation collector 漏 chunks** → 修 collector
- **chunks 缺 episode_title 等 metadata** → 修 `_chunk_to_dict` 補齊
- **grader 公式問題** → 修 grader（影響全 dataset 數據可靠性）
- **Voyage 對中文 long context 真的弱** → 換 provider 或 abandon rerank

**本 change 結尾的 acceptance**：Stage A 寫完 + root cause 明確 + Stage B fix 落地 + 8 題 subset 重跑 gate 過（cross_episode chunk_recall ≥ 0.40 + factual ≥ 0.80）。

如果 Stage A 發現有任何階段 I/O 不符預期 — 不論是不是「修了就解 b22/b23」，都要記進 case study 跟 memory，因為這是同層次的 latent bug（跟 citation collector 那條同樣性質）。

## Non-Goals

- 不預設 root cause（不假設是 doc payload / agent routing / 其他單一原因）
- 不換 rerank provider / model（仍 Voyage rerank-2.5）
- 不調 N（仍 30）
- 不動 b20 retrieval miss（屬另一個 follow-up）
- 不處理 multi_turn ordinal_resolution
- 不擴大 dataset scope
- Stage A 不寫 application code — 純 diagnose tool + case study

## Alternatives Considered

- **直接 doc payload ablation**（原 proposal）：跳過 root cause 驗證、賭一個假說；如果真因在別處，24 query × judge cost 白燒。Rejected by user 拍板要 root cause 紀律
- **revert Voyage**：放棄已驗 b20 / b21 改善換 factual 回穩；trade-off 不對等
- **換 provider（Cohere/Jina）**：成本 / scope 暴增，且不解 b22/b23 退步的 root cause — 換個 provider 還是猜
- **跑全 34 題 v2 baseline 對比**：scope 太大，先 isolate b22/b23 拿 root cause 再說

## Impact

- Affected specs:
  - `chat-agentic-routing`（MODIFIED — Stage B 修法決定後落 spec；Stage A 不動 spec）
- Affected code:
  - New: backend/scripts/audit_voyage_pipeline.py（Stage A pipeline I/O audit 工具 — 對單題抓 9 階段 I/O dump）
  - Modified: `backend/app/services/rag_rerank.py` / `backend/app/services/chat_agent/tools.py` / `backend/app/api/query.py`（待 Stage A 結論決定 — proposal 階段不假設）
  - Modified: backend/eval/graders/chunk_recall_grouped.py（待 Stage A 發現 grader bug 才動）
  - New: docs/case-studies/voyage-rerank-pipeline-audit-2026-05-27.md（Stage A 結果）
