# Answer-model bake-off — 決策註記（2026-06-07）

## 選定模型：gpt-5.1

prod `ai_steps.answer.model` 已由 `gpt-4o` 切為 **`gpt-5.1`**（via `PUT /admin/ai-steps/answer`，
`get_step_config` 每 request 讀 DB → 即時生效、免 redeploy）。base_url / api_key_id 不變（同 AI Hub）。

## Bake-off 數據（9 題 human-verified 子集，5 arms，0 errors）

| 模型 | b23 routing 硬門檻 | factual 均值* | chunk_recall | 每題成本 | 總成本 |
|---|---|---|---|---|---|
| gpt-4o（baseline） | ✗ `search_across_episodes` | 0.831 | 0.55 | $0.028 | $0.249 |
| gpt-4.1 | ✓ prefilter | 0.744（<baseline） | 0.4 | $0.027 | $0.242 |
| **gpt-5.1（選定）** | ✓ prefilter | **0.919（最高）** | 0.5 | **$0.019** | $0.173 |
| gemini-2.5-flash | ✓ prefilter | 0.575 | 0.3 | $0.004 | $0.039 |
| gemini-2.5-pro | ✓ prefilter | 0.865 | 0.6 | $0.031 | $0.279 |

\* factual 均值排除 mt01（expected_answer_summary 為空 → judge 一律 0.0、不可信）。

完整表 + 並排答案：`bakeoff-results.md` / `bakeoff-answers.md`（同目錄）。

## 選定理由（design D2 準則）

1. **硬門檻（honor forced tool_choice）**：4 候選全部 route 到 `search_with_topic_prefilter`；gpt-4o ✗
   （確認此 change 前提成立——gpt-4o 在 14 工具下不 enforce forced function）。
2. **品質**：gpt-5.1 factual 0.919（最高，> baseline 0.831）；推理最細，並排答案中正確識破
   「永和騎機車」段是別的來賓、避開 gpt-4o / gpt-4.1 都犯的代詞錯置幻覺。
3. **性價比**：gpt-5.1 每題 $0.019，候選中最便宜。
4. **行為穩定性**：gpt-5.1 的 tool topic 參數跨 4 次 b23 smoke **完全一致**（`迪拉 Leo王 合作`），
   比 gemini-2.5-pro（`Leo王`/`合作`/`顏社` 飄）可預測。

## 關鍵發現：b23 EP107 是 prefilter 機制限制，非模型問題（→ follow-up）

切 gpt-5.1 後跑 b23 prod smoke ×4：first tool = prefilter（4/4 ✓），但 **EP107 引用 0/4**。
對照 gemini-2.5-pro ×4 為 1/4（命中那次 topic 剛好是單獨「合作」）。

根因（DB 機制）：prefilter = lexical OR-tsquery + ts_rank cap 12。topic 含 entity token（迪拉 / Leo）
在全 show 逐字稿太常見 → 候選池灌爆到 137+ 集 → EP107 best-chunk ts_rank 被 entity-heavy 集壓出
cap 12。**反直覺：加 entity token 反而害 EP107 被埋**；純動作詞「合作」單獨反而能讓 EP107 進候選。

→ 此為 `topic-prefilter-transcript-aware`（b23）change 的 lexical 機制本質限制，**與 answer 模型無關**
（換哪個模型都救不了）。Jacky 拍板（2026-06-07）：EP107 可靠性踢給 follow-up，候選方向 =
design Alternatives 的 plan B（語意向量選集）或「topic 參數去 entity token、只留動作詞」輕量實驗。

## D6 與 b22 的依賴交接

**b22-cross-episode-topic-routing 已解除 block**：answer 模型現為 gpt-5.1，honor forced tool_choice
（b23 smoke first tool = prefilter 4/4 證實）。下一步：

> `/spectra-apply b22-cross-episode-topic-routing`（unpark）→ 跑 task 6 prod smoke 收尾 → archive。

注意：b22 task 6 的 smoke 若也檢查「EP107 引用」，會撞上同一個 prefilter 機制限制（見上）——
b22 的本職是 routing nudge（已驗 first tool = prefilter 生效），EP107 末端可靠性屬 b23 follow-up，
兩者判讀分開。

本 change 不代為執行 b22 apply。
