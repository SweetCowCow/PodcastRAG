## 1. 程式修改

- [x] 1.1 在 `backend/app/services/rss_parser.py` 把 `fetch_and_parse(url: str, max_episodes: int = 200)` 改為 `fetch_and_parse(url: str, max_episodes: int | None = None)`；line 58 改為 `episodes_iter = parsed.entries if max_episodes is None else parsed.entries[:max_episodes]`，後續 list comprehension 改用 `episodes_iter` — 對應「Create show endpoint」requirement 與「Feed with more than 200 episodes is persisted in full」scenario

## 2. 部署與 Prod 驗證

- [x] 2.1 commit + push 觸發 Zeabur backend service 重新 build & deploy；用 `zeabur-deployment-logs` 確認 backend service 狀態 RUNNING、`GET /` healthcheck 回 200，且新版 code 已上線（可用 `curl https://podcastrag-api.zeabur.app/openapi.json` 確認服務可達）
- [x] 2.2 在 https://podcastrag.zeabur.app 後台對「壹加壹電台」按「⋯ → 更新節目集數」一次；驗證 alert 顯示 `added=51, updated=0, total=251`（既有 200 不變，補入 51 新集）
- [x] 2.3 對 `< 200 集` 的節目（這又沒有很屌、曼報）按「⋯ → 更新節目集數」各一次；驗證 alert 顯示 `added=0`（無新集）、total 維持原數字（161 / 139）— 對應「Feed with more than 200 episodes is persisted in full」scenario 的反向驗證（正常 < 200 集 feed 行為不變）

