---
name: golden-set-builder
description: "Build a show's golden set via the dynamic pipeline: show profiling → anchor-first generation → pre-review grading → conversational human review → promote to main dataset → reject-feedback report. Use when adding/extending a show's eval golden set."
license: MIT
metadata:
  version: "1.0"
---

Golden set 動態流水線（eval-loop-automation，2026-07）。取代「全自動 LLM 產題」（壞題率 ≥75%，2026-05-13 audit）與「全手工共草」（30 題一個 session）兩條死路。

## When to invoke

- User 要幫某節目建立或擴充 golden set（「幫壹加壹出題」「補曼報的量尺」）
- User 要重跑一輪產題（回饋圈第二輪補題）
- User 要人工共草 multi-turn 題

## 流水線總覽

```
0. show_profile.py     → profiles/{slug}.json（quota 矩陣，可手改）
1. build_golden_set.py → _pending_review.json（anchor-first 產題 + 預審分級）
2. 對話式人審           → 逐題 verdict 記入 _review_log.jsonl
3. promote_reviewed.py → 核准題寫入 datasets/{slug}.json（三參數防呆）
4. 回饋圈報告           → 壞題率 vs 上輪；不足 30 題 → 回饋圈生效後跑第二輪
```

所有腳本從 repo root 跑，需要：
- `DATABASE_URL`：prod **read-only** 帳號即可（產題只讀）
- `OPENAI_API_KEY`：AI Hub key（backend/.env 有，用 `export $(grep -h '^OPENAI_API_KEY=' backend/.env)` 載入，**不准 cat .env**）
- `/search` retrieval 訊號要 `--backend-url https://podcastrag-api.zeabur.app`；不通時 `--skip-retrieval-signal`（代價：全部落重審級）

## Step 0 — Show profiling

```bash
python -m backend.eval.scripts.show_profile \
  --show-id <uuid> --show-slug <slug>
```

產出 `backend/eval/datasets/profiles/{slug}.json`。quota 規則是靜態 if 表（寫在腳本註解）：來賓覆蓋率 <10% → `guest_find=0` 回填 fact/cross_episode；summary done 率 <50% → `summary_overview=0`；無歌單集 → `playlist_enum=0`。**產題前把 profile 給 user 過目確認 quota 合理** — 檔案可手改，改完直接餵下一步。

### Step 0b — 節目基本資訊確認（show_facts，2026-07-03 加入）

產題前**上網（WebSearch）查證節目基本資訊**並跟 user 確認，寫進 profile 的 `show_facts` 欄位：

```json
"show_facts": {
  "hosts": [{"name": "...", "aliases": ["..."], "real_name": "...", "note": "..."}],
  "notes": "<ASR 高風險名詞備註>",
  "confirmed_by": "<user>", "confirmed_at": "<date>"
}
```

- 查：主持人名字與暱稱、加入時間、常見贊助商/廠商名稱
- 產題 prompt 會引用 hosts 讓題目用自然稱呼（不寫「主持人/講者」）；**無法從片段判斷是誰說的一律用「他們/他/她」，不要瞎猜指名**
- 贊助商/廠商名稱是 ASR 轉錯重災區（例：壹加壹的「心肌尼」）— 出題避免依賴這類名稱，人審遇到 reject `asr_typo_dependent`

## Step 1 — anchor-first 產題 + 預審

```bash
python -m backend.eval.scripts.build_golden_set \
  --profile backend/eval/datasets/profiles/{slug}.json \
  --round <N> \
  --backend-url https://podcastrag-api.zeabur.app
```

- 錨先於題：先抽 episode（長度×時間分層）→ 抽 chunk → LLM 從 chunk 產題 → 錨定該 chunk。
- 產題模型 gpt-5.1、預審判官 gemini-2.5-flash-lite — **兩者必須不同**（腳本會擋）。
- 每題附 `pre_review`：anchor 對齊、answerability rubric（must_ok）、show_id 防呆（唯一自動 reject，直接記 log）、retrieval rank（**只分級不否決** — 檢索不到的難題正是量尺價值）。
- `review_grade: light | heavy`；negative 題一律 heavy（「真的沒講過」只有人能查證）。
- 回饋圈：腳本自動讀 `_review_log.jsonl` 把歷史 reject 實例注入 prompt；`--dry-run-prompt` 可印出最終 prompt 驗證注入。

## Step 2 — 對話式人審（所有題都過人審，深淺有別）

staging 檔每題帶 `anchor_context`（錨 chunk 原文），審核不用查 DB。

**輕審級**（batch 呈現，一行一題，user 快速 y/n）：

```
| # | id | 題型 | 題目 | rank | 裁決? |
```

