## 1. Flag 與 HyDE helper（service 層）

- [x] 1.1 在 `backend/app/core/config.py` 的 Settings 新增 `enable_hyde_retrieval: bool = False`，緊鄰 `enable_agentic_chat` 並沿用其慣例。驗證：import settings 後讀到該欄位、預設為 False。
- [x] 1.2 新增 `backend/app/services/hyde_retrieval.py`：`HydeResult` dataclass（`semantic_vec`、`used_hyde`、`hyde_text`、`extra_llm_calls`）+ `async def resolve_semantic_embedding(db, question, base_vec, embedding_cfg) -> HydeResult`。flag off 直接回 `semantic_vec=base_vec, used_hyde=False, extra_llm_calls=0`；flag on 以 `_HYDE_SYSTEM`（沿用 archived `lexical_bakeoff_arms.py` 的常數、註明來源）+ temperature=0 生假設答案文本、embed 該文本當 `semantic_vec`。驗證：flag off 回 base_vec、flag on 回 HyDE 文本向量且 used_hyde=True。
- [x] 1.3 在 1.2 helper 實作 fail-open：HyDE 生成的 step 未設定 / client ctor / LLM error / 空回覆 一律回退 `base_vec`、`used_hyde=False`、log warning、不拋例外（沿用 `_extract_entities_fail_open` 模式）。驗證：人為讓 LLM 拋錯，helper 回 base_vec 且不 raise。

## 2. 在 query.py 三個 semantic retrieve 點接上 helper（routing 維持原向量）

- [x] 2.1 `public_search_show`：保留 `base_vec = embed_texts([question])` 給 `route_episodes`；以 `resolve_semantic_embedding` 取得 `semantic_vec` 餵 `retrieve_hybrid` 的 `query_embedding`，`question` 參數維持原 question。驗證：flag off 時該 endpoint 回傳與改動前一致；flag on 時 routing 仍收原向量。
- [x] 2.2 `query_show` mode=="search"：同 2.1 接法（routing 用 base_vec、retrieve_hybrid 用 semantic_vec、lexical 維持原 question）。驗證：flag off 回歸一致、flag on routing 不變。
- [x] 2.3 `query_show` chat rule-based path：以 `rewritten` 為 question 與 base_vec 來源，`resolve_semantic_embedding` 的 HyDE 文本據 `rewritten` 生成；`route_episodes` 維持 `rewritten` 的 base_vec。驗證：flag off 回歸一致；flag on 時 HyDE 文本對應 rewritten 而非原始輸入。

## 3. 測試與行為等價回歸

- [x] 3.1 新增 `backend/tests/test_hyde_retrieval.py`：(a) flag off → 回 base_vec 且 extra_llm_calls==0；(b) flag on + LLM 正常 → 回 HyDE 文本向量、used_hyde==True；(c) flag on + LLM 拋錯 → fail-open 回 base_vec、used_hyde==False、不 raise。驗證：三案測試全綠。
- [x] 3.2 在 flag 預設 off 下跑既有 query 相關測試（test_error_responses、test_rag_multi_column_bm25、test_chat_agent_topic_prefilter 等），確認行為等價、無回歸。驗證：既有測試套件全綠。

## 4. 擴樣 golden set（先撈現有、不足再 co-draft 補寫）

- [x] 4.1 從 `backend/eval/datasets/extended-multi-turn-40.json` 撈出現有「問句講法 ≠ 答案講法」的詞彙失配題（含 b20/b23），列出 item id + 為何屬詞彙失配，標記為 A/B 標靶集。驗證：印出標靶 id 清單與判定理由，數量計入下一步門檻。
- [x] 4.2 若 4.1 不足 10 題，依 co-draft 紀律（feedback_golden_set_co_draft_flow）逐題與 Jacky 共草補寫至 ≥10 題（每題先講 type + 考驗什麼 + 判斷標準再定 anchor），落入 golden set 並標 human-verified。驗證：標靶集達 ≥10 題、新題皆經 Jacky 確認。

## 5. flag on/off A/B 量測與報告

- [x] 5.1 新增 `backend/scripts/hyde_ab/run.py`：對指定 backend 跑 flag on vs off 兩輪，對 4 的標靶集量每題 must-chunk prefilter-rank 與 calibration 退步集；目標為 prod 時開跑前 curl `/me` 驗 200，失敗 fail loud 中止不產半套報告（依 reference_prod_eval_session、用 playwright-state session + zeabur domain）。驗證：用過期 session 跑 prod 確認中止且無 results 檔。
- [x] 5.2 對 prod 跑完整 A/B（flag 由 env toggle→redeploy→驗證 env 真值→eval，依 feedback_env_toggle_order_discipline），產出 `docs/case-studies/hyde-landing-ab-2026-06-05.md`：含標靶集 on vs off must-rank 對照、calibration 退步檢查、b23 另標「選集層是否本來就召得回」、mixed 評分視角（量化召回 vs 延遲成本）、小樣本限制聲明、記錄 model 與 HyDE 文本樣本。驗證：報告含上述各段、矩陣無 placeholder。

## 6. stop-the-line：預設維持 off，等 Jacky 拍板 flip

- [x] 6.1 確認本 change 未把 `enable_hyde_retrieval` 預設改成 True（git grep 確認 config.py 仍為 `= False`）；報告明記「是否 flip 預設為待 Jacky 依 A/B 證據核准之決定，由後續 change/設定變更落地」。驗證：config.py 預設為 False、報告含 stop-the-line 段。
