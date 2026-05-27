# Tasks

Per design goals + 對齊 non-goals「不動 agent SYSTEM_PROMPT / chunking / dataset / 其他 metrics / deterministic grader」:

## 1. Phase 1 — judge input 物理層改 + prompt rubric 改

對齊 design 決策「修 judge input 餵 result_full 而非加新 retrieval」+「Prompt 結構：條件式 + 1 個 example」+「三態 verdict 而非 boolean 或分數」+ Goals 第二三項。實作 spec MODIFIED Requirement「chat-rag LLM judge prompt SHALL incorporate agent tool I/O for grounding」全部 7 個 Scenarios（four-verdict / sees-result_full / contradict-null / refusal-with-correction / pronoun-hallucinated / pronoun-inferred / pronoun-null / retry-once-on-malformed）。

- [x] 1.1 實作 spec MODIFIED Requirement `chat-rag LLM judge prompt SHALL incorporate agent tool I/O for grounding`: 修 `backend/eval/judge_chat_v2.py` 內組 input payload 邏輯，tool_calls 內每個 element 改傳 `result_full`（從 ChatAgentResult.tool_calls[*].result_full 字串拿，per agent-trace-telemetry archive 已存）；保留 `result_summary` 在 envelope 不變；對應 spec MODIFIED Scenario「judge sees full tool result text via the tool_calls payload」
- [x] 1.2 修 `backend/eval/prompts/chat_judge_v2.md`：JSON schema 例子加第 4 個 top-level key `pronoun_attribution_check`，verdict 三態枚舉值依 design 決策「三態 verdict 而非 boolean 或分數」設為 `grounded` / `inferred` / `hallucinated` 純枚舉（無 confidence score）；結構描述 `{"verdict": "grounded" | "inferred" | "hallucinated", "rationale": "<≤80字繁中>"} or null`；對應 spec Scenario「judge returns four structured verdicts in a single call」
- [x] 1.3 在 chat_judge_v2.md 加新 rubric section `## Rubric — pronoun_attribution_check`，含三類 verdict 判定準則 + 條件式描述（只當答案提到具體人名 + expected 涉及多人關係時才跑，否則 null）；明確說明 boolean / 連續信心分被 reject 的理由（LLM calibration 不可信，per design 決策）
- [x] 1.4 在 chat_judge_v2.md 末尾 `## Few-shot examples` 加 Example 4（b23 hallucinated case）：含 EP129 chunk @261.20 完整 result_full text + agent answer + 預期 verdict=hallucinated + rationale 提到「呂安」或「chunk anchor 非 Leo 王」；per memory `feedback_prompt_saturation_more_is_less.md` 只加 1 個
- [x] 1.5 跑 `python -c "from backend.eval.judge_chat_v2 import load_prompt_sha256; print(load_prompt_sha256())"` 驗 prompt sha 變動

## 2. Phase 2 — Unit tests

對齊 design Implementation Contract「3 個 pytest unit test」+ Goals 第一項。

- [x] 2.1 寫 `backend/tests/test_judge_pronoun_attribution.py` 含 3 個 scenario：grounded（fake judge response verdict=grounded） / inferred（fake response verdict=inferred） / hallucinated（fake response verdict=hallucinated）；對應 spec Scenarios「pronoun_attribution_check detects hallucinated person attribution」+「accepts legitimate pronoun inference」+「is null when ... does not involve multi-person attribution」
- [x] 2.2 加 scenario 驗 condition：當 agent_answer 不含具體人名 OR expected 不涉及多人，judge response 內 `pronoun_attribution_check == null`；對應 spec Scenario「is null when the item does not involve multi-person attribution」
- [x] 2.3 加 scenario 驗 judge_chat_v2.py 組 payload 時 tool_calls element 含 `result_full` key（fixture 用一個 fake ChatAgentResult.tool_calls 含 result_full string，呼叫 build_payload，assert payload['tool_calls'][0]['result_full'] != '' and 'result_summary' NOT in element 或 result_summary kept envelope-only — 看現有 build_payload 實作決定）
- [x] 2.4 跑 `pytest backend/tests/test_judge_pronoun_attribution.py -x` 全綠 + `pytest backend/tests/test_judge_chat_v2.py -x` 不 regress

## 3. Phase 3 — Calibration on 5-item mini set（先確認 prompt 改動沒讓既有指標 regress）

對齊 design Risks「Prompt 飽和 / Judge 看 result_full 後對其他指標的影響」mitigations。

