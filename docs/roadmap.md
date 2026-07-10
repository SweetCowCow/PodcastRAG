# PodcastRAG 路線圖

> 最後更新：2026-07-10（**EQ10 ✅20/20 archive**：1011/1011 集零失敗上線、schedule 零重複 enqueue、smoke 全過、GCP 資源五類全清；下游實測 ~$76（D6 後 $0.053/集）。**EQ12 mobile-rwd ✅ archive**（07-07 真機驗證）。Release log v2.3 兩條目上線。**新 parked change `worker-reliability-and-deeplink-fixes`**：EP326 事故挖出 4 個既有 bug（tasks.py permanent-fail NameError 無限重派、dispatcher 錯派 external row、B2 無終止態、deep-link >50 集失效），proposal/design/specs/tasks 齊備待 Jacky 討論定案 → apply。**EQ16 範圍縮為 B1+T2**（B2/B3/B4 已被新 change 接走）。）
>
> 舊更新：2026-07-02（**Roadmap/Backlog 重定義 + 佇列重排**：Jacky 拍板新定義 — Roadmap＝確認執行、照序走；Backlog＝存想法、不排序。五個新想法編入（EQ11 eval-loop-automation / EQ12 mobile-rwd / EQ13 english-shows-research / EQ14 user-insight-and-landing / EQ15 loop-engineering-pilot）+ 新增 EQ16 轉錄管線韌性（B1+B2+T2 併一條）+ EQ5 重塑為 EQ5′（改用 EQ11 流水線產 golden set）+ EQ8/EQ9 降 Backlog。**EQ10 進行中 12/19**：兩節目已入 prod（塞掐 449/台通 562）、spot VM 全量轉錄跑批中（RTF 26.9x、ETA ~36h）、費用 gate 過（轉錄 ~$14 + 下游 ~$52 topic 大頭 Jacky 拍板照跑）。）
>
> 舊更新：2026-06-11（**序6 R1.3-j judge harness 對齊完成**：校準對齊 prod 真判官（廢 stand-in prompt＋寫死 gpt-4o）、mini-set 40 題補 `expected_behavior`/`expected_answer_summary`（23 題證據先行共審）、拒答感知 scalar、5 模型 bake-off → 新判官 **gemini-2.5-flash-lite** Spearman 0.8365（及格線 0.7 拍板、judge_config drift 依證據收斂）。archive `2026-06-11-r1-3-j-judge-harness-align`。C fallback 未觸發。haiku 因 AI Hub+response_format 回空 `{}` 跳過、fallback 列 follow-up。序6 劃掉，下一動回到序2 EQ5。）｜2026-06-10（**EQ6 RAG 回答 cache 完成**：見序4 列。）｜2026-06-09（**EQ4a `rag.py` 模組拆分完成**：facade re-export 拆 6 子模組、行為零改變、新 spec `rag-service-layout`、prod smoke 200+5 citations、archive。序5 劃掉。下一動回到序2 EQ5 golden set 擴充。）｜2026-06-08（**佇列重整**：發現 EQ4 對話 Agent 核心其實早已 archive + prod default-on（roadmap 原標 ⬜ 為 drift），核心歸入已完成、名下三項拆散重排（rag.py 拆分＝refactor、pronoun-grounding＝獨立小品質、citation-postgen 併入 R2.2）。R1.3 依賴「R3.x 全完」已滿足→解鎖進佇列。待辦改以「🎯 建議執行順序」為權威。EQ7 base image 起手。前次（06-07）b22/b23 retrieval track 完成收尾：EQ3a-f4 b22 routing ✅、EQ3a-f5 b23 narrative ✅（拆三條 + answer-model 切 gpt-5.1，皆 archive），b23 端到端 prod EP107 引用 5/5（修前 0/6）。EQ3a-f3 conditional-HyDE 負結果廢掉。）

本文件記錄 PodcastRAG 後續開發的優先順序與規劃。**排序真相 = 下方「🎯 執行佇列」**；Phase A–F 表是細節背景（多數 Phase A 已完成）。

---

## 📍 Roadmap（2026-07-02 Jacky 拍板，權威排序）

> **定義（2026-07-02 重定）**：Roadmap＝**確認要執行**的項目，沒有意外照此順序做；Backlog＝有想法但不急、**先存起來不排序**。
> 與 memory `project_pending_changes.md` 的同名段**互為鏡像**，更新時兩邊同步（feedback_roadmap_dual_write）。

**狀態圖例**：⬜ 待開　🔵 進行中（active change）　✅ 完成並 archive　⏸ parked

| 序 | 項目 | code | change 名（暫名） | 前置 / 卡點 | 說明與驗收 |
|---|------|------|------------------|------------|---------|
| **0** ✅ | 兩大集數節目歷史轉錄匯入 | EQ10 | `external-transcript-bulk-import`（**20/20，2026-07-10 archive**） | 無 | **完成**：1011/1011 集 transcript+summary 零失敗、schedule 上線（23:00 UTC daily、對已匯入集零重複 enqueue）、prod smoke 全過（三模式+deep-link+external badge）。實測 RTF 0.038（26.3x）、972h 音訊/36.9 GPU-hr；下游 ~$76（D6 後 $0.053/集）。GCP 資源全清。case study：`docs/case-studies/external-transcript-bulk-import-2026-06.md`。衍生 4 bug → `worker-reliability-and-deeplink-fixes`（parked） |
| **1** ✅ | Eval 動態流水線（想法3） | EQ11 | `eval-loop-automation`（16/16，2026-07-03 完成，待 archive） | 無 | **完成**：show profiling（quota 矩陣 + show_facts 環節）、anchor-first 產題（gpt-5.1）、預審分級（判官 gemini-2.5-flash-lite + retrieval rank）、review log + reject 回饋圈、promote 溯源晉升、golden-set-builder skill。**壹加壹首跑：壞題率 15%（gate <40%、基線 75%）、34 題入 `yi-jia-yi.json`、baseline 34/34 可消費**。multi-turn 3 題共草待約時間。case study：`docs/case-studies/eval-loop-automation-first-run.md` |
| **2** ✅ | 手機 RWD（想法4） | EQ12 | `mobile-rwd`（**12/12，2026-07-10 archive**） | 無 | **完成**：P0 節目卡爆寬 / P1 Btn nowrap + citation 卡減層 / P2 dock 收合 + admin 表格橫捲全修；07-07 iPhone Safari 真機逐項驗證通過；specs 同步（added 5/modified 1）；release log v2.3 條目上線 |
| **2.5** ⏸ | worker 可靠性 + deep-link 修復 | — | `worker-reliability-and-deeplink-fixes`（**parked，0/14，artifacts 齊備**） | 等 Jacky 討論 proposal 定案 → `/spectra-apply` | EP326 事故 4 bug：D1 permanent-fail NameError 收尾修（tasks.py）、D2 failure_count 連續 3 次終止（吃掉舊 B2/B3）、D3 dispatcher 對 external: row 短路（B4）、D4/D5 單集 endpoint + deep-link 改打 + 計數修正 |
| **3** | 轉錄管線韌性（範圍縮減） | EQ16 | `transcription-pipeline-resilience`（暫名） | EQ10 ✅ 已解鎖 | **B2/B3/B4 已移轉給 `worker-reliability-and-deeplink-fixes`**；剩 B1 RSS re-sync 偵測 audio_url 變動失效 storage key + T2 轉錄失敗回報使用者（2026-07-01 EP20 教訓） |
| **4** | golden set 流水線後續批次（EQ5 重塑） | EQ5′ | `golden-set-via-eval-loop`（暫名） | EQ11 ✅（流水線已驗證可行） | **壹加壹第一批已隨 EQ11 首跑完成（34 題）**；下一批 = 曼報（invoke golden-set-builder skill 即可）；跑順後套塞掐+台通（EQ10 轉錄完才有料） |
| **5** | 英文節目資訊整合研究（想法2） | EQ13 | `english-shows-research`（暫名） | research 可隨時平行跑 | 版權 deep-research（轉錄/翻譯/摘要衍生著作風險、產業慣例）+ 產品定位 discuss；可行才進 dogfood pilot（技術全復用 EQ10 工具組，痛點案例：Lenny's Podcast — 太長/全英文/主題過濾） |
| **6** | 用戶洞察 + Landing 改版（想法1） | EQ14 | `user-insight-and-landing`（暫名） | 訪談要 Jacky 時間；準備工作隨時 | 問題：家人朋友 get 不到產品的點與用法。順序：訪談腳本 + events 數據分析（Claude 備）→ Jacky 執行 5 訪談 → 依洞察開 landing 價值主張改版 change（5/23 已改架構層，這次是傳達層） |
| **7** | agent 代詞 grounding | EQ4b | `agent-pronoun-grounding` | EQ5′ 先（要量尺） | pronoun 0 hallucinated 維持；judge `pronoun_attribution_check` 綠 |
| **8** | R2.2 prompt + citation 後檢 + UX | EQ3d | `r2-2-prompt-redo`（**併** `agentic-citation-check-postgen` v3b） | EQ5′ + R1.3-j✅ | Faithfulness ≥ 0.71；inline `[N]` 渲染 + hover↔source；citation 後檢驗真 grounding（上次 inline 試法 backfire 過，重新設計）。prompt 已近飽和（feedback_prompt_saturation） |
| **9** | Loop Engineering pilot（想法5） | EQ15 | `loop-engineering-pilot`（暫名，**先 /spectra-discuss**） | 討論可提前 | 收斂「用強模型 + multi-agent loop 優化什麼」（架構債/效能/測試涵蓋）→ 小 pilot（如 multi-agent 全 backend audit 產 tech-debt 清單）驗證工作模式 |

