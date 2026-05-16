## 1. 擴張 regex（落實 `Cross-episode enumeration response shape` MODIFIED 的 enumeration rule pattern scenario）

- [x] 1.1 修改 `backend/app/api/query.py` `_ENUMERATION_RULE_PATTERN` 落實 `Cross-episode enumeration response shape` MODIFIED：從 `r"[哪那]幾集|[哪那]集|[哪那]些集"` 改成 `r"[哪那]幾集|[哪那]集|[哪那]些集|集數?有[哪那]些"`；更新 inline comment 含新句型範例
- [x] 1.2 修改 `backend/tests/test_query_chat_metadata_filter.py` `test_enumeration_rule_pattern_variants`：加 4 個正例 case（「集數有哪些」「集有哪些」「集數有那些」「集有那些」）+ 1 個反例 case（「主持人有哪些」**不**應命中）；既有 6 個 case 保留
- [x] 1.3 跑 `python -m pytest tests/test_query_chat_metadata_filter.py::test_enumeration_rule_pattern_variants -v` 確認全綠

## 2. Prod 驗證

- [ ] 2.1 commit + push backend 變動（無 frontend / migration）；等 Zeabur backend build 綠
- [ ] 2.2 chrome-devtools-mcp 自動化驗證 q26 句型：登入後直接打 chat endpoint with question `"節目裡有講過高雄美食的集數有哪些？"`，assert response.enumeration_episodes 非 null + enumeration_total > 0
- [ ] 2.3 同樣對 q25 句型「節目裡有哪些集是歌單？」打一次（regression check），assert 行為 byte-identical 到 ship 前
- [ ] 2.4 跑 false-positive 檢核：打 `"主持人有哪些人？"`，assert enumeration_episodes 為 null（rule pattern 不該命中、entity extractor 抽不出 guests/topics/date）
- [ ] 2.5 用 eval-runner-chat-enum-scoring 的新 runner 跑一次 prod eval baseline：對比上次 q26 episode_set_recall = 0.333，預期升到 ≥ 0.5；aggregate enumeration mean 應從 0.5467 升

## 3. 收尾

- [ ] 3.1 補 release log entry（v1.7 內，date 2026-05-16 或 ship 日，slug `enumeration-rule-pattern-broaden`，tag `fix`，user-perspective 講「問『高雄美食的集數有哪些』現在也能列出相關集數了 — 之前只認得『哪幾集』這類問法」）
- [ ] 3.2 更新 `docs/case-studies/r33-metadata-filter.md` 補 Stage 10（regex 擴張 + q26 eval lift 數字）
- [ ] 3.3 同步 memory `project_pending_followups.md`：把 q26 持平的 follow-up 標完成
- [ ] 3.4 `/spectra-archive enumeration-rule-pattern-broaden`
