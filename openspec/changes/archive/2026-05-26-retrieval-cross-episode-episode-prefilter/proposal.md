## Summary

加新 chat agent tool `search_with_topic_prefilter(topic, query, k)`：server-side 內部先用 `find_episodes_by_topic` 找候選 episodes，再用 `search_in_episodes` 限縮 retrieve 池 — 解 cross_episode 題型 retrieve 被無關集 description 擠掉的問題。

## Motivation

`retrieval-cross-episode-recall-improvement` (2026-05-26 archive，commit `c93e395`) 的 RCA 揭露：cross_episode 題（b20/b21/b23）chunk_recall 低不是因為 RRF weight 設錯，**而是 search_across_episodes 在整 show pool 內 retrieve 時，topic 相關但不同集的 description chunks 系統性壓過正確集 transcript chunks**。

具體 evidence（從 sweep RCA 抽出）：

| 題 | 觀察 | 結論 |
|---|---|---|
| b21「家常味」 | description weight 0.7 時 top-5 含 4 個正確集 (EP143) transcript chunks → score 0.4；提高 weight 反而把無關集 description 推前 → score 0.2 | 正確集的 GT chunks 已在召回池前列，但**整 show pool 內排名易被擠掉** |
| b23「迪拉/Leo王 合作」 | 同 pattern — 0.7 時 top-3 在正確集 transcript；1.5 時 top-3 變不同集 description | 同 |
| b20「中老年開工」 | 任何 weight 下 GT 都不在 top-5（4 GT chunks 連召回池前 100 都沒進）| **沒有對的集 scope，retrieval 無能為力** |

RCA 結論：cross_episode 題本質上需要「**先 scope 到候選集合再 retrieve**」。Agent 在 multi-turn 場景已會 auto-pin 單集（per `multi-turn-epref-resolution-fix`），但跨集 narrative 題沒有單集可 pin — 需要先用 keyword 找一組候選集，再限縮 retrieve。

既有工具已備齊（`find_episodes_by_topic` + `search_in_episodes`），但 agent 沒被引導用這條 chain — 跨集題它直接呼叫 `search_across_episodes`（整 show pool）。

## Proposed Solution

**加新 tool + 改既有 tool description 引導 agent**（純 mechanical，不動 SYSTEM_PROMPT 避免 prompt 飽和）：

1. **新 tool `search_with_topic_prefilter(topic: str, query: str, k: int=5)`** 在 `backend/app/services/chat_agent/tools.py`：
   - Server-side 內部先 call `episode_finders.find_episodes_by_topic(show_id, [topic])` 拿候選 episode_ids
   - 若候選非空 → call `rag.retrieve_hybrid(query, episode_id_filter=candidate_ids, k=k)` 限縮 retrieve 池
   - 若候選為空 → fallback to `rag.retrieve_hybrid(query, k=k)` 整 show pool（不退化體驗）
   - Return envelope 含 `prefilter_episode_count` + `chunks` + `fallback_to_full_pool: bool`，讓 agent context 可見發生什麼

2. **更新 `search_across_episodes` tool description**：明確說「fallback only — for questions spanning a known topic / theme across episodes, prefer `search_with_topic_prefilter(topic, query)` to avoid topic-related-but-wrong-episode chunks dominating the pool」。Agent 看 OpenAI tool schema description 自己選 tool，不靠 SYSTEM_PROMPT 規則。

3. **不動既有 tool 行為**：`search_across_episodes` / `search_in_episodes` / `find_episodes_by_topic` 三個既有 tool 行為完全不變。新 tool 是 affordance 而非取代。

## Non-Goals

- **不**動 SYSTEM_PROMPT（per memory `feedback_prompt_saturation_more_is_less.md`，prompt 飽和已證明，靠 tool description 引導即可）
- **不**動 RRF_WEIGHTS（已在前一個 change 證實不是 lever）
- **不**重 embed / 不改 chunk builder / 不改 description chunk 切法
- **不**改 `find_episodes_by_topic` / `search_in_episodes` / `search_across_episodes` 既有行為
- **不**做 chunk recovery（另一個 真實 lever，留下一個 change）
- **不**改 agent loop 結構（tool 註冊 + 新 callable 而已）
- **不**改 dataset schema / LLM judge
- **不**做 cross_episode 自動偵測（heuristic 太脆弱；讓 agent 看 tool description 自己選比較穩）

## Alternatives Considered

- **加 SYSTEM_PROMPT 規則「跨集題先 call find_episodes_by_topic」**：rejected — 違反 prompt 飽和紀律
- **改 `search_across_episodes` 自動內部 pre-filter**：rejected — 「偵測 question 是否含 topic-like keyword」是 query understanding heuristic，誤觸發成本高（單集題被誤判跨集會多繞一圈拉長 latency 又可能 retrieve 到無關集）
- **取代 `search_across_episodes`**：rejected — 既有 tool 還是有用（user 問 free-form 無明顯 topic 時整 show 搜還是必要 fallback）
- **動 chunk builder 把 description 切細**：rejected — blast radius 大、要重 embed、本 change scope 之外（留 follow-up）

## Impact

- Affected specs: `chat-agentic-routing`（MODIFIED — tool registry 從 11 → 12 callables，加 `search_with_topic_prefilter`；MODIFY `search_across_episodes` 描述指引）
- Affected code:
  - Modified:
    - backend/app/services/chat_agent/tools.py（加 `SearchWithTopicPrefilterInput` BaseModel + `_search_with_topic_prefilter` async function + 註冊到 TOOLS list；改 `search_across_episodes` tool spec description）
    - backend/app/services/chat_agent/__init__.py（如有 export 列表）
  - New:
    - backend/tests/test_chat_agent_topic_prefilter.py（4 case：happy path / empty prefilter fallback / envelope fields / 不影響既有 tool 行為）
  - Removed: 無
- 部署：純 Python tool 新增 → backend redeploy 即生效（無 DB migration、無 schema change、無 prompt change）
- 觀測：
  - prod redeploy 後重跑 mt + cross_episode 題（b20/b21/b23 + mt02/03/04）對比 baseline，看 agent 是否自發採用新 tool（chunk_recall_grouped + factual_correctness 是否上升）
  - 若 agent 沒主動用 → tool description 還不夠 affordance → 評估是否需要更明確 description 或 SYSTEM_PROMPT 補一條（屬下一輪 follow-up）