**重審級**（逐題呈現，完整脈絡）：

```
【題目】…
【預期答案】…
【錨 chunk 原文】（集數標題 + 全文）
【判官 note】…（anchor_aligned / must_ok 有 fail 要標紅）
【retrieval rank】N 或 miss
→ 裁決：approve / approve_edited（改完再核）/ reject（附理由）
```

- `approve_edited`：直接把 staging 檔裡該題改好（question / expected_answer_summary / GT 分層），再記 verdict — promote 會取 staging 檔當下內容。
- 每個 verdict 立刻用 CLI 記入（enum 驗證內建），**不要累積到最後補記**：

```bash
python -m backend.eval.scripts.review_log \
  --show-slug <slug> --item-id <id> --verdict reject \
  --reason too_shallow --note "單句可矇中" \
  --question "<題目原文>" --round <N>
```

- reject 理由必須從枚舉挑（見下表），自由文字放 `note`；reject 時 `--question` 必填（回饋圈素材）。

### Review log 行格式（append-only JSONL）

```json
{"ts": "<ISO8601>", "show_slug": "...", "item_id": "...", "verdict": "approve|approve_edited|reject", "reason": "<枚舉>", "note": "...", "question": "<題目原文>", "round": N}
```

`question` 欄位是回饋圈的 negative few-shot 素材，reject 時**必填**。

### Reject reason 枚舉

| reason | 意思 |
|--------|------|
| `anchor_mismatch` | 錨與題意不對齊（只共享關鍵字） |
| `too_shallow` | 題太淺、單句可矇中 |
| `keyword_triggered` | 單關鍵字就能觸發正解 |
| `cross_ep_irrelevant` | 跨集錨其實無關聯 |
| `ambiguous` | 語意含糊、答案沒有清楚立場 |
| `asr_typo_dependent` | 題目依賴 ASR 錯字才成立 |
| `other` | 其他（note 必填） |
| `show_id_guard` | （機器保留）錨屬於別的 show，腳本自動 reject |

## Step 3 — 晉升核准題到 main dataset

```bash
python -m backend.eval.scripts.promote_reviewed \
  --staging backend/eval/datasets/_pending_review.json \
  --show-slug <slug> --round <N> \
  --target-main --reviewed-by <id> --reviewed-at <ISO8601>
```

- 只搬 verdict = approve / approve_edited 的題；staging 裡有題沒 verdict 會直接報錯（審核必須覆蓋每一題）。
- 寫入時去掉 `anchor_context`，附上溯源欄位：`reviewed_by` / `reviewed_at` / `review_round`、`audit_status: "approved"`。
- 三參數防呆與 build_golden_set 相同：缺任一參數 exit 2。
- 已存在的 main dataset 會合併（append 新題，不動舊題）。

## Step 4 — 回饋圈報告與第二輪

- 產題腳本每輪結束自動印各輪壞題率（reject 率）與理由分布。
- **驗收 gate：首輪壞題率 <40%**（歷史基線 75%）。
- 核准不足 30 題 → 跑第二輪：`--round N+1`，回饋圈自動把首輪 reject 實例當反面教材注入；先 `--dry-run-prompt` 驗證注入內容再正式跑。

## Multi-turn handcraft 共草引導

`multi_turn_handcraft` quota 不自動產。共草紀律（2026-06 拍板）：**一題一題引導、不可 batch**——

1. 先講這題的 type、考驗什麼能力、判斷標準
2. Claude propose 錨 chunk（附原文）等 user 確認
3. 確認後才共草題目與 turns（v2 schema `is_multi_turn: true` + `turns` 陣列，可參考 extended-multi-turn-40.json 的 multi-turn item）
4. 完成的題直接進 main dataset（帶 reviewed 溯源欄位），review log 記 verdict=approve、note=handcraft

## 未來接入點（本 change 未實作）

- **prod query 回收軌**：真實用戶 query 可從 `events` 表 `event_type='search_executed'` 回收作候選題源；回收時必須過濾 eval 流量（`X-Eval-Run-Id` header 打進來的請求）並去重。量夠了再開 change。
- **recurring_segments**：profile 的掛鉤欄位，等固定環節結構化抽取（台通推歌／塞掐片尾題）獨立 change。

## 踩坑備忘

- 本機跑 pytest 驗證腳本改動要加 `-p no:deepeval`（plugin 會 load .env 蓋 DATABASE_URL）
- 集數編號跨 show 會碰撞 — 挖 transcript 一律 filter show_id（show_id 防呆就是為此存在）
- dataset 檔案驗證：`backend/tests/test_golden_set_dataset.py` 會掃 datasets/*.json
