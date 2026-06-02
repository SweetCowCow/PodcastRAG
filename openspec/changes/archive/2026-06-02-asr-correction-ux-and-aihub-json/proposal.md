## Summary

兩個 EQ2b 上線後衍生的小修：核准 ASR 同音字候選時可當場微調正字（F3），以及偵測回應解析容錯讓更多 AI Hub 模型可用（F5）。

## Motivation

EQ2b（asr-llm-homophone-postprocess）上 prod 後，dogfood 暴露兩個磨擦點：

- **F3 — 核准無法微調**：候選審核只能「核准 / 駁回」，核准即把 LLM 給的 `correct` 原樣寫成規則。但 gemini 偶爾正字差一點（例如對應到清單裡相近但不對的名字），admin 只能駁回後再去「新增規則」手動重打，流程繞。應允許核准當下直接改 `correct`。

- **F5 — 解析過嚴擋掉模型**：`asr_homophone._parse_pairs` 對 LLM 回應的容錯不足。pilot A/B 時 qwen-3-235b / deepseek-v4-pro / claude-sonnet-4-6 在 `response_format=json_object` 下回傳的格式（物件包裹、或仍夾 markdown code block、或鍵名不同）沒被解析出來 → fail-open 回 0 → 這些模型「看起來不可用」。實際是解析端太脆，不是模型不行。強化容錯可擴大可選模型（含更便宜/更強的中文母語模型）。

## Proposed Solution

- **F3 核准可編輯**：
  - 後端 `POST /admin/asr-corrections/{id}/approve` 接受 optional body `{ correct?: str }`；有給就覆寫該規則的 `correct` 再設 `status='approved'` + `enabled=true`；沒給維持原值（向後相容）。
  - 前端 `AdminAsrCorrectionTab` 待審核候選的「核准」改為可編輯：correct 欄位變成可改輸入框（預填 LLM 值），送出時帶 correct。

- **F5 解析容錯**：
  - 強化 `asr_homophone._parse_pairs`：除既有 strip code block + 物件 `pairs`/`corrections` 鍵外，再容忍 (a) 物件直接是 `{wrong, correct}` 單筆、(b) 鍵名大小寫/空白變體、(c) 回應前後夾雜非 JSON 文字時擷取第一個 JSON 陣列/物件、(d) 全形引號。失敗仍 fail-open 回空。
  - 不改 `detect_homophones` 的 RAGEC 流程、post-filter、fail-open 契約本身。

## Non-Goals

- 不動 RAGEC 偵測邏輯、候選清單組成、post-filter 規則。
- 不改預設模型（仍 gemini-3.5-flash）；F5 只是讓「換模型時不會因解析掛掉」。
- 不做核准時編輯 `wrong` / `scope` / `show_id`（規則身分不可變，沿用 EQ2a 既有約束；要改身分仍是刪除重建）。
- 不做批次核准 / 批次編輯。

## Alternatives Considered

- F3 用既有 PATCH 改 correct 再 approve（兩次請求）：流程更繞、且 PATCH 對 pending 候選語意不清；單一 approve-with-correct 較直接。
- F5 改回不要求 `response_format=json_object`：會讓本來正常的 gpt/gemini 變不穩；容錯解析風險更低。

## Impact

- Affected specs: asr-correction-dictionary（候選審核 API approve 加 optional correct 覆寫）、asr-homophone-detection（解析容錯）、admin-asr-correction-ui（核准可編輯）
- Affected code:
  - Modified:
    - backend/app/api/admin/asr_corrections.py
    - backend/app/schemas/asr_correction.py
    - backend/app/services/asr_homophone.py
    - src/AdminAsrCorrectionTab.jsx
    - backend/tests/test_admin_asr_corrections.py
    - backend/tests/services/test_asr_homophone.py
  - New: (none)
  - Removed: (none)
