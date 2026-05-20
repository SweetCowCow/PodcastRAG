# Agentic Framework Bake-off — 三 framework 跨指標比較

> Change: `agentic-framework-bakeoff`
> 來源 result：
> - A: `a_native_openai_20260519T100220Z.json`
> - B: `b_pydantic_ai_20260519T161358Z.json`
> - E: `e_google_adk_20260519T164317Z.json`
> 共用 model: gemini-2.5-flash via AI Hub OpenAI-compatible endpoint
> 共用 golden set: `golden_set/bakeoff_40.json`（34 record / 40 turn / 8 design bucket，含 4 題 multi-turn）

## 量化指標總表

| Metric | A 原生 OpenAI | B Pydantic AI 0.0.55 | E Google ADK 1.34 + LiteLLM 1.75 | Winner |
|---|---|---|---|---|
| tool_precision_mean | **0.6438** | 0.4604 | 0.5708 | **A** |
| answer_keyword_hit_mean | **0.3242** | 0.2033 | 0.2921 | **A** |
| latency_p50_ms | **5337** | 5713 | 6347 | **A** |
| latency_p95_ms | 10850 | **10090** | 13640 | **B** |
| latency_mean_ms | **5492** | 5825 | 7436 | **A** |
| cost_total_usd (40 turn) | $0.01466 | **$0.01164** | $0.01521 | **B** |
| multi_turn_final_pass_rate | 0/4 | 0/4 | 0/4 | tie（共通缺陷）|
| LOC | 213 | 212 | 226 | ~tie |

**勝場統計**：A 4 / B 2 / E 0 / tie 2。

## 質化指標（debug 體驗 1-5 分）

> 視角採用：**AI-delegate**（user 把 debug 工作交給 AI Claude 處理）— 評分視角轉換的設計理由見 `docs/case-studies/framework-eval-perspective-shift-2026-05.md`。

| 面向 | A 原生 | B Pydantic AI | E Google ADK |
|---|---|---|---|
| trace 可讀性 | **5** | 2 | 2 |
| stack trace 清晰度 | **5** | 2 | 2 |
| 錯誤訊息可讀性 | **5** | 3 | 4 |
| User 平均 | **5.00** | 2.33 | 2.67 |
| 文件評分（auto-trace） | 4.00 | 2.67 | 3.33 |
| **最終（兩者平均）** | **4.50** | 2.50 | 3.00 |

收集方式：對照本 repo 的 `docs/case-studies/agentic-framework-bakeoff-2026-05.md`「Debug 體驗附錄」9 個 trace scenario + 三 framework 核心結構，以「framework 對 AI debug 友善度」打分。

## 解讀

### A 量化全面領先
- **tool_precision +18 pp 對 B、+7 pp 對 E**：自寫 agent loop + Pydantic schema 自動轉 OpenAI function spec 帶來最高的 tool 選對率
- **answer_keyword_hit 0.32 略低**：問題在 fixture（show overview 沒含主持人姓名）而非 framework；三 framework 都受影響
- **latency p50 + mean 最快**：沒 framework 抽象 = 沒額外 round-trip / serialize 開銷

### B 在 cost + p95 占優
- **cost 21% 便宜**：tool_precision 較低代表 agent 早早 short-circuit 拒答（很多題 0 tool call），token 用量低
- **p95 最佳**：尾延遲穩 — 沒有 retry 失控的長尾
- **但答對率掉 37%**（answer_keyword_hit 0.32 → 0.20）：cost 省下來但結果掉太多，trade-off 不對稱

### E grounding-friendly 但代價高
- **唯一在 `unknown_ref` (EP99999) 場景呼 `find_episode_by_ref`**：tool-eager 行為避免幻覺，A / B 都 0 tool call 直接編回應
- **代價**：latency_p95 13.6s（A 的 1.26x、B 的 1.35x）、cost 最高、LOC 多 6%（含 `_strip_optional` 修 Vertex schema bug）

### multi-turn carry 共通失敗
- **三 framework 全 0/4** — 共通 prompt-plumbing 問題（system message 只注 `focused_episode_id`，沒注 `last_enumeration_episodes` list）
- 這是 design 議題、不是 framework 議題；留待主 change `chat-agentic-tool-routing` 用 L1 state 加 `last_enumeration_episodes` 欄位修

## 推薦結論（量化證據導向）

**建議主 change 採用 A 原生 OpenAI tool calling**：

1. **量化 4/8 項勝出**（tool_precision / answer_kw / latency_p50 / latency_mean），且輸的 2 項（p95 / cost）差距小（p95 7%、cost 25%）
2. **LOC 213 在 budget 內**：自寫 agent loop 沒爆 250
3. **可移植性最強**：純 OpenAI SDK，未來換 provider（Anthropic / Vertex direct）只要換 endpoint
4. **B / E 的優點可反向 port**：
   - 從 E 學「tool-eager prompt」（system prompt 加「先呼 tool 找資料再決定」減 b04/b06/b07 拒答）
   - 從 B 學「strict Pydantic schema」習慣（避免 Vertex schema bug 類問題）

**落選 trade-off**：
- B 適合 cost-sensitive 場景（如本專案未來要跑大量 agent eval），但本 chat use case 答對率比省 $0.003 重要
- E 適合 grounding-critical 場景（如金融 / 醫療），本專案以 podcast 內容查詢為主，可接受偶發拒答 + 用 prompt 補

## How to consume

主 change `chat-agentic-tool-routing` propose 時：
1. 把本檔的「推薦結論」段引進 design.md 的 "Framework decision" section
2. 把 multi-turn carry 共通缺陷的 fix（L1 state 加 `last_enumeration_episodes`）寫進主 change 的 specs
3. 把 E 的 tool-eager prompt + B 的 strict schema 兩個 port-over 寫進主 change tasks
