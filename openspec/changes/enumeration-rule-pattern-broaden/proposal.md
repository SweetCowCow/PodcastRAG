## Problem

R3.3 + r3-3-chat-enum-grounding 的 enumeration rule pattern 是 `[哪那]幾集|[哪那]集|[哪那]些集`，要求「哪/那」後面必須緊接「集」或「些集」或「幾集」。實際使用 + golden set 都會出現使用者把問句結構翻轉的問法，譬如：

- 「節目裡有講過高雄美食的集數有哪些？」 — 「有哪些」結尾，「哪些」**後面接「？」不是「集」**
- 「歌單的集數有哪些」 — 同上結構
- 「哪些是 podcast 集數」 — 「哪些」後面接「是」

這些問題語意上明顯是列舉題，但 pattern 不會觸發，entity_extraction LLM 也沒抽到 topic 時（譬如 q26「高雄美食」topic 沒被抽到）就完全沒進 enumeration 路徑，使用者得不到「相關集數」清單，chat 答案也只用 top-K=8 chunks 回答。

**量化證據**：2026-05-16 跑 eval-runner-chat-enum-scoring baseline：
- q25「節目裡有哪些集是歌單？」→「哪些集」命中 → episode_set_recall = 0.76 ✅
- q26「節目裡有講過高雄美食的集數有哪些？」→「集數有哪些」**不命中** → chat 回 0 集 → episode_set_recall 持平 0.333 ❌

兩題都是 enumeration 題型、prompt 結構幾乎一樣，只差問句字序，覆蓋率差距太大。

## Root Cause

`backend/app/api/query.py` 的 `_ENUMERATION_RULE_PATTERN` 要求「哪/那」緊接「集」相關字串，無法處理使用者把問句末端寫成「集數有哪些」「集有哪些」的常見句型。

## Proposed Solution

擴張 regex 多接受一條「集數+有+哪/那+些」的反序模板：

```python
_ENUMERATION_RULE_PATTERN = re.compile(
    r"[哪那]幾集|[哪那]集|[哪那]些集|集數?有[哪那]些"
)
```

加上的這條 `集數?有[哪那]些` 同時涵蓋：
- 「集數有哪些」（標準）
- 「集有哪些」（省略「數」字）
- 「集數有那些」「集有那些」（「那」打字錯誤）

不擴張到「哪些是」「有哪些」這種不含「集」的問法 — 因為那會引起 false positive（譬如「主持人有哪些人？」會誤觸發列舉路徑）。pattern 必須含「集」字才安全。

## Non-Goals

- **不改 entity_extraction LLM prompt**：topic 抽取改進是另一條獨立議題，這次只動 rule pattern
- **不改 topic-filter SQL**：topic-filter 行為不變，只是 trigger 條件擴張
- **不擴張到「哪些是」「有哪些」這類無「集」字的句型**：false positive 風險太高（主持人 / 來賓 / 歌單 等可單獨被「有哪些」修飾，但語意未必是列舉題）
- **不動既有「[哪那]幾集」「[哪那]集」「[哪那]些集」三條 pattern**：完全 backward compatible，現有命中題目零受影響

## Success Criteria

1. q26「節目裡有講過高雄美食的集數有哪些？」rule pattern 命中觸發 enumeration，chat 回應帶 `enumeration_episodes` 非 null
2. q25「節目裡有哪些集是歌單？」維持命中（regression check，舊 pattern 完整保留）
3. 「主持人有哪些人？」**不**誤觸發（false positive check — pattern 必須含「集」）
4. unit test `test_enumeration_rule_pattern_variants` 加 3 個新 case + 1 個 false-positive case 全綠
5. prod 重跑 eval baseline，q26 episode_set_recall 從 0.333 升到 ≥ 0.5（aggregate enumeration mean 也應同步升）

## Impact

- Affected code:
  - Modified:
    - `backend/app/api/query.py`（`_ENUMERATION_RULE_PATTERN` regex 加一條 `集數?有[哪那]些`）
    - `backend/tests/test_query_chat_metadata_filter.py`（`test_enumeration_rule_pattern_variants` 加 case）
  - New: 無
  - Removed: 無
- Affected specs:
  - Modified: `rag-query`（`Cross-episode enumeration response shape` 內 enumeration rule pattern scenario 補新句型）