**平行規則**：EQ11 discuss、EQ12 audit、EQ13 research、EQ14 準備工作四項互不衝突也不碰 prod，等批次/gate 的空檔可插著做。

---

### 完整狀態表（含已完成歷史，細節參考）

> 已完成（✅）/ 終結（❌ 廢）/ 延後（⏸）列保留作紀錄；**待辦排序看上方「🎯 建議執行順序」**。

| # | 項目 | change 名（暫名） | 狀態 | 依賴 / 前置 | 驗收標準 |
|---|------|------------------|------|------------|---------|
| **EQ1** | 補 favicon | `favicon-fix`（小修，免開 Spectra） | ✅ | 無 | ✅ 2026-06-01 上線（commit `02c1acf`）：head inline SVG data-URI（indigo 方塊+zap 閃電，呼應站內 logo）；prod 已驗無 /favicon.ico 404、分頁 icon 載入 OK |
| **EQ2a** | ASR 校正字典詞庫 | `asr-correction-dictionary` | ✅ | 無 | ✅ 2026-06-01 完成並 archive（`archive/2026-06-01-asr-correction-dictionary`，commit `bde733a`）：後端+前端+migration 全上 prod；prod 驗證 UI 列表/新增/命中預覽/dry_run 全綠；實機回填「這又沒有很屌」6 條規則共 1507 段（杜忠祐→杜宗祐 362、阿鳴+阿明→阿名 1017、方品龍→方品融 124、龍虎報→龍虎豹、咪有企→滅火器），成本 $0.046；搜尋正字命中驗證通過 |
| **EQ2b** | ASR LLM 同音異義字後處理 | `asr-llm-homophone-postprocess` | ✅ | EQ2a ✅ | ✅ 2026-06-02 完成上 prod（12/12，commit `977d1db`）。**中途大改設計**：開放式 prompt pilot 兩端皆失（gpt-4o-mini 過度激進幻覺、gpt-4o 全 0、recall≈0）→ 改 **RAGEC 候選清單接地**（來賓∪字典正字∪主持人 → LLM 只做「ASR 聽錯→對應回清單」+ post-filter correct∈清單、wrong∈逐字稿）。模型 **gemini-3.5-flash via AI Hub**。核准制+fail-open 不變；pilot 這又沒有很屌 5 集（dry-run $0.014）→ 27 候選人工核准。詳見 design D7 + `docs/case-studies/eq2b-asr-homophone-pilot.md`。**回填 timeout 順手修**（dry-run 改 SQL 計數 98s→3.5s）。follow-up 見下方 F1–F7 |
| **EQ2c** | ASR 校正小修（F3+F5） | `asr-correction-ux-and-aihub-json` | ✅ | 無 | ✅ 2026-06-02 完成+archive（`2026-06-02-asr-correction-ux-and-aihub-json`，commit `1578a49`）。F3 核准可編輯 correct（後端 approve 接 optional correct + 前端可編輯欄位）；F5 `_parse_pairs` 容錯（全形引號/夾雜 prose 擷取/單筆物件/鍵名變體/items 鍵）。prod smoke：qwen-3-235b 解析從 0→有 pair ✓、UI 編輯核准「高明碧→Gummy B-EDIT驗證」寫入驗證 ✓。46 test passed |
| **EQ2d** | ASR 可逆性 + content 同步（F1+F2） | `asr-correction-reversibility-and-content-sync` | ✅ | 無（**F6 前置鎖**，已解） | ✅ 2026-06-02 完成+archive（`2026-06-02-asr-correction-reversibility-and-content-sync`，commit `3326fe9`，9/9，58 test）。`segment.original_text`+`transcript.original_content` snapshot-once + per-episode 還原 API/UI + content 同步（task 2.3 強制重算獨立於 segment 變動）。prod smoke：migration ✓、重跑「這又沒有很屌」回填修好歷史 content（卡拉基 15→0、杜忠祐 89→0、156 集存 original_content）✓、restore 全循環 ✓、admin 還原按鈕渲染 ✓。**F6 前置鎖已解，EQ2e 可開** |
| **EQ2e** | ASR 全面回填（F6）＋回填可觀測/可取消（F8） | `asr-homophone-full-backfill` | ✅ | **EQ2d 完** + 成本 dry-run 估 | ✅ 2026-06-04 完成+archive（`2026-06-04-asr-homophone-full-backfill`，commit `3328cc9`，14/14，64 ASR test，release log v2.2 feature）。F6 偵測原有集數（per-show 序列 driver、只產候選不改文字、不碰 transcription_queue）+ F8 兩 task bind=True 報進度 + `/backfill-status` 五態映射 + `/backfill-cancel` revoke + `/batch-restore` + F-approve（approve 勾 apply_to_existing）。LANGUAGE.md 新增「偵測原有集數/套用原有集數」。prod smoke（曼報）三大驗收全綠（dry-run→真跑→取消 REVOKED 保留 / approve apply 文字被改 / 批次還原）。下一動 = EQ3a unpark |
| **EQ3a** | rerank 調參救 b22/b23 | `voyage-rerank-tune-b22-b23` | ✅ NEGATIVE | — | ✅ 2026-06-04 archive（`2026-06-04-voyage-rerank-tune-b22-b23`）。Stage A 診斷成功＋證偽「voyage 對中文弱」；三題真因：b21 control 正常、b22 沒進 voyage path（routing+distributed-evidence）、b23 topic-prefilter 找不到 transcript-buried 答案（EP107 ts_rank 排不進前 20）。Stage B prefilter-cap NEGATIVE→revert（commit `873f1e3`）。診斷工具 `audit_voyage_pipeline.py` 留存。**衍生 2 follow-up**：b23 transcript-aware retrieval、b22 routing |
| **EQ3a-f1** | 詞彙失配 bake-off | `lexical-mismatch-query-rewrite-bakeoff` | ✅ | EQ3a | ✅ 2026-06-05 archive。比較 query-expansion / HyDE / 多向量，測試案例 b20+b23。**HyDE 勝**→落地走 EQ3a-f2 |
| **EQ3a-f2** | HyDE 落地（flag-gated）+ prod A/B | `hyde-retrieval-landing` | ✅ | EQ3a-f1 | ✅ 2026-06-05 apply+archive（commit `ac15402`）。flag `enable_hyde_retrieval`（預設 **off**）+ `resolve_semantic_embedding` 接 3 entry point + `/admin/diagnose/prefilter-rank` flag-aware + A/B harness + 擴 10 標靶。prod A/B：標靶 avg must-rank 11.2→7.8 但 calibration 退步 3/8（b05 78.7→124.2）→**雙面刃、維持 off 不 flip**。詳見 `project_hyde_conditional_activation_followup` |
| **EQ3a-f3** | HyDE 有條件啟用 | `hyde-conditional-activation` | ❌ 廢 | EQ3a-f2 | ❌ 2026-06-06 **負結果廢掉**（revert）：runtime 召回池訊號（overlap / lexical 分數）結構上偵測不到答案對齊，兩組分不開。見 `project_hyde_conditional_negative_result`。別再走這條 |
| **EQ3a-f4** | b22 routing（強制路由） | `b22-cross-episode-topic-routing` | ✅ | EQ3a | ✅ 2026-06-07 archive（`2026-06-07-b22-cross-episode-topic-routing`）。deterministic nudge：跨集 narrative 題第一輪強制 `tool_choice=search_with_topic_prefilter`（flag `enable_topic_routing_nudge`）+ pinned-episode guard。prod smoke first-tool 5/5。EP107 引用半段交 EQ3a-f5 鏈補齊 |
| **EQ3a-f5** | b23 narrative retrieval | `topic-prefilter-{transcript-aware,hybrid-coverage-ranking,forward-query-tokens}` + `answer-model-bakeoff-and-switch` | ✅ | EQ3a | ✅ 2026-06-07 四條 archive。①來源 transcript-aware（transcript-chunk 候選）②排序 hybrid-coverage（ts_rank ∪ distinct-token coverage union）③觸發 forward-query（agent topic 太薄時用 query token 開 gate）+ answer 模型切 gpt-5.1。**prod 端到端 EP107 引用 5/5（修前 0/6）**。見 `project_session_resume_2026_06_07` |
| **EQ3b** | b20 召回 RCA spike | `chunk-level-retrieval-rca-b20-style` | ⏸ 降級 | 無 | ⏸ b20 詞彙失配根因已被 EQ3a-f1/f2 track 涵蓋（HyDE 把 @1719 rank 78→17）。原始 RCA 目的（查清 @1790/@1808 全 miss）已部分回答：屬歌曲推薦 acceptable 級 GT。除非要追剩餘 chunk-level 失配標靶，否則可略 |
| **EQ3c** | BM25 取代 ts_rank + EP-scoped IDF | `lexical-bm25-replace-ts_rank` | ⏸ **延後**（2026-06-08）| **probe 須先重設計**：舊「混題+aggregate」會把 BM25 贏輸抵消（=05-28 死因）；改成「題型(A 稀有鑑別詞/B 口語常見詞/C narrative)×模式(關鍵字/語意/RAG對話)」分層矩陣、per-question、episode-scoped、流量比例加權判淨效果 | 2026-06-08 拍板延後：改動大、效益不明顯、IDF 假設曾翻車（注意「現在的 BM25」其實是 `ts_rank`，名不副實）。完整討論 + resume checklist：`docs/research/eq3c-bm25-discussion-2026-06-08.md`。先有 probe 定論再碰 code |
| **EQ3d** | R2.2 prompt + citation 後檢 + UX（序 7） | `r2-2-prompt-redo` **併** `agentic-citation-check-postgen`(v3b) | ⬜ | EQ5(序2) + R1.3 judge re-bake-off(序6)；EQ3a–c 已完/延後 | Faithfulness ≥ 0.71；inline `[N]` 渲染 + hover↔source；**citation 後檢驗 `[N]` 真 grounding**（上次 inline 試法 backfire、重新設計） |
| **EQ4** | 對話 Agent（核心） | `chat-agentic-tool-routing` + `enable-agentic-chat-default-on` + ordinal/multi-turn + grounding-v2 + severe-residual-fix | ✅ 核心完成 | — | ✅ **核心已 archive（2026-05-21 主 change，2026-05-22 default-on，prod `enable_agentic_chat=True`）**+ 後續一串強化（ordinal/multi-turn/grounding/residual 皆 archive）。原列名下三項已**拆散重排**：rag.py 拆分→**EQ4a**(序5)、代詞 grounding→**EQ4b**(序3)、citation-postgen→**併入 EQ3d**(序7)。b22/b23 routing nudge 疊在本 agent loop 上 |
| **EQ5** | 評測 / golden set | `golden-set-expand-manbao-yijiayi`（**首要**）→ 後續 R1.3 judge re-bake-off / `eval-runner-dynamic-top-k` / q25 audit | ⬜ | 無（首要可立即動） | 曼報 + 壹加壹各 ≥30 題人工 sentinel；一題一題共草（feedback_golden_set_co_draft_flow） |
| **EQ6** | RAG 回答 cache | `r4-rag-result-cache` | ✅ | — | 2026-06-10 archive。service 層分層快取（embedding+retrieve_hybrid+keyword）三模式共用 + `/search` enriched response 快取；版本失效（corpus_ver/config_ver）；P2 semantic cache flag-off。prod 語意延遲 −95% |
| **EQ7** | Pre-built base image | `o2-prebuilt-base-image` | ✅ | 無 | ✅ 2026-06-08 archive。base-as-cache（GHCR 公開 base + app `FROM` 它 + pip 自癒層 + GHA build workflow）。**prod build ~10 分→~2–2.5 分**、四服務 RUNNING、chat query 200。新 spec `container-build-pipeline` |
| **EQ8** | 詞典系統整合（F4） | `dict-system-integration`（暫名） | ⬜ | **先 /spectra-discuss** | 核准 ASR 校正時自動加進分詞詞典；併 Parking Lot「詞典系統整合/重設計」一起想（兩套詞典職責釐清 + 後台 UI 重設計） |
| **EQ9** | 一般同音異義字修正（F7） | `general-homophone-correction`（暫名） | ⬜ | **先 /spectra-discuss**（風險高） | 非專名通用同音（在來→再來）；過度修正風險高，須先評估方法與防誤改機制，不與 EQ2b RAGEC 混 |

