## Why

2026-05-10 一整天 user 跟 Claude 反覆問「topic backfill 跑到哪了」、「為什麼 segments 沒漲」、「轉錄還剩幾集」 — 全部要手動 SQL query 進 prod DB 才查得到。Admin Queue Tab 現有「轉錄佇列」表只看到 individual queue rows，沒有跨集數的進度概覽。User 沒辦法自己 monitor，必須叫 Claude 才知道狀況。Backfill 進度涉及三個維度（轉錄完成 / 摘要完成 / topic 分類完成），需要一頁集中視覺化。

## What Changes

- 在 admin Queue Tab 上方加新區塊「進度概覽」（不是新 page，inline 在 Queue Tab top）
- 顯示 3 個進度條：轉錄完成（X / 總集數，% bar）、摘要完成、topic 分類完成
- 數字基於 segment-level（不是 distinct episode）— 解決 5/10 「distinct episode 不準」事故
- 顯示「最近 24 hr 處理量」：轉錄 +N 集 / 分類 +N 集 / 失敗 N 件（來自 Celery result backend，未來 F2 archive 後改 task_failure_log）
- 自動 30 s polling 刷新
- 新增 backend endpoint `GET /admin/processing-stats` 回 JSON
- v1 「最近失敗」展開 list 用 Celery result backend 撈（限 24 hr 內的 FAILURE meta，過濾 transcribe / topic / summary），F2 archive 後可平滑切換到 task_failure_log（兩種 source 同 schema 包裝）

## Non-Goals

- 不做歷史趨勢圖（每日進度 line chart）— 屬 v2 polish
- 不做 per-show breakdown（哪個節目跑到哪）— 屬 v2 polish
- 不做使用者端的 progress 顯示（PodcastSelect / QueryPage）— admin only
- 不做 manual backfill enqueue button（屬 F1 / F2 範疇 — F2 有 admin resume button 形式）
- 不做 cost-per-batch 顯示（屬 multi-provider-usage-monitoring 範疇）
- 不引入新 chart library — 用純 div + width % 的 progress bar 即可
- 不暴露非 admin 的 API（admin role gate）

## Capabilities

### New Capabilities

- `processing-progress-overview`: admin 端 backfill 三維度進度概覽 + 24 hr 處理摘要

### Modified Capabilities

（無）

## Impact

- Affected specs: `processing-progress-overview`
- Affected code:
  - New:
    - `backend/app/api/admin_processing_stats.py`（GET /admin/processing-stats endpoint）
    - `backend/tests/test_admin_processing_stats_api.py`
    - `src/QueueTab.jsx` 內新 `<ProcessingOverview>` 子元件
  - Modified:
    - `src/QueueTab.jsx`（在表上方插入 ProcessingOverview）
    - `backend/app/main.py`（註冊 admin_processing_stats router）
