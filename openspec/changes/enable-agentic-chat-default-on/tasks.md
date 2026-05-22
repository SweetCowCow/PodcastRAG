## 1. 後端 mapper：Agentic path populates chunk-level citations from search-tool results

- [x] 1.0 實作 spec requirement「Agentic path populates chunk-level citations from search-tool results」並落地 design 決策 D1：citations 從 `tool_calls[].result_full` 撿、不另跑 retrieval。
- [x] 1.1 在 `backend/app/api/query.py` 的 `_agent_result_to_response` 內新增 helper `_collect_agentic_citations(tool_calls)`：遍歷 `tool_calls`，篩 `name in {"search_within_episode", "search_across_episodes", "search_in_episodes"}` 且 `raised is None` 的 entry；從 `result_full["chunks"]` 累計、按 `chunk_id` 去重、按 `rrf_score` 降冪排序、取 top 5；逐筆轉成 `ChunkHit`；遇到 `result_full` shape 不符（KeyError / TypeError）skip 該 tool call 並 `logger.warning`，不 raise。
- [x] 1.2 修改 `_agent_result_to_response` return 語句：`citations=[]` 改成 `citations=_collect_agentic_citations(result.tool_calls)`；其他欄位不動。
- [x] 1.3 確認 helper 呼叫位置在 `result_full` scrub 之前（query.py 617-631 既有邏輯會在 `include_trace=False` 時把 `result_full` 設 None）— helper 必須在 scrub 前對 `result.tool_calls` 跑，避免普通 user 路徑撿不到資料。

## 2. 後端 mapper：Agentic path populates enumeration_episodes from listing-tool results

- [x] 2.0 實作 spec requirement「Agentic path populates enumeration_episodes from listing-tool results」並落地 design 決策 D2：enumeration_episodes 來源 = 列舉 tool 的 result_full。
- [x] 2.1 在 `_agent_result_to_response` 內新增 helper `_collect_agentic_enumeration(tool_calls)`：遍歷 `tool_calls`，篩 `name in {"find_episodes_by_guest", "find_episodes_by_topic", "find_episodes_by_date"}` 且 `raised is None` 的 entry；從 `result_full` 撿 episode list（保留 agent 觀察順序）；按 `episode_id` 去重；逐筆轉成 `EpisodeRef`；空集合回 `None`（非空 list）以維持 schema 語意。Shape 異常 skip + warning。
- [x] 2.2 修改 `_agent_result_to_response` return 語句：加入 `enumeration_episodes=_collect_agentic_enumeration(result.tool_calls)`。

## 3. 後端 unit tests（覆蓋 §1 與 §2 兩條 spec requirement）

- [x] 3.1 在 `backend/tests/` 新增 `test_agent_result_mapper.py`：建立 `ChatAgentResult` fixture，含 (a) 兩個 search tool 共 8 chunk 含 2 個 chunk_id 重複，(b) 一個 find_episodes_by_guest 回 2 episode，(c) 一個 raised=True 的 search tool。驗 `citations` 是 5 entry / 無重複 / 按 rrf_score 排序；`enumeration_episodes` 是 2 entry / 保序。
- [x] 3.2 加 test case：所有 tool 都 raised → `citations=[]`、`enumeration_episodes=None`。
- [x] 3.3 加 test case：`result_full["chunks"]` 缺 key → mapper 不 raise、warning 被 log（用 `caplog`）、其他 tool 正常處理。
- [x] 3.4 加 test case：沒呼叫過任何 search/listing tool（只呼叫 `get_show_overview`）→ `citations=[]`、`enumeration_episodes=None`。
- [x] 3.5 跑 `pytest backend/tests/test_agent_result_mapper.py -v` 驗全綠；跑既有 `test_chat_agent_loop.py` / `test_chat_agent_multi_turn.py` 確認無 regression。

## 4. Flag 翻轉：ENABLE_AGENTIC_CHAT Python default SHALL be true

- [x] 4.0 實作 spec requirement「ENABLE_AGENTIC_CHAT Python default SHALL be true」並落地 design 決策 D3：Flag default 翻轉 + 30 天 kill-switch。
- [x] 4.1 在 `backend/app/core/config.py` 把 `enable_agentic_chat: bool = False` 改成 `enable_agentic_chat: bool = True`。同行 docstring / 註解若有「default false」字樣同步更新。
- [x] 4.2 確認 prod env 4 個 service（backend / worker / dispatcher / beat）的 `ENABLE_AGENTIC_CHAT=true` 維持不動（同 default，行為一致；env 留著作為顯式 kill-switch 保留位）。
- [x] 4.3 確認 `if settings.enable_agentic_chat` 分支與 rule-based pipeline 程式碼**不動**（30 天 kill-switch 由顯式 env false 觸發）。

## 5. Eval gate blocks rollout of agentic chat default