### 🗃️ Backlog（存想法，不排序 — 2026-07-02 重定義）

有想法但不急著做的項目，**不排優先順序**；要動時由 Jacky 升入 Roadmap。

**產品 / 前端**
- U3 用量 Dashboard + 熱搜 chip／A5 整集對話入口／A4 淺色主題／U2 點數計價 + 每月 quota 自動補回／全站登入 gate（Phase 2）
- **查詢模式整合 / 簡化**（2026-06-08 Jacky 提出）：三模式是否太多易混淆。注意「索引」是 2026-05-31 刻意拆出的，合併＝推翻該決策。三條中間路線 + 利弊記於 `docs/research/query-mode-consolidation-backlog-2026-06-08.md`。真要動前先看真實使用分布 + /spectra-discuss

**檢索 / RAG**
- **固定環節結構化抽取**（2026-07-02 Jacky 提出）：節目重複環節的專門記錄與查詢 — 台通片尾「推歌環節」（主持人/來賓推薦 1-2 首歌）、塞掐訪談片尾固定題（最近看的書/影視作品/理財方式）。設計方向：per-show 環節 pattern 設定 → LLM 抽取 → 結構化存放（類 guests JSONB 的 metadata）→ agent 查詢面 + golden set 特化題型聯動（EQ11 流水線的 show profile 已預留 `recurring_segments` 掛鉤）。呼應 b20 歌曲推薦詞彙失配的老難題 — 結構化抽取是比檢索調優更根本的解法
- **EQ3c** BM25 取代 ts_rank + EP-scoped IDF ⏸ — 前置條件：probe 重設計成「題型×模式」分層矩陣（`docs/research/eq3c-bm25-discussion-2026-06-08.md`）
- **EQ3b** chunk-level retrieval RCA（b20-style）⏸ 已降級 — 已被 HyDE track 大致涵蓋
- R3.x 候選：topic seg 自動類別建議／`segment_categories` admin UI／業配段降權／dict weight 通用化
- R5 地端 embedding

**ASR / 詞典**
- **逐字稿轉錄品質加強流程**（2026-07-06 Jacky 提出，試水 5 集人工抽看時觀察）：external 匯入的逐字稿品質還需加強 — 有錯字**和錯誤理解**（語意誤聽，不只專名同音）應該要修正。試水 gate 判「不影響理解就過」先放行上線，但後面要想怎麼**補上系統性的修正流程**（不只 T1 已知錯字清單）。設計時機：EQ10 全量匯入完成後。與 EQ8（詞典整合）、EQ9（通用同音修正）相鄰但範圍更廣 — 含批次回掃已入庫逐字稿的 pipeline。**⚠️ 2026-07-07 D6 起,external 匯入路徑已停用 LLM 同音字偵測（asr_homophone，成本 73%），所以匯入進來的 1006 集完全沒跑同音字修正 —— 這條回掃 pipeline 必須涵蓋「對已匯入集補做同音字偵測」（用批次策略：抽樣/選高價值集/更省模型，而非逐集 gemini-3.5-flash $0.15）**
- **EQ8** 詞典系統整合（F4）— 2026-07-02 從主序降 Backlog：等詞條累積更多才有整合價值。核准 ASR 校正自動進分詞詞典 + 兩套詞典職責釐清 + 後台 UI 重設計（詳細痛點：分詞詞典收了「杜宗祐」但索引仍切「杜宗+祐」落 T3、`POST /admin/tokenizer/reload` 卡 CSRF 403）
- **EQ9** 一般同音異義字修正（F7）— 2026-07-02 從主序降 Backlog：風險高、無急迫性。非專名通用同音（在來→再來），要做先 /spectra-discuss 評估防誤改機制

