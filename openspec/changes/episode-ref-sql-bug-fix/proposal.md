## Why

`find_episode_by_ref` tool 在所有 chat query 中都炸 `bind parameter 'EP'` error，造成 agent 無法用 `EP\d+` 引用 episode。Dataset 內約 15 題（所有 negative trap + 多數 deep_dive + 部分 cross_episode）受污染，agent 拒答行為從表面看像 grounded refusal、實際是 tool failure-induced refusal。Chat-RAG dataset audit 2026-05-25 在 b27「迪拉胖在 EP1 有提到自己得過什麼嘻哈大賽冠軍嗎？」第一個踩到，audit 流程被迫暫停等修。

## What Changes

- 修正 `_BY_REF_EP_NUMBER_SQL` 內的 PCRE non-capturing group 寫法：`(?:EP|第)` → `(EP|第)`、`(?:集)?` → `(集)?`。Boolean match 語意不變（`title ~*` 只看 match 結果，不取 capture group），但避開 SQLAlchemy `text()` 把 `:EP` / `:集` 誤判為 bind parameter
- 加 unit test 鎖：以 `EP1` / `EP143` / `第19集` 三種 ref 形式驗證 `find_by_ref` 能回傳對應 EpisodeRef
- 加 regression test：對 SQL 字串本身 assert 不含 `(?:` non-capturing group 寫法，防止未來 regress

## Non-Goals (optional)

- 不改 `find_by_ref` 的 fallback `_BY_REF_TITLE_SQL`（這段沒踩同樣坑）
- 不改 `episode_ref.py:extract_episode_ids_from_query`（此處 SQL 不用 PCRE 寫法，沒踩同樣坑）
- 不重新 audit 受污染的 dataset 題目（fix 後 chat-rag dataset audit 自然會用乾淨 prod 行為重跑，audit 是 eval-judge-incorporate-tool-grounding 範疇不在此 change）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `chat-agentic-routing`: `find_episode_by_ref` tool SHALL 正確處理 `EP\d+` 與「第 N 集」reference，不再因 SQLAlchemy bind parameter 衝突 raise StatementError

## Impact

- Affected specs: `chat-agentic-routing`（delta spec：episode reference SQL 行為 requirement）
- Affected code:
  - Modified: `backend/app/services/episode_finders.py`（`_BY_REF_EP_NUMBER_SQL` regex 改寫）
  - New: `backend/tests/services/test_episode_finders_by_ref.py`（unit test + SQL regression assert）
