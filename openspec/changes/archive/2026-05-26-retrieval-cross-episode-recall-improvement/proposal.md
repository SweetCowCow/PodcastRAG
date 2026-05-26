## Summary

調整三池 RRF 權重（特別是 description 池）以改善「跨集合成 (cross-episode)」題型的 chunk_recall — 試水 / triage 共 5 題（b20/b21/b22/b23 + b29 EP143）系統性低於 0.5。

## Motivation

`eval-judge-incorporate-tool-grounding` apply 後跑出兩輪 baseline，揭露 cross-episode design_type 的 retrieval signal 系統性偏弱：

| item | design_type | chunk_recall_grouped | 觀察 |
|---|---|---:|---|
| b22 | cross_episode | n/a (改題) | audit 時發現答案缺方品融/阿名/杜宗祐 — 跨集 narrative 漏 |
| b29 | leading_question_yes | n/a (acceptable EP143 漏) | retrieve 撈到 EP134/EP41 但 user 親證 EP143 也含「家常味」「家想像」沒被命中 |
| b20 | cross_episode | **0.25** | 答案圍繞 EP134 中老年觀點，但 GT 含跨集 chunks |
| b21 | cross_episode | **0.40** | 答案圍繞 EP143 馬世芳家常味，多集 narrative 只命中 2/5 |
| b23 | cross_episode | **0.33** | 答案圍繞 EP116 迪拉/Leo王，多集只命中 1/3 |

詳細 triage：`docs/case-studies/chat-rag-dataset-audit-2026-05-26-triage-27.md`

模式辨識：當題目跨集合成（譬如「主持人陣容變化」「迪拉跟 Leo 的合作關係」「家常味的多種角度」），retrieval 容易**收斂到單集 transcript chunks**，因為 transcript 池訊號最強、weight=1.0；其他跨集相關訊息散落在各集 description（節目簡介、來賓介紹），但 description 池目前 weight=0.7、且 description chunk 整集只 1 條密度低，被 transcript 池淹掉。

假說：把 description 池權重往上推（候選 0.7 → 1.0 或更高），讓跨集 narrative 題能撈到更多相關集數的 description chunk 進 top-K。

## Proposed Solution

**單一 lever：調整 `backend/app/services/rag.py` 內 `RRF_WEIGHTS` 常數**，無需 DB migration、無需重 embed。

**Design drift 註記（2026-05-26 apply 階段）**：原 proposal 假設「in-process local DB connection」但實際 `backend/.env` 的 `DATABASE_URL` 指向 Zeabur 內部 hostname `db:5432`，本機無法解析。改走 **admin endpoint 路徑**：加 `POST /admin/rrf/sweep` 接收 candidates list，server-side 在 backend process 內每組 monkey-patch `RRF_WEIGHTS` 跑 retrieve_hybrid + chunk_recall_grouped，單一 HTTP 請求拿回所有候選結果。Scope 仍小（一個 admin route + 不到 100 行）；endpoint 是 read-only（不修 DB）+ require_admin gated。

具體步驟：
1. 加 admin endpoint `POST /admin/rrf/sweep`（in-process sweep harness，require_admin gated，read-only）
2. backend redeploy 後 admin call sweep endpoint 拿 6 組候選（baseline 0.7 + 0.85/1.0/1.2/1.5 + sanity 0.3/2.0）對 mini-set (b20/b21/b23 / b15/b16/b17/b19) 的結果
3. 量每組的 `cross_episode_recall_mean` + `deep_dive_recall_mean` 對齊 spec acceptance gate
4. 選最佳 weight、commit 改 `RRF_WEIGHTS` 常數、再次 redeploy、跑全 34 題 baseline 確認 cross_episode 平均 recall 上升且 deep_dive 不退超過 0.05
5. Update spec `rag-query` 的 default RRF weights 數字

## Non-Goals

- **不**動 agent search query rewrite（per memory feedback_prompt_saturation_more_is_less.md，prompt 飽和點已證明過，要修先動 tool layer / RRF）
- **不**重 embed description chunks（既有 v2 embedding 不變）
- **不**改 chunk builder / chunking 邏輯
- **不**動 semantic 池權重（永遠 1.0，不在 RRF_WEIGHTS dict）
- **不**動 title 池權重（試水中沒紅旗）
- **不**改 LLM judge / dataset schema（剛 ship 完 eval-judge-incorporate-tool-grounding，這層穩定）
- **不**改 chat agent loop / tool 定義
- **不**修 b16「世韻」ASR 錯字（屬 asr-known-typos-correction-batch 範圍）
- **不**修 multi-turn EP-ref resolution（屬 multi-turn-epref-resolution-fix 範圍）

## Alternatives Considered

- **加 agent SYSTEM_PROMPT search query rewrite hint**：rejected — prompt 飽和風險（memory 已記錄 R2.x 加 example 反 regress）。weight tuning 是純機械、可量化、可 revert。如果 weight tuning 不夠才回頭考慮。
- **重 embed description chunks 用更大 model**：rejected — 成本高、blast radius 大、改 weight 是更便宜的第一刀。
- **加 cross-episode 專用 retrieval path**：rejected — 過度設計，weight 是 single lever 先試。
- **改 RRF_K（k=60 → k=30 / k=120）**：rejected — weight 是更直接的拉桿，k 是 secondary tuning。

## Impact

- Affected specs: `rag-query`（MODIFIED — RRF weights default 數字 + 對應 example scenario 數字）
- Affected code:
  - Modified:
    - backend/app/services/rag.py（`RRF_WEIGHTS` 常數新值）
    - openspec/specs/rag-query/spec.md（spec sync 在 archive 階段做，這 change 內動 delta）
  - New:
    - backend/eval/scripts/rrf_weight_sweep.py（一次性 sweep harness：對 cross-episode mini-set 跑 N 組 weight 拿 recall@k mean）
    - docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md（sweep 結果 + 選擇邏輯紀錄）
  - Removed: 無
- 部署：純 Python 常數改動 → backend redeploy 即生效（無 DB migration）
- 觀測：prod redeploy 後重跑 v2 triage 34 題 baseline，cross_episode design_type chunk_recall_grouped mean 須 ≥ 之前數字（依 sweep 選定的 expected gain）；deep_dive design_type 該指標不退步