**Eval 雜項**
- golden set q25 audit expected 對齊／`eval-runner-dynamic-top-k`／rule pattern 涵蓋率月度回顧／haiku via AI Hub `response_format` 空 `{}` fallback
- 新節目 onboarding 收尾包（塞掐/台通 golden set + 新 ASR 詞條）— EQ5′ 流水線跑順後自然消化

**基礎設施 / 安全**
- `enable_agentic_chat` kill-switch 過期 cleanup（30 天觀察期 6/21 已過，可 propose 刪 rule-based 舊碼）
- cookie SameSite=Lax 強化 + **Zeabur Gateway 評估**綁一起做（Gateway 把 `app.podcastrag.app/api/*` 路由 backend → 同源解 SameSite + 去 CORS；docs: zeabur.com/docs/zh-TW/deploy/networking/gateway；限制：不支援 IPv6 IP 控制）
- C1 對話紀錄 → C2 推薦 → C3 權限分級（成本計價線）

### 追蹤規則（2026-07-02 更新）

1. **Roadmap＝確認執行、照序走；Backlog＝存想法、不排序**。唯一排序真相 = 上方「📍 Roadmap」表（完整狀態表只作細節/歷史參考）；`docs/roadmap.md` 與 memory `project_pending_changes.md` 互為鏡像，動一邊就同步另一邊。
2. **開工**：從 Roadmap 最上方未完成項取一條 → `/spectra-propose`（或小修直接做）→ 狀態改 🔵。
3. **完成**：`/spectra-archive` → 狀態改 ✅ + 記 archive 路徑/commit → 問是否補 release log（feedback_release_log_maintenance）。
4. **插隊 / 重排 / Backlog 升級**：只有 Jacky 能改；新議題預設進 Backlog，除非他指定插入 Roadmap 位置。
5. **依賴鎖**：前置未完成不得開工。當前鎖：EQ5′ 鎖 EQ11 討論定案；EQ4b/EQ3d 鎖 EQ5′。（EQ16 已因 EQ10 ✅ 解鎖，但建議先做 `worker-reliability-and-deeplink-fixes` 再開 EQ16 剩餘範圍）
6. **平行例外**：EQ11 discuss / EQ12 audit / EQ13 research / EQ14 準備工作可在等待期插著做（不碰 prod、互不衝突）。

---

## Phase A — 公開準備

| 代號 | 項目 | 狀態 |
|------|------|------|
| — | 競品分析（3 站：sear.newfolderla.com / findtt.top / whatmkreallysaid.com） | ✅ 已完成（產出在 `docs/research/`，未進 commit） |
| — | `admin-llm-step-config`（T3 前置）| ✅ 已 archive 並 deploy（2026-05-03，v0.7）— 重構 admin AI 設定為 `api_keys` + `ai_steps` 雙表 |
| — | `e2e-login-backdoor`（驗證流程基建）| ✅ 已 archive 並 deploy（2026-05-03，v0.8）— `/auth/_e2e_login` env-gated 後門讓 Claude MCP 自動驗證不再仰賴 14 天過期的 storage state |
| **T3** | 每集 AI 摘要（`episode-ai-summary`）| ✅ 已 archive 並 deploy（2026-05-03，v0.9）— map-reduce + idempotent + admin backfill |
| — | `summary-stale-detection`（T3 補強）| ✅ 已 archive 並 deploy（2026-05-04）— cron_tick 每分鐘掃 stale running summary、Celery on_failure handler、`ai_summary_started_at`/`ai_summary_error` 兩欄位 |
| **U1** | freemium 分層 gate（取代「全站登入 gate」原計畫）| ✅ 已 archive 並 deploy（2026-05-04，v1.0）— LandingPage、公開段落搜尋（IP rate limit 20/day）、登入解鎖 LLM 答案、quota 申請流程 |
| **O1** | 自有網域 + ZSend Email | ✅ 已上線（2026-05-04）— `podcastrag.app` 透過 Zeabur registrar 購買，前後端綁 `app./api.`，ZSend 整合 `noreply@podcastrag.app`。**SameSite=Lax 改動留為 polish change**（現 samesite=none 仍可運作；切 lax 需先廢棄 zeabur.app 子域）|

### T3：每集 AI 摘要（NEW，源自競品分析 A1）
- 批次跑 LLM 寫每集 80–150 字摘要（**不**做 `ai_display_title`，討論決定）
- DB 加 `episodes.ai_summary / ai_summary_status / ai_summary_generated_at / ai_summary_model`
- 轉錄完成後鏈式 enqueue Celery task；map-reduce（chunk=12K token，3 retries）
- 走 `ai_steps.summary` step 拿 endpoint / model
- UI 在 PodcastSelect / QueryPage / TranscriptPage 三處顯示，失敗 fallback 原 RSS 描述（對使用者隱藏）
- Admin Queue Tab 加 summary badge + 失敗重跑 + 「批次補摘要」一鍵
- 規模 32 tasks，成本一次性 657 集 < $1

### ~~U1：全站登入 gate + 註冊流程細化~~ → 已轉為 freemium 分層 gate（archive 2026-05-04）
- 改採「先讓人看到價值再要登入」設計：select/transcript 完全公開、段落搜尋免登入（IP rate limit 20/day）、LLM 答案需登入消耗 quota
- Google SSO 一鍵直接 active（無 pending / approval queue / email 驗證）
- Quota 用完不自動補回，使用者主動透過「申請更多額度」按鈕送 quota_requests
- Beat 每 12 小時彙整 pending 申請寄給 admin（ZSend 已開通，2026-05-04 起可實際寄信）

### ~~O1：自有網域 + SameSite=Lax~~ → 網域 + ZSend 上線（2026-05-04）；SameSite=Lax 留為 polish
- ✅ 透過 Zeabur registrar 購買 `podcastrag.app`（$14.99/yr，自動 Cloudflare DNS，Let's Encrypt cert）
- ✅ `app.podcastrag.app` 綁 frontend service、`api.podcastrag.app` 綁 backend service
- ✅ Google OAuth Console 加 `https://api.podcastrag.app/auth/google/callback` redirect URI
- ✅ 4 個後端 service env 更新：`FRONTEND_ORIGIN` 加新域、`GOOGLE_REDIRECT_URI` 切新域
- ✅ ZSend 啟用 + 加 sending domain `podcastrag.app`（SES region ap-northeast-1）+ 6 DNS records (3 DKIM + MX + SPF + DMARC) + API key 產出 + env 部署完
- ✅ ZSend URL bug 修正（commit `c0e88fc`：原本猜的 `zsend.zeabur.app/api/v1/send` 實際是 `api.zeabur.com/api/v1/zsend/emails`）
- ⏳ **未做**：cookie SameSite=none → lax（需先廢棄 `*.zeabur.app` 子域才能切，否則跨網域 fetch 不會帶 cookie）

---

## Phase B — 品質基線

| 代號 | 項目 | 說明 |
|------|------|------|
| **R1** | RAG 評測框架 | golden set + recall@K + regression。**必做**，否則 R2/R3 矇著眼改。R1.1 ✅ / R1.2 ✅ / R1.3 ⏸（指標觀察及通知機制，等 R3.x 完再做） |
| **R1.3** ⏸ | 指標觀察及通知機制 | Langfuse trace + admin Dashboard 視覺化（Recall@5 / Faithfulness 趨勢、thumbs ratio）+ threshold alerting + qa_feedback thumbs-down 餵回 sentinel + judge calibration debt（gpt-5-nano Spearman 0.414 → 重 calibrate）+ JSONB events 表查詢加速。**等 R3.x（R3.2 / R3.3 + 衍生候選）全跑完才啟動** — 那時指標才有故事可說 |
| **U3** | 使用量追蹤 Dashboard + 熱搜 chip | admin 看誰在燒額度，每人查詢趨勢；🆕 含 A3：QueryPage 空狀態顯示 7 日熱搜 chip 引導新使用者 |

---

## Phase C — RAG 真正優化

