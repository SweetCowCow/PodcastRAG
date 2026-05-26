## 1. 修正 SQL regex 寫法

- [x] 1.1 在 `backend/app/services/episode_finders.py` 把 `_BY_REF_EP_NUMBER_SQL` 內的 `(?:EP|第)` 改寫為 `(EP|第)`、`(?:集)?` 改寫為 `(集)?`。驗證：手動跑 `python -c "from backend.app.services.episode_finders import _BY_REF_EP_NUMBER_SQL; assert '(?:' not in _BY_REF_EP_NUMBER_SQL"` 不 raise

## 2. 加 unit test 鎖 SQL 行為

- [x] 2.1 新增 `backend/tests/services/test_episode_finders_by_ref.py`，含 4 個 test case：(a) `find_by_ref(ref="EP143")` 對含 `EP143` 標題的 fixture episode 回傳 `EpisodeRef`，episode_id 正確；(b) `find_by_ref(ref="第19集")` 對含 `EP19` 標題的 fixture 回傳同一筆；(c) `find_by_ref(ref="EP999")` 對不存在的 EP 編號 + 無 title 部分匹配時回傳 `None`；(d) 純 string assert：`_BY_REF_EP_NUMBER_SQL` 不含 `(?:` 子字串。驗證：`pytest backend/tests/services/test_episode_finders_by_ref.py -v` 4 個 case 全 pass

## 3. Prod smoke

- [x] 3.1 把 fix commit 推 main、等 Zeabur build + RUNNING（用 `zeabur deployment list --service-id <api-svc>` polling）。Build 卡 10 分鐘以上要走 redeploy SOP 排除 webhook 不穩。驗證：build status = SUCCESS、service status = RUNNING、`curl https://podcastrag-api.zeabur.app/health` 回 200
- [x] 3.2 對 prod 跑 4 個 EP-reference smoke query（EP1 / EP19 / EP143 / EP134），每題打 `POST /shows/45fc2462-17cf-42f5-98a7-68fe1a222228/query?debug_trace=true` mode=chat、檢查 response `tool_calls[0]` 含 `find_episode_by_ref` 且 `result_summary` 的 `ok=true`、`raised` 不存在。驗證：4/4 全 pass，無 `StatementError` 字眼
