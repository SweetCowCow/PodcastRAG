## 1. Fix code

- [x] 1.1 Fix 1 — `backend/app/services/rag.py`：新增 `_CITATION_TOKEN_RE = re.compile(r"\s*\[\d+(?:,\s*\d+)*\]")` 與 `strip_citations(text: str) -> str` helper；`answer_with_chunks` 回傳 dict / tuple 同時包含 `answer_raw`（含 `[N]`）+ `answer_clean`（strip 過）+ `used_chunk_ids`
- [x] 1.2 Fix 1 整合 — caller (`/query`, `/search` route) 回給前端用 raw；新增 `backend/tests/test_strip_citations.py` 確認 helper 正確去掉單一 `[1]` / 多重 `[2,3]` / 句尾 `[N]` 三種型態
- [x] 1.3 Fix 1 — `backend/eval/runners/run.py` 的 `_query()` 拿 cleaned answer 送 judge；`out_items` 多寫 `answer` 欄位（方便日後對照）
- [x] 1.4 Fix 2 + Fix 3 + Fix 4 — `backend/app/services/llm_prompts.py` 重寫：
  - 拒答條改自然語言範例（X 替換成主題詞）
  - 「禁止編造」拆三層（事實點來源 / 語意彙整可推論 / 片段資訊標明待補）
  - chunks_block 移除 `source_key` 與 `(episode_title)`，只保留 `[N]\n{text}`
  - zh/en 共用骨幹：lang 只決定 surface 字串，不重複整段規則
  - 砍 inline example（`(例如：他在 EP1 提過這件事[1]。)` 那種）
- [x] 1.5 跑 backend pytest 全綠（特別 `backend/tests/test_strip_citations.py` + 既有 prompt 相關測試）

## 2. Push deploy

- [x] 2.1 commit Fix 1 (rag.py + strip_citations test)
- [x] 2.2 commit Fix 1 整合（route caller 改用 raw + run.py 改用 cleaned）
- [x] 2.3 commit Fix 2/3/4 (llm_prompts.py)
- [ ] 2.4 push origin main
- [ ] 2.5 等 Zeabur 4 service redeploy；webhook 不穩時用 `zeabur service redeploy --id 69eb10360da29f05f49a4b0b -y`
- [ ] 2.6 prod smoke：`curl ... /shows/.../search` 確認回應 contract 不變（answer 裡 `[N]` 仍在；不報 500）

## 3. Eval verify

- [ ] 3.1 等 prod 穩定 30 sec 後跑 post-fix eval（同 dataset、同 backend、same top_k=5、metric_level=episode）
- [ ] 3.2 對比 baseline `eval-this-not-that-cool-20260510T120602Z.json` 取 judge_mean / negative_mean / latency_p95
- [ ] 3.3 Gate：judge_mean ≥ 0.7146 才算成功；否則停下來回報「具體哪個 metric 還不夠 + 推測原因 + 下一步」
- [ ] 3.4 寫 `docs/case-studies/r21-prompt-fix-eval-2026-05-10.md`：三輪數字對照（baseline / first post / post-fix）+ pattern 對應 fix 是否生效