⭐ **優先級拉到最前**（2026-05-07 review）：R1.2 baseline Recall@5 = **2.4%**，純語意檢索在 162 集 show 直接破功 — R3 是當前 product quality 最大瓶頸。

R3 拆三段做（每段都跑 eval baseline 對照升幅）：

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **R3.1** ✅ shipped 2026-05-08 | Hybrid retrieval 核心 | R1 ✅ | (a) Chunk 重定義：30-60s / 5-10 segments + 前後 1 seg overlap；(b) jieba 分詞 + tsvector + 自訂詞典 (29 詞 manual seed)；(c) pgvector + tsvector RRF 融合；(d) Episode description 進 BM25（556 集）。**結果**：episode-level Recall@5 從 2.4% → 23.8%（10x），Recall@20 = 62%。詳見 `docs/case-studies/r31-hybrid-retrieval-rollout.md`。**併入 R3.2 的 carry-over**：description chunks 在排序壓 transcript anchor (cap 或 down-weight)、通用詞 dict 條目造成 noise (節目名類)、eval metric 加 episode-level flag |
| **R3.2** ✅ shipped 2026-05-11~13 | 兩層檢索 + topic segmentation（4 個 changes 全 archive） | R3.1 | (1) `r3-2-two-layer-topic-seg` — topic seg backfill 全綠（保留 in prod）；two-layer routing 在 r3-5 被關掉；(2) `r3-2-retrieval-fix` — Phase 1 lever test 證實 Recall ceiling 結構性，**但結論被 r3-5 推翻**（測試集污染）；(3) `chunking-version-coexistence` — schema 已 ship；(4) `description-retrieval-prefer-v2` — prefer-v2 + RRF DISTINCT + P95 -56% 已 ship。詳見各 archive design.md 的「2026-05-13 archive follow-up」段 + `docs/case-studies/r32-routing-regression-2026-05-11.md`（5/13 follow-up 結論作廢）|
| **R3.4** ✅ shipped 2026-05-12~13 | text-embedding-3-large + dual-write | R3.1 | embedding model 從 `text-embedding-3-small` 升級到 `text-embedding-3-large`（3072 dim）。原本 ship gate（D4）作廢 — 真正瓶頸是 routing 不是 embedding，詳見 archive design.md D7 follow-up |
| **R3.5** ✅ shipped 2026-05-13 (v1.7) | 關掉 two-layer routing | R3.2 | `ENABLE_TWO_LAYER_ROUTING` env default 翻 false；同 archive 把 golden set audit 結果（移 36 LLM-auto 壞題、補 q05 EP66 anchor、加 staging 守門）固化；human-curated Recall@5 0.0625 → **0.4375 (7x)**、P95 2170ms（< 4500ms gate）。詳見 archive design.md D2-D7 |
| **R3.3** ✅ shipped 2026-05-16 (v1.7) | Metadata filter + 三池 BM25 + cross-episode enumeration | R3.2 ✅ | (a) RSS regex 抽 guests → `episodes.guests` JSONB + admin 編輯 tab（93/164 集有 guests）；(b) `episodes.title_tsvector` Python-side jieba populate（558 集 backfill）；(c) 三池 RRF（chunk 1.0 / desc 0.7 / title 0.5）weight 線上可調；(d) LLM `entity_extraction` step (gemini-2.5-flash-lite) 抽問句 guests+date，fail-open；(e) ChatResponse 加 `enumeration_episodes` + frontend EnumerationSection（guest 名 / date / 「[哪那]幾集」rule pattern 任一觸發）；(f) Prod fix：那/哪 widen + malformed JSON salvage。**Prod 驗證**：Recall@5 0.86 (n=28 chunk_id)，馬世芳/楊大正 enum 正確；title pool live 但對此 dataset 不換 top-K（weight 設計上保守）。**Follow-up `r3-3-chat-enum-grounding` ✅ shipped 同日**：chat 答案 grounding（楊大正 chat 文字「1 集」→「2 集」對齊）+ topic-trigger（「歌單」單獨輸入也觸發列舉）+ topic-filter SQL（「歌單哪幾集」回 23 集精準而非全 164 集）+ tool-like 拆分（為 agentic RAG 預留）+ 前端階段式 10 集顯示。詳見 `docs/case-studies/r33-metadata-filter.md` Stage 8|
| **R2.1** ✅ shipped 2026-05-10 | citation infrastructure（v1.6） | R1 | 後端 sources 回應加 4 欄位（before/after_text、highlights、ai_summary_excerpt + ai_summary_full）；前端 `<SourceCard>` 加關鍵字 indigo 高亮（加粗+底線）+ before/after 灰色上下文 + AI 摘要 60 字「展開」+「跳到這段內容」button；URL deep-link `?show_id=&episode_id=&t=` shareable / bookmarkable / reload-safe；description-source 卡按鈕改「打開該集」；URL 邊界錯誤靜默回首頁；LLM prompt 加拒答模式 + `[N]` citation contract；citation parser strip 無效 ref。**Faithfulness gate 重訂為軟 gate（≥ 0.50）**因 RCA 證實退步根因是 retrieval 15% recall + judge 對中文拒答打折，跟 UI 無關。詳見 `docs/case-studies/r21-rca-deep-2026-05-10.md` |
| **R2.2** | prompt 重做（待 R3.x + R1.3 完成）| R3.x / R1.3 | 等 retrieval 改善 + judge re-bake-off 完，回頭把 Faithfulness 拉回 ≥ 0.71；同時做 inline `[N]` 渲染、hover ↔ source 互動、popover 完整化、mobile bottom sheet、無障礙 ARIA |
| **R4** | RAG 結果 cache | — | Redis hash key on 問題 + show + top_k + model。🆕 回應附 `cache_hit: bool` flag 給前端（dev 模式可顯示，學自競品 findtt.top） |

**故意排除（不放 R3）**：
- LlamaIndex / LangChain — 抽象封裝過厚、效能黑盒、新依賴。pgvector + tsvector + RRF 純 SQL 即可
- Whisper diarization speaker labels — 要重轉 360 集，影響 P2，暫緩
- ASR 錯字後處理 — 屬於 input quality 問題（T1 範疇），R3 是 retrieval 端問題，分開做

---

## Phase D — 內容生態

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **T2** | 轉錄人工回報機制 | — | UI flag bad transcript + admin 看 report。⚠️ **輕量版**：段落右側 icon 三選一（轉錯/敏感/其他），不開放使用者直接改字（避免新資料庫站那種開放校對的維運成本 + 惡意風險） |
| **T1** | 轉錄 LLM 潤飾（已完成集數重跑降錯字） | T2 | — |
| **C1** | 持久化對話紀錄 | — | DB 表 + API + UI |

---

## Phase E — 商業化 / 進階

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **U2** | 點數系統 + 計價 + 自動每月補回 | U1 | — |
| **C2** | 相關推薦機制（演算法 + UI） | C1 | — |
| **C3** | 內容權限分級（付費 tier 才看某些功能） | U2 | — |
| **A5** 🆕 | 整集對話入口（彩蛋級，源自競品分析） | R2 / R3 | TranscriptPage 浮動「問這集」按鈕，`/query` 多接 `episode_id` 限定向量檢索範圍 |
| **R5** | 向量化地端實作（self-host embedding，省 OpenAI 錢） | — | ⚠️ **規模大 + 資源限制**：要起 model service、Linode SIN 2vCPU/4GB 跑 BGE-small 可以但慢；可能要升級 VPS 或上 GPU。等真的有成本壓力再做 |

---

## Phase F — Ops / 體驗微調（隨時可插）

| 代號 | 項目 | 說明 |
|------|------|------|
| **O2** | Pre-built base image | build 從 10 分→30 秒 |
| ~~O3 → db-backup~~ ✅ | **archived 2026-05-07-db-backup（v1.3 milestone）** | 24h RPO / 30min RTO。每日 03:00 UTC pg_dump → age 加密 → Cloudflare R2 離站。月度 GHA 自動還原驗證。Manual smoke 全綠（restored 354/180826 = prod 354/180826，0% diff）。詳見 `docs/disaster-recovery.md` |
| **F1** 🆕 | `celery-routing-and-dispatcher-fix`（~17 tasks，**R3.2 archive 後最先做**）| 修 EP20 互卡 + stale-detect 失效兩個架構性問題。內含：(a) 4 條 queue（transcribe / topic / summary / control）+ Celery message priority + task_routes，單 worker 不浪費 RAM；(b) dispatcher 把 `set status=running` defer 到 worker task entry + worker 端 5 min idempotency check。EP20 case study 根因正解 |
| **F2** 🆕 | `task-failure-monitoring-and-circuit-breaker`（~25 tasks，依賴 F1 完）| 給所有背景任務加觀測層。內含：(a) 失敗率告警（30 min 窗口失敗 ≥3 次 → ZSend）；(b) 錯誤分類（暫時錯 retry / 永久錯 402/401/400 立刻 fail + 觸發斷路器）；(c) 斷路器（5 min 內同服務商連續 3 個永久錯 → 暫停所有用該服務商的 task）；(d) 自動每 30 min 探測恢復 + 手動按服務商 resume button。資料模型留 `task_type` 欄位方便未來細粒度恢復 |
| **A4** 🆕 | 明亮（淺色）主題（源自競品分析） | Shared.jsx TOKEN 拆 DARK/LIGHT + ThemeContext + localStorage。優先級低，等使用者反映再做 |

