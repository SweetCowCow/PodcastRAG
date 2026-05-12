# Tasks — provider-key-resolver

## 1. Module 實作 — design D1 + D2 + D3

- [ ] 1.1 建立 `backend/app/services/key_resolver.py`，含 module docstring 說明 "for offline / standalone scripts ONLY, in-request paths use step_config.api_key"
- [ ] 1.2 實作 sync engine singleton：從 `app.core.config.settings.database_url` 衍生 sync URL（`postgresql+asyncpg://` → `postgresql+psycopg://` 或 plain `postgresql://`），module-level lazy init
- [ ] 1.3 實作 `_CACHE: dict[tuple[str, Optional[str]], str]` module-level dict，DB hit 才存（env hit 不存，per D2）
- [ ] 1.4 實作 `get_provider_key(provider, prefer_env=None)`：先 env → cache → DB `SELECT api_key FROM api_keys WHERE provider=:p ORDER BY created_at DESC LIMIT 1` → KeyError
- [ ] 1.5 確認函式內**完全沒有** `print` / `logging.*` 對 key 值的引用（grep self-audit）
- [ ] 1.6 KeyError message 嚴格遵守 `f"No API key found for provider={provider!r}"` 格式（測試會 match）

## 2. 單元測試 — design D7

- [ ] 2.1 建立 `backend/tests/test_key_resolver.py`，重用既有 conftest 的 DB fixture（async session + 同 transaction rollback）；若既有 fixture 是 async-only，加 sync fixture wrapper
- [ ] 2.2 `test_prefer_env_set_returns_env_value`：monkeypatch `OPENAI_OFFICIAL_KEY=sk-test-env`、call `get_provider_key('openai', prefer_env='OPENAI_OFFICIAL_KEY')` → assert == `'sk-test-env'`；用 mock 確認 DB 不被 query
- [ ] 2.3 `test_prefer_env_empty_falls_back_to_db`：env 設空字串、DB 插一筆 `provider='openai' api_key='sk-test-db'` → call → assert == `'sk-test-db'`
- [ ] 2.4 `test_db_multiple_rows_returns_latest`：DB 插兩筆同 provider、created_at 差 1 秒 → call → assert 回較新那筆
- [ ] 2.5 `test_db_miss_raises_key_error`：DB 沒對應 provider → `pytest.raises(KeyError, match=r"provider='nonexistent'")`
- [ ] 2.6 `test_no_key_logged`：`caplog.set_level(logging.DEBUG)`、跑 success + miss 兩條 path → assert `'sk-test-env'`、`'sk-test-db'`、`'sk-'` 字串都不出現在 `[r.message for r in caplog.records]`
- [ ] 2.7 `test_cache_hit_skips_db`：同 (provider, prefer_env) 連續 call 兩次 → 第二次 DB query 計數應 == 第一次（mock counter 不增）
- [ ] 2.8 `pytest backend/tests/test_key_resolver.py -v` 全綠

## 3. 範例 caller migration（**apply 階段才動，本 change propose 不動**）— design D6

- [ ] 3.1 修改 `backend/eval/scripts/embedding_bakeoff.py` 第 455-466 行 fallback chain，改用 `from app.services.key_resolver import get_provider_key; api_key = get_provider_key('openai', prefer_env='OPENAI_OFFICIAL_KEY')`
- [ ] 3.2 移除原本「讀 backend/.env 找 OPENAI_API_KEY=」的 fallback（DB 已是 single source of truth）
- [ ] 3.3 dry-run `python3 -m eval.scripts.embedding_bakeoff --help` 在 backend/ 下能正常 import、印 help 文字（不執行 API 呼叫，不花錢）
- [ ] 3.4 註解 / docstring 更新：說明此 script 現在從 DB `api_keys WHERE provider='openai'` 拿 key，可選 `OPENAI_OFFICIAL_KEY` env 覆蓋

## 4. 文件 + 後續清理 backlog — design D6

- [ ] 4.1 在 design.md D6 表格基礎上，於 apply 階段檢查 grep 結果是否還有遺漏 caller（`grep -rln "OPENAI_API_KEY\|os.environ\[.OPENAI" backend/`），若有新檔補進清單
- [ ] 4.2 每個遺留 caller 開 follow-up issue / backlog 條目（**不在本 change 修**）：`judge_bakeoff.py`、`build_golden_set.py`、`backfill_topic_labels.py` 等
- [ ] 4.3 確認 `backend/.env` 與 Zeabur prod env **沒被動到**（diff before/after = 空）
- [ ] 4.4 確認沒新增任何 commit 含 key 值（gitleaks scan 本地 staging area）

## 5. Ship 驗證

- [ ] 5.1 `pytest backend/tests/test_key_resolver.py -v` 5+ case 全綠
- [ ] 5.2 `pytest backend/tests/ -k "not key_resolver" -x --co | head -5` 確認沒誤觸其他 test
- [ ] 5.3 caplog assertion 在 success / miss / cache hit 三條 path 都驗證過 key 不外洩
- [ ] 5.4 `embedding_bakeoff.py --help` dry-run 正常（task 3.3）
- [ ] 5.5 留 user review、user 同意後再 commit（**本 change 不自行 commit**）
