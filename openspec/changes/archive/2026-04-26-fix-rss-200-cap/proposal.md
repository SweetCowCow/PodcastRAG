## Problem

`backend/app/services/rss_parser.py` 的 `fetch_and_parse(url, max_episodes=200)` 寫死預設值 200，並在 line 58 用 `parsed.entries[:max_episodes]` 截斷。所有呼叫者（`backend/app/services/sync.py:22` 與 `backend/app/api/shows.py:74`）都使用預設值，導致**任何 podcast 節目最多只能抓到 200 集**。

實際 prod 案例：Firstory 上的「壹加壹電台」 RSS feed 真實有 **251 集**，DB 卻只有 200 集，少 51 集。

## Root Cause

寫死的 `max_episodes=200` 在 `parsed.entries[:200]` 切片時丟掉超過的 entries。feedparser 已在記憶體中解析完整 feed，是我們應用層自己丟掉的。並非 RSS host 端限制：已驗證 Firstory 與 SoundOn 兩家 host 都會在單一 XML 中回傳完整集數歷史（壹加壹 251 集 / 這又沒有很屌 161 集 / 曼報 139 集，後兩者 < 200 所以未被影響）。

## Proposed Solution

把 `fetch_and_parse` 的 `max_episodes` 預設值改為 `None`，並在 `None` 時不對 `parsed.entries` 切片（取全部）。保留 `max_episodes` 為 `int` 時仍切片的行為，方便未來測試或特殊呼叫者使用。

呼叫端不需修改：`sync_show_episodes` 與 POST /shows 都使用預設值，預設變了 → 自動拿到完整 feed。

修復部署後，使用者用「⋯ → 更新節目集數」對既有節目觸發重抓，缺的集數會自動 upsert 進 DB。

## Non-Goals

- **不實作 RSS Atom paginate**（`<atom:link rel="next">` 跟蹤）— 主流 podcast host 都單一 XML 回完整歷史，YAGNI。少數要分頁的 feed 等真踩到再開新 change。
- **不引入 host-specific API**（Apple Podcasts API / Spotify API）— 只解 RSS 截斷問題，不擴大範圍到其他資料源。
- **不調整 `transcribe-latest` 的 `max_episodes` 概念**——那是「轉錄上限」與本 change 無關。
- **不調整 `httpx.AsyncClient(timeout=30.0)`**——目前壹加壹 251 集 / 929KB 在 30s 內 OK；超大 feed（10MB+）的 timeout 留給未來真踩到再說。
- **不新增前端 UI 通知「集數變多了」**——使用者按「更新節目集數」會看到 alert 顯示 added/updated 數字，已足夠。

## Success Criteria

1. `fetch_and_parse(url)`（無 `max_episodes` 參數）對 251 集的 Firstory feed 回傳所有 251 個 ParsedEpisode。
2. `fetch_and_parse(url, max_episodes=10)` 仍回傳前 10 個 entries（向後相容）。
3. 部署後對 prod 上「壹加壹電台」按「更新節目集數」一次，DB `episodes` 表中該 show 的 row 數從 200 → 251（+51）。
4. 對其他 < 200 集的節目（這又沒有很屌 161 / 曼報 139）按「更新節目集數」結果不變（added=0、updated=任意）。

## Impact

- Affected specs: `rss-feed`（MODIFIED「Create show endpoint」requirement，移除「up to 200」字眼並新增 scenario 確認 > 200 集 feed 全部 persist）
- Affected code:
  - Modified:
    - backend/app/services/rss_parser.py（`max_episodes: int | None = None`，None 時不切片）
  - New: （無）
  - Removed: （無）
- 無 DB migration、無前端變動、無 dependency 變動
- Runtime 影響：對 > 200 集的 feed，sync_show_episodes 會多執行 N - 200 次 in-memory dict lookup + insert，O(N) 線性，對 1000 集等級無壓力