---

## 小修補（不開 Spectra change，下次順手做）

（2026-05-04 全部清完）
- ~~Empty-state 的 `POST /shows` 提示改導向後台~~ ✅ 已做（PodcastSelect 已 routing 到 admin-rag）
- ~~AdminPage ApiKeysTab 接後端~~ ✅ admin-llm-step-config 時已接好
- ~~STATS_VECTORS_COUNT 估算值改 live fetch~~ ✅ 加公開 `GET /stats` endpoint，ReleaseLogPage + PresentationPage 都改 live-fetch
- ~~既有 admin pytest 沒帶 auth fixture~~ ✅ 已隨 authentication-system 補齊（剩下 `test_admin_llm_step_migration.py` 不需要 — 它測 migration，不打 API）

---

## 進行中 changes（active，非 parked）

（2026-05-13 R3.2 milestone 全部 archive 收尾後清空 — 詳見下方「已 archive」段）

## Active + Parked changes（2026-05-31 snapshot）

**Active**（0 個）：
- （per-show-mode-example-prompts 已 2026-05-31 archive，無進行中 change）

**Parked**（0 個）：
- （voyage-rerank-tune-b22-b23 已 2026-06-04 archive，NEGATIVE）

**待 propose / 待 discuss**：見下方「衍生待 propose」段。

> 早期擱置的 `agentic-framework-bakeoff` / `chat-agentic-tool-routing` / `landing-and-mode-orchestration-redesign` / `rag-vs-longcontext-benchmark` 等：landing-redesign 已 2026-05-23 archive；其餘 agentic 路線仍在「衍生待 propose」追蹤，未進現役 parked queue。

## 衍生待 propose（未開 change 但有共識）

### EQ2b ASR 同音字 follow-up（2026-06-02，pilot/上線後衍生）
- **F1 可逆性 / 原始備份**：校正是 literal 取代、不可逆；`transcript.content` 非可靠原始來源（只是 EQ2a 沒回填 content 的巧合、新轉錄會覆蓋、且無 segment 時間軸對應）。要可還原須**明確存原始 segment 文字**（segment 加 `original_text` / 校正前快照），或讓「本集即時套用」也改成只套已核准。Jacky 接受目前風險（核准制把關），但列為待辦。
- **F2 EQ2a content-sync 缺口**：EQ2a 回填只改 segment/chunk，**沒同步 `transcript.content`**（逐字稿頁全文仍留錯字：杜忠祐 89、阿鳴 72、阿明 116）。獨立 bug。
- **F3 核准時可編輯 correct**：核准對話框讓人工微調正字（gemini 偶爾差一點）。
- **F4 jieba 詞典 × ASR 校正整合**：核准校正時自動把正字加進分詞詞典 → 搜尋斷詞更準。**與 Parking Lot「詞典系統整合 / 重設計」合併考慮**，先 /spectra-discuss。
- **F5 AI Hub 非 OpenAI 模型 JSON 相容**：qwen/deepseek/claude 在 `response_format=json_object` 回 0（fail-open）；加寬鬆解析（strip code block / 容錯）救回、擴大模型選擇。
- **F6 全面回填評估**：pilot 已過，原 Non-Goal 的全節目 LLM 偵測回填可評估開新 change。
- **F7 一般同音異義字修正（非專名）**：RAGEC 只認候選清單內的專名，抓不到一般常用詞同音（在來一碗→再來一碗、在/再、的/得）。要做須另設計通用文法/同音校正，**過度修正風險高**，先 /spectra-discuss 評估方法與風險，不塞進 EQ2b。
- **F8 回填可觀測/可取消**（2026-06-02 發現）：ASR 批次回填現在純背景 Celery，前端只彈 task_id toast、**無狀態/進度查詢、無取消（task revoke）、`failed_chunk_ids` 也沒 UI 讀**。**併進 EQ2e**（跑大 job 前先有控制）。