- [x] 3.1 確認 `~/.config/podcastrag/e2e-token` + `/tmp/podcastrag_session.txt` 有效（per memory `reference_e2e_backdoor.md`）
- [x] 3.2 對 prod backend RUNNING commit ≥ `f2bd7840` 跑 5 題 calibration: `python -m backend.scripts.run_chat_agent_eval_v2 --filter-ids b14,b15,b27,b23,b20 --output /tmp/judge-v2-calibration.json --report /tmp/judge-v2-calibration.md --prod-commit f2bd7840`
- [x] 3.3 對照舊 baseline `baseline-post-b23-fix-2026-05-27.json` 內這 5 題的 factual / refusal / contradict 分數，確認每題 ±0.1 內無大幅變動（容差用 `abs(new - old) <= 0.15` 衡量；對 boolean / verdict 改變則記下 case）
- [x] 3.4 確認 b23 的 `pronoun_attribution_check.verdict == "hallucinated"`（rationale 含「呂安」或「chunk anchor 非 Leo 王」對等語意）
- [x] 3.5 確認 b14 / b15 / b27 / b20 的 `pronoun_attribution_check` 多數為 `null` 或 `grounded`（這 4 題不涉跨人物代詞）
- [x] 3.6 若任一指標 regress 超過容差或 b23 沒抓到 hallucinated：abort + revert prompt 改動 + 重新評估 rubric 描述；若全綠則進 Phase 4

## 4. Phase 4 — 全集 baseline 重算

對齊 design 決策「Baseline 全集重算」+ Goals 第四項。

- [x] 4.1 啟動全集跑：`nohup python -u -m backend.scripts.run_chat_agent_eval_v2 --dataset backend/eval/datasets/extended-multi-turn-40.json --backend https://podcastrag-api.zeabur.app --session-cookie-file /tmp/podcastrag_session.txt --me-json /tmp/me_resp.json --output backend/eval/results/baseline-post-judge-v2-<DATE>.json --report ... --prod-commit f2bd7840 > /tmp/baseline-judge-v2.log 2>&1 &`；落 PID 到 `/tmp/baseline-judge-v2.pid`
- [x] 4.2 監看 log 直到 RUNNING / FAILED 或 wrote 完成；失敗題目補跑 r2（per `baseline-post-b23-fix-2026-05-27` 跑分過程已建立 SOP）
- [x] 4.3 落盤後跑 jq 驗證 `.provenance.judge_prompt_sha256` 與 Phase 1.5 拿到的 hash 一致；驗 `.provenance.citation_collector_fix_applied == true`、`.provenance.backend_commit == "f2bd7840"`
- [x] 4.4 用 `python -m backend.eval.scripts.diff_baselines --old backend/eval/results/baseline-post-b23-fix-2026-05-27.json --new backend/eval/results/baseline-post-judge-v2-<DATE>.json --dataset ... --output /tmp/diff_judge_v2.md` 出 diff 表

## 5. Phase 5 — Case study + 收尾

- [x] 5.1 寫 case study `docs/case-studies/judge-pronoun-attribution-baseline-<DATE>.md`：含 Phase 3 calibration 對照表 / Phase 4 全集 diff 摘要 / cross_episode 4 題 pronoun_attribution verdict 分佈 / b23 重評後 verdict 確認 / 標舊 baseline `baseline-post-b23-fix-*` deprecated（per memory `feedback_case_studies_no_commit.md` 不入 git）
- [x] 5.2 更新 `project_pending_changes.md` 加進「最近 archive」表 + 寫新乾淨基準（cross_episode chunk_recall 不變，但 factual 可能微動，記新 mean）
- [x] 5.3 同步 `docs/roadmap.md`（per `feedback_roadmap_dual_write.md`）— 把 `judge-pronoun-attribution-check` 從衍生待 propose 移到已完成
- [x] 5.4 release log 草稿（per `feedback_release_log_maintenance.md`），中英雙語講「打分用的 AI 學會看出『把別人故事套到 query 那個人身上』」這種抓得更準的故事
- [x] 5.5 git commit 三筆：prompt 改動單 commit + judge_chat_v2.py 改動單 commit + unit test 一起；commit message 標 `feat(eval-judge): pronoun_attribution_check + judge sees result_full`；本 change **不需要 redeploy prod backend**（eval-only change，per design Migration Plan Phase 4）
- [x] 5.6 git push + spectra archive

## 6. Validate + Analyze

- [x] 6.1 跑 `spectra validate judge-pronoun-attribution-check` 全綠 + `spectra analyze` 0 Critical/Warning
- [x] 6.2 archive 前確認 Phase 3 calibration 通過 + Phase 4 baseline 落盤完整 + b23 verdict=hallucinated 達 success criterion