- [x] 5.0 實作 spec requirement「Eval gate blocks rollout of agentic chat default」並落地 design 決策 D4：Eval gate dataset = extended-multi-turn-40 + LLM judge。
- [x] 5.0.1 改 `backend/scripts/run_chat_agent_eval.py` 適配 nested schema：偵測 `items[].turns` list、為 multi-turn item 用同一 `session_id` 串 chat history、`?debug_trace=true` 撿 `tool_calls` 算 `tool_required_hit` / `tool_acceptable_hit` per turn、aggregate 多輪平均。Backward compat 維持 flat schema（this-not-that-cool.json）。
- [x] 5.1 從 backdoor `~/.config/podcastrag/e2e-token` hit `/auth/_e2e_login` 取得 admin session（記憶 `reference_e2e_backdoor.md`），跑 nohup `python3 -u backend/scripts/run_chat_agent_eval.py --dataset extended-multi-turn-40 --backend-url prod --auth-token $SESSION --label agentic-multi-turn-40 --out backend/eval/results/chat_eval_agentic_multi_turn_40_<DATE>.json`。先跑 1 題 canary 驗 debug_trace 回 tool_calls。
- [x] 5.2 跑 LLM-as-judge 對上一步輸出：judge prompt 與 calibration 沿用 `_judge_minisset.json` 校準的版本；輸出 `backend/eval/results/llm_judge_multi_turn_40_2026-05-XX.json` 含每題 `answer_quality` (0-1) + `hallucination_severity` (none/mild/severe) + ordinal-reference 命中欄位。
- [x] 5.3 對照 baseline `backend/eval/results/chat_eval_agentic_2026-05-22.json` 算 delta；驗證 spec 三條 gate criteria：(a) answer_quality mean delta ≥ -0.05、(b) severe hallucination count == 0、(c) 4 組 ordinal-reference dialog ≥ 3 組 episode_id 命中。Gate 不過則 STOP，flag default 不翻、回頭 root cause。
- [x] 5.4 把 gate 跑分結果摘要 append 到 design.md「Decisions § D4」段落底（明確寫日期、mean / severe count / ordinal hit rate 三數字 + 通過判定）。

## 6. Prod smoke + 視覺驗證

- [x] 6.1 翻 default commit 推到 main 並等 Zeabur build 完成（用 `zeabur deployment list --service-id 69eb10360da29f05f49a4b0b` 確認 RUNNING）。
- [ ] 6.2 用 chrome-devtools-mcp 走完整流程：登入 → 進「這不是音樂」節目 → chat tab 發「楊大正上過哪幾集？」→ 確認回應內 EnumerationSection 渲染含 2 集 episode card + 答案文字「2 集」一致 + 截圖。
- [ ] 6.3 chrome-devtools-mcp 同 session 發「歌單那幾集 EP143 主要在講什麼？」→ 確認 ChatBubble 下方紫色 citation chip 區渲染（至少 1 chip）+ 截圖。截圖不入 git（依 `feedback_pptx_qa_jpg_cleanup.md` 規則做完即刪）。
- [x] 6.4 任一步前端出錯（chip 沒出、enum card 沒出、5xx）→ STOP，回頭排查 mapper / 前端 prop。

## 7. 觀察期 SOP 落地

- [x] 7.0 落地 design 決策 D5：14 天 dogfood 觀察期 + 自動 rollback 條件。
- [x] 7.1 把 design.md D5 段「14 天觀察期 + 5% threshold + 人工 rollback」轉成 admin 後台值班 SOP 文件 `docs/runbooks/agentic-chat-observation.md`（依 `feedback_case_studies_no_commit.md` 規則：docs/runbooks/ 不入 git，純記憶）。內容含：(a) 每日掃描查詢 SQL 模板、(b) 5% threshold 公式、(c) rollback CLI 指令範本 `zeabur variable update --id 69eb10360da29f05f49a4b0b -k "ENABLE_AGENTIC_CHAT=false" -y -i=false` + 4 個 service redeploy 範本。
- [ ] 7.2 把觀察期起始日寫進 `project_pending_changes.md` 記憶（archive 後做），方便未來 session 想起來追蹤。

## 8. Archive 與後續（含 design D6：Follow-up 列表落地）

- [ ] 8.1 commit 訊息明確：mapper 改、test、config default 翻、design 補 gate 數字四件分開 commit 或合併一個 commit message 多段描述。
- [ ] 8.2 跑 `/spectra-archive enable-agentic-chat-default-on` 收尾，回流 spec 內容到 `openspec/specs/chat-agentic-routing/spec.md`。
- [ ] 8.3 archive 後在 release log 起草新 entry（依 `feedback_release_log_maintenance.md`）：tag=feature，milestone v1.8，標題「Phase 2 翻牌：agentic chat 成為預設」，描述含 (a) 補 citations + enumeration 資料、(b) flag 翻 default 但保留 30 天 kill-switch、(c) 後續 UIX 由 landing-redesign 接手。
- [ ] 8.4 archive parked change `rag-vs-longcontext-benchmark` 並標記 superseded（spike 已寫成 case study 取代）。
