## Why

Phase 1 dogfood 同 30 題 failure signal 已從 1/30 → 0/30，q03 SQL typo + transaction 污染等 root cause 全在 `chat-tool-error-isolation`（archive 2026-05-22）修完，Phase 2 翻 `ENABLE_AGENTIC_CHAT=true` default 最後一個 functional blocker 已清。但實際上線前還有一個未處理的呈現缺口：agentic 路徑在 `_agent_result_to_response` 把 `citations=[]` 寫死、`enumeration_episodes` 留 `None`，導致使用者切到 agentic 模式時前端 source 區塊整個不會出現（chip 與 enumeration card 雙雙空白），體驗倒退到比 rule-based 還差。要在翻 default 同時補齊資料層，UI 容器與 UX polish 留待後續 `landing-and-mode-orchestration-redesign` 接手優化。

## What Changes

- 後端 `_agent_result_to_response` 從 `result.tool_calls[].result_full` 蒐集 chunk-level 資料（已含 `chunk_id` / `episode_id` / `episode_title` / `text` / `rrf_score` / `source`），按 `rrf_score` 去重 + top-K 排序填入 `ChatResponse.citations`。
- 後端 `_agent_result_to_response` 從列舉類 tool（`find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date`）的 `result_full` 撿 episode list 填 `ChatResponse.enumeration_episodes`。
- `backend/app/core/config.py` 的 `enable_agentic_chat` default 從 `False` 翻成 `True`。
- 保留 `ENABLE_AGENTIC_CHAT` flag 與 `if settings.enable_agentic_chat` 分支作為 30 天 kill-switch，**不**在本 change 移除 flag 或 rule-based pipeline 程式碼。
- 跑 `backend/eval/datasets/extended-multi-turn-40.json`（34 record / 40 turn，含 4 組 multi-turn dialogs）+ LLM-as-judge 對 Arm D（agentic）一輪，結果落盤 `backend/eval/results/` 作為翻 default 的 eval gate 證據。
- design.md 寫入「翻 default 後 14 天 dogfood 觀察期」驗收條件：prod 每日掃使用者答案內 "技術問題" / "系統錯誤" 字串出現率，超過 threshold 自動 rollback flag。
- 前端**不動**，依賴既有 chip 與 `EnumerationSection` 容器「資料有就渲染、沒就 hide」邏輯自動受益。

## Non-Goals

（皆寫入 design.md 的 Goals/Non-Goals 段，此處從略）

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `chat-agentic-routing`: 新增「agentic 路徑必須回 chunk-level citations」與「列舉類 tool 結果必須填入 `enumeration_episodes`」兩條 ADDED requirements；並調整既有「`ENABLE_AGENTIC_CHAT` flag 預設」描述以反映 default 翻轉。

## Impact

- Affected specs: `chat-agentic-routing`（MODIFIED：新增兩條 ADDED requirements + 一條 MODIFIED）
- Affected code:
  - Modified:
    - backend/app/api/query.py（`_agent_result_to_response` 補 citations + enumeration_episodes mapper）
    - backend/app/core/config.py（`enable_agentic_chat` default `False` → `True`）
    - backend/eval/results/（新增 Arm D 在 multi-turn-40 dataset 的 eval gate 結果檔）
  - New:
    - 無新檔
  - Removed:
    - 無刪檔（flag 與 rule-based pipeline 程式碼留 30 天 kill-switch）