- ❌ **`retrieve-quality-step1-idf-and-prefilter`** done 2026-05-28 **FAILED, both layers reverted** (archive `2026-05-28-retrieve-quality-step1-idf-and-prefilter`)：Layer A (IDF-bucketed `ts_rank`) chunk_recall 0.482 → 0.382 ❌；Layer B (chat agent EP-ref dispatch prompt) chunk_recall 0.482 → 0.340 ❌。Root causes：(1) show-wide IDF 對 podcast transcript 不適用（entity token 在 show 維度罕見、在 answer-ep 內部極常見、IDF rare=signal 假設破滅）(2) prompt change 從來不 orthogonal 於 retrieval — 新 prompt 改 agent 措辭 `search_*(query: str)` 的 query → ts_rank 跟著飄 (3) show-wide DB probe 是 episode-scoped retrieval false positive validator。完整 RCA + 三條教訓 memory：`feedback_idf_show_wide_failed_2026_05_28.md` + `feedback_prompt_change_retrieval_side_effect.md` + `feedback_show_wide_probe_false_positive.md`。下動 pivot 評估框架升級（不再動 retrieval / prompt 直到有 span-level tracing + per-question tool trace）
- ✅ **`eval-framework-upgrade`** done 2026-05-30（archive `2026-05-30-eval-framework-upgrade`）— Langfuse Cloud Free + PG eval_traces 雙 sink + 6 個新 grader (4 DeepEval 內建 + 2 GEval 自寫) + `_calibration_8.json` + `retrieve_probe.py` + `prompt_fingerprint_diff.py` + PR template Retrieval/Prompt checklist + runbook + 全 34 baseline。**未達 4.4 acceptance**：prod 灰度 P95 +3375ms FAIL (<100ms gate)、tracing 預設 OFF、open follow-up `langfuse-self-host-evaluation`。完整 case study + RCA: `docs/case-studies/eval-framework-upgrade-2026-05-30.md`
- ❌ ~~**`langfuse-self-host-evaluation`**~~ — **CLOSED 2026-05-30** by `langfuse-sdk-overhead-rca`。Cloud SDK overhead 真實值 0.947 ms/span（30 span ~28ms）、與 Langfuse 官方 0.1ms 量級一致。4.4 P95 +3.4s attribution 錯誤、cross-session noise 造成的假象。完整 RCA: `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-30.md`
- ✅ **`eval-runner-eval-context-plumbing`** done 2026-05-31（archive `2026-05-31-eval-runner-eval-context-plumbing`）— bind_eval_context FastAPI dependency + runner X-Eval-* 三 header 注入 + run_id 落 result JSON + `sql_rca_demo.py` + `prompt_fingerprint_diff.py --source=sql` 路徑。Phase 5 prod 驗 34 span / 8 item / mt03 三輪 locator NOT NULL。hotfix `842d69d` 修 span_writer JSONB serialization（dormant bug）。完整 case study: `docs/case-studies/eval-runner-eval-context-plumbing-2026-05-31.md`
- ✅ **`lexical-bm25-replace-ts_rank`** / **EP-scoped IDF** 候選**解凍**（原暫不開）— eval framework 已 ship，可重新討論。下次提案 design 階段必須含 `retrieve_probe.py` 對 calibration_8 八題的事前 dry-run 才能進 apply
- ✅ **`b23-dataset-and-retrieval-rca-fix`** done 2026-05-27（commits `927fa18` + `f2bd784`）— b23 chunk_recall 0→0.5（dataset GT 修正主因）；episode_finders.find_episodes_by_topic 加 guest-index dispatch path（≥2 distinct guest names 觸發）+ envelope `prefilter_source` 觀測欄位；admin diagnose 擴 top_n=500 + chunking_context；揭露 b20 retrieve_hybrid 召回根本性 miss（@1790/@1808 連 top-500 都沒撈到）留 follow-up `chunk-level-retrieval-rca-b20-style`
- **`chunk-level-retrieval-rca-b20-style`**（衍自 b20 Phase 3 diagnostic）— retrieve_hybrid 對 EP134 @1790.18 / @1808.78 在 top-500 都沒撈到，疑似 chunking 邊界或 lexical 召回根本問題；先 query prod DB `transcript_chunks WHERE episode_id=c1d87278 AND start_time BETWEEN 1780 AND 1820` 看 chunks 存在性
- **`agent-pronoun-grounding`**（follow-up，未急）— b23 揭露 agent 拿到無關 chunk 後 LLM 自動把代詞「他/她/我」解析成 query 主體 → 表面 grounded 實際 hallucinate；需 SYSTEM_PROMPT 或 grounding rule 加「代詞解析驗證」。**unblocked**（judge 已可量代詞 hallucination）
- ✅ **`judge-pronoun-attribution-check`** done 2026-05-27（eval-only 不 redeploy）— judge 改餵 result_full + 加 pronoun_attribution_check 三態指標 + b23 為 Example 4；新 baseline `baseline-post-judge-v2-2026-05-27.json` chunk_recall_grouped 0.382→0.482、factual 0.831→0.892、refusal 0.971→1.000 全部提升；0 hallucinated case 反映 dataset + retrieval 前置 fix 真實效果
- **eval baseline 寫死**：cross_episode mean chunk_recall **0.283**（舊 0.244 deprecated，污染期 citation collector bug 數據）
- ✅ **`citation-display-unify`** — **已於 2026-05-18 ship**（隨 landing-and-mode-orchestration-redesign decision 5 + ConversationSourcePanel）：列舉題走 EnumerationSection 主從佈局、內容題走 ConversationSourcePanel 依集分組。此條先前誤列為待辦（drift），2026-05-31 更正。**後續迭代** → 見下方兩個 2026-05-31 propose 的 parked change。
- ✅ **`unified-segment-citation-card`** done 2026-05-31（archive `2026-05-31-unified-segment-citation-card`）— 三模式共用片段卡 + 播放/跳轉兩鈕 + 顯示數量與 top_k 解耦 + 列舉題展開片段卡。prod 三模式 smoke 全綠。
- ✅ **`per-show-mode-example-prompts`** done 2026-05-31（archive `2026-05-31-per-show-mode-example-prompts`）— 每節目×每模式 LLM 預產引導範例 + 冷啟動 chip fallback。prod 三節目 backfill 3/3/3、前端 placeholder+chip smoke 全綠。
- **eval golden set 擴張到 曼報 + 壹加壹電台** — 各 ~30+ 題人工 sentinel，等本節目 30+ 題到位再啟動
- **R3.x 候選未 propose**：topic seg 自動類別建議 / segment_categories admin UI / 業配段降權 multiplier / dict weight_in_lexical_query 通用化
- ✅ **`semantic-topk-bump-and-show-more`** done 2026-05-31（archive `2026-05-31-semantic-topk-bump-and-show-more`）— 語意過撈 k=25 + 初始 10 group + 顯示更多 +5。prod smoke「找到 25 個相關片段」、顯示更多不重打 API、排序不變。
- **R2.2 prompt redo** — Faithfulness 拉回（依賴 R3.x + R1.3）
- **R1.3 judge re-bake-off** — Phase B，等 R3.x 全跑完啟動
- **Golden set audit q25 expected 對齊** — 4 集多撈 / 6 集漏，人工複查（屬 dataset quality）
- **Rule pattern 涵蓋率月度回顧** — 等真實 prod query 累積後做
- **`eval-runner-dynamic-top-k`** — enumeration items top_k 動態提到 `len(expected)`
- ~~**`rag-py-module-split`**~~ ✅ 2026-06-09 archive。最終採獨立 change（非併進 chat-agentic）：facade re-export 拆成 6 子模組（types/config/sql/retrieval/enrich/generation），行為零改變。詳見上方序5

---

## 已 archive 變更（最近，依時間反序）

| Change(s) | Archive 路徑 | 摘要 |
|-----------|-------------|------|
| **2026-05-31** `semantic-topk-bump-and-show-more` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-semantic-topk-bump-and-show-more/` | 3/3 task done。語意搜尋過撈 k=25（前端 search 帶 k；endpoint 已支援 1–50；後端零改動）+ `SemanticResultList` 顯示上限：初始 10 group + 「顯示更多」每次 client-side +5（不重打 API，因 endpoint 無 offset）、全露完按鈕消失。k 壓在 25 因 `enrich_hits` 是 O(k) 循序 SQL（延遲線性，無 per-hit LLM 故 $ 不變）。純前端、不動排序（Recall@K 不受影響）。spec `semantic-mode-result-ui` +1 requirement（4 scenarios）。本機 render 測試 + prod smoke 全綠：request body k=25、「找到 25 個相關片段」、初始 10 group、顯示更多 +5 不重打 API（/search 請求數仍=1）、前 5 名排序不變。commit `d3aa949`。 |
| **2026-05-31** `per-show-mode-example-prompts` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-per-show-mode-example-prompts/` | 9/9 task done。每節目×每模式 LLM 預產引導範例（冷啟動 trending<3 fallback）。後端：`show_example_prompts` 表（migration `d8e9f0a1b2c3`）+ `services/example_prompts.py`（gather_materials + generate_for_show，沿用 summary step、fail-open、idempotent delete-then-insert、**per-mode 題目長度上限** index30/semantic70/chat120）+ 公開 GET `/shows/{id}/example-prompts` + admin backfill（單一 inline / 全 show enqueue）+ `workers/example_prompts_task.py` 鏈式（summary 批次全完成 enqueue 一次）。前端：i18n 三 per-mode placeholder + `TrendingQueriesChips` 加 mode prop（trending≥3 熱搜 / <3 fallback「範例」chip）+ QueryPage 三 tab 接線。本機 9 pytest 全綠 + migration 升降可逆。**Prod 驗證**：三節目（這又沒有很屌/曼報/壹加壹電台）trending 皆 0 全冷啟動，backfill 後各 3/3/3；前端三模式 placeholder + 範例 chip + 點擊執行全綠。順手抓到並修：全域 60 字上限把 chat 長題全濾掉（壹加壹電台 chat 0→3，commit `ed56f1b`）。生成內容抓到 ASR 錯字「寰宇龍虎報→豹」（非本 change bug，入 ASR backlog）。commits `71f2e44` + `ed56f1b`。 |
| **2026-05-31** `unified-segment-citation-card` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-unified-segment-citation-card/` | 11/11 task done。三模式（索引/語意/對話）引用呈現收斂到單一共用葉子 `src/SegmentCitationCard.jsx`：片段文字 + 雙模式高亮（多詞兩色橘實線/青虛線 ← `highlightTerms` 移入本檔成 canonical、KeywordResults 不再重複宣告 / server `highlights` 單色 indigo via `.scc-server-hl` scoped CSS）+ 集標題 + 時間戳 +「播放此段」/「跳到逐字稿」兩顆獨立鈕（取代舊 `onSourceJump` 播放+導航綁一起）。`SourceCard` 改 thin wrapper 轉呼叫；`SemanticResultList`（relevance bar 移進卡內 `relevance` prop）/`ConversationSourcePanel`（每組 cap 5 + 顯示更多、與 top_k 解耦）/`KeywordResults`（T1/T2/T3 leaf）全換共用卡；`EnumerationSection` 集卡加「展開查看各段」inline 片段卡（不離頁）。`LANGUAGE.md` 補引用片段卡 + citation/source/segment 三層語意。Spec：segment-citation-card 新增 + conversation-source-panel/semantic-mode-result-ui 修改進 canonical（added 5/modified 3）。本機整合（9 元件 global、無 collision/JS error）+ prod 三模式 smoke 全綠（索引 T2 展開 25 卡兩色、語意 8 卡 relevance bar 100/87/74、對話 5 集分組 description「打開該集」vs transcript「播放+跳轉」、列舉「歌單哪幾集」展開 8 inline 卡）。commit `50388d9`。 |
| **2026-05-31** `keyword-index-mode` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-keyword-index-mode/` | 26/26 task done。第三模式「索引」：`POST /shows/{id}/keyword-search` 嚴格 AND 多關鍵字三段式（T1 同 chunk AND / T2 跨三池 episode AND / T3 OR fallback 僅 T1+T2=0）+ 100 cap + 5s timeout；`app_settings.keyword_t2_collapse_threshold`（migration `c7d8e9f0a1b2`）；`KeywordResults.jsx` sectioned 結果頁（兩色高亮、T2 inline 展開查看各段、collapse chip、分頁、empty state、mode switcher）；QueryPage 索引 tab 接線。本機 20 unit+integration 測試（真實 Postgres）全綠；prod smoke「歌單/馬世芳 歌單/馬世芳 滅火器/空查詢」四 scenario + 422 錯誤 UI 驗證。Bonus 修正 `/events` SearchExecutedPayload.mode 接受 `index`（commit `35e6850`+`d851f15`）。同 session discuss 收斂引用呈現 → propose 兩 parked change。 |
| **2026-05-31** `eval-runner-eval-context-plumbing` ✅ done | `openspec/changes/archive/2026-05-31-eval-runner-eval-context-plumbing/` | 11/11 task done。Runner v2 startup 生 run_id (`eval-YYYYMMDDTHHMMSSZ-<8hex>`) + 每 turn 注入 `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx`；backend `bind_eval_context` FastAPI dependency 在 admin + 三 header 齊 + turn_idx int>=0 → `set_eval_context()`、reset on request end；非 admin / 缺 header / malformed silent skip（不 4xx）。新增 `sql_rca_demo.py`（3 段：per-turn span count / cross-run query diff / per-turn tool timeline）+ `prompt_fingerprint_diff.py --source=sql` 路徑。Phase 5 prod 驗：run `eval-20260530T181920Z-465dd6d2` → 34 span / 8 distinct items / mt03 turn_idx 0,1,2 全 NOT NULL；admin caller 無 X-Eval-* header → eval_traces baseline 不增。**Hotfix 同 change `842d69d`**：span_writer JSONB serialization（asyncpg DataError dormant bug，首次真正 exercise PG sink 才暴露；三欄 `json.dumps + CAST AS JSONB`）。同 session 抓到 prod `EVAL_TRACING_ENABLED=false`（記憶寫 ON 不符）、toggle + redeploy 後生效。完整 case study: `docs/case-studies/eval-runner-eval-context-plumbing-2026-05-31.md` |
| **2026-05-30** `langfuse-sdk-overhead-rca` ✅ spike done | `openspec/changes/archive/2026-05-30-langfuse-sdk-overhead-rca/` | Investigation-only spike。加 per-op timing probe (`EVAL_TRACING_TIMING_PROBE` env)、prod 量測證實 Langfuse Cloud SDK overhead 平均 0.947 ms/span、P95 1.689 ms/span、30 span ~28ms — 4.4 P95 +3.4s attribution 給 SDK 是錯的、是 cross-session noise。Forward decision: CLOSE `langfuse-self-host-evaluation` follow-up。完整 RCA: `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-30.md` |
| **2026-05-30** `eval-framework-upgrade` ✅ PARTIAL ship | `openspec/changes/archive/2026-05-30-eval-framework-upgrade/` | 33/33 task done。Langfuse Cloud Free + PG eval_traces 雙 sink、6 個新 grader (4 DeepEval 內建 + 2 GEval 自寫)、`_calibration_8.json` 8 題 byte-equivalent subset、`retrieve_probe.py` + `prompt_fingerprint_diff.py` 兩 CLI、PR template Retrieval/Prompt checklist、runbook、全 34 baseline。**未達 4.4 acceptance**：prod 灰度 P95 +3375ms FAIL (<100ms gate)、tracing 預設 OFF、open follow-up `langfuse-self-host-evaluation`。4.1 chunk_recall_grouped -0.10 RCA 確認非 regression（agent 落相鄰 chunk、answer 品質完全沒變、`contextual_precision=0.92` 證 retrieval 健康）— 驗證 task 2.3b ContextualRecall grader 加入正當性。完整 case study: `docs/case-studies/eval-framework-upgrade-2026-05-30.md` |
| **2026-05-28** `retrieve-quality-step1-idf-and-prefilter` ❌ FAILED | `openspec/changes/archive/2026-05-28-retrieve-quality-step1-idf-and-prefilter/` | 兩 Layer 全 revert。Layer A IDF-bucketed `ts_rank` chunk_recall 0.482 → 0.382；Layer B chat agent EP-ref dispatch chunk_recall 0.482 → 0.340。Prod 留 orphan `transcript_token_freq` table + alembic migration（無程式引用）。下動 pivot 評估框架升級。完整 RCA: `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md` |
| **2026-05-18 batch (3 個)** `backfill-progress-admin-tab` + `whisper-chunking-fix` + `multi-provider-usage-monitoring` | `openspec/changes/archive/2026-05-18-*` | Admin Queue Tab 進度概覽；Whisper 80min 集 multipart 25MiB chunk fix；3 provider 用量監控 + 預算告警（aihub adapter URL 猜錯 follow-up 開 `aihub-graphql-adapter-migration`）。Release log v1.7 |
| **2026-05-17 batch (2 個)** `enumeration-rule-pattern-broaden` + `enumeration-topic-finder-include-title` | `openspec/changes/archive/2026-05-17-*` | Rule pattern 加反序「集數有哪些」+ find_episodes_by_topic 對 LLM phrase 先 jieba 切（CJK simple analyzer bug）；q26 0.333→1.0、aggregate 0.5467→**0.88** |
| **2026-05-16 batch (4 個)** `r3-3-metadata-filter` + `r3-3-chat-enum-grounding` + `chat-input-ime-composition-fix` + `eval-runner-chat-enum-scoring` | `openspec/changes/archive/2026-05-16-*` | R3.3 milestone (v1.7)：guests JSONB + admin tab + title_tsvector + 三池 RRF + LLM entity_extraction + ChatResponse enumeration_episodes + frontend EnumerationSection；chat 答案 grounding + topic-trigger + topic-filter SQL；IME enter 送出 bug；eval runner 對 chat enum 計分。Prod Recall@5 0.86 (n=28)，q25 0.04→0.76、aggregate 0.1867→0.5467。詳見 `docs/case-studies/r33-metadata-filter.md` |
| **R3.5** `r3-5-disable-routing` + R3.4 + R3.2 milestone (6 個) | `openspec/changes/archive/2026-05-13-*` | **v1.7 milestone**：關掉 two-layer routing + 6 個 R3.x changes pair archive。Recall@5 (human-curated) 0.0625 → **0.4375 (7x)**、P95 2170ms |
| `r2-1-citation-infra` + `r2-1-followup-bugs` + `r2-1-prompt-fix` | `openspec/changes/archive/2026-05-10-r2-1-*` | citation infrastructure（v1.6）：search 結果加 highlights / before/after_text / ai_summary 60 字 + 「展開」+「跳到這段內容」button + URL deep-link shareable + LLM prompt 加拒答模式 + citation parser strip [N]。**Faithfulness gate 重訂為軟 gate（≥ 0.50）** |
| `db-backup` | `openspec/changes/archive/2026-05-07-db-backup/` | 每日 03:00 UTC pg_dump → age → R2 離站；月度 GHA 還原驗證；7d/4w/12m retention。月成本 ~$1 |
| `freemium-onboarding` | `openspec/changes/archive/2026-05-04-freemium-onboarding/` | LandingPage + 公開段落搜尋（IP rate limit 20/day）+ 登入解鎖 LLM 答案 + quota 申請流程 |

完整列表（含更早）見 `openspec/changes/archive/` 目錄。

---

## 維護規則

- 本文件與 Claude 的記憶檔案 `project_pending_changes.md` **互為鏡像**，更新時請同步維護兩邊（feedback_roadmap_dual_write）
- 路徑變更 / 新增 / archive 時兩處都要動
- 詳細工作紀錄類文件（case studies / research）放 `docs/case-studies/` + `docs/research/`，**不進 commit**（feedback_case_studies_no_commit）

## 工作紀律（不在路線圖內，但執行時受其約束）

- **成本紀律**：pilot < $20 免問；> $30 大規模回填要 confirm；AI Hub 可程式查餘額（Balance/100k=USD），OpenAI 走 α 方案手動回報（baseline 記在 memory `reference_openai_balance.md`）
- **單節目 pilot 策略**：所有「全 corpus 重做」類動作（re-chunking / re-embed / 換 embedding model）必須先在單一節目（「這又沒有很屌」）pilot 驗證，再 rollout 其他兩個節目
