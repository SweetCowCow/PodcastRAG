# Design — provider-key-resolver

## D1. Function signature

```python
# backend/app/services/key_resolver.py

from typing import Optional

def get_provider_key(provider: str, prefer_env: Optional[str] = None) -> str:
    """
    Resolve provider API key for offline / standalone scripts.

    Resolution order:
      1. If prefer_env is set AND os.environ[prefer_env] is non-empty → return it
      2. SELECT api_key FROM api_keys WHERE provider = :provider
         ORDER BY created_at DESC LIMIT 1
      3. raise KeyError(f"No API key found for provider={provider!r}")

    Cached per (provider, prefer_env) tuple within process lifetime.
    Never logs / prints the key value (success, miss, or exception).

    Args:
        provider: e.g. 'openai', 'anthropic', 'deepgram'
                  (matches api_keys.provider column)
        prefer_env: optional env var name to consult before DB.
                    Convention: use distinct names from default like
                    'OPENAI_OFFICIAL_KEY' to avoid collision with
                    OPENAI_API_KEY (AI Hub gateway key).

    Returns:
        Raw API key string.

    Raises:
        KeyError: when no key found in env or DB. Message contains
                  provider name only, never the key value.
    """
```

## D2. 優先順序邏輯

```
get_provider_key('openai', prefer_env='OPENAI_OFFICIAL_KEY')
  │
  ├─ os.environ.get('OPENAI_OFFICIAL_KEY') ──→ non-empty ──→ return env value
  │                                          ──→ empty/missing ──┐
  │                                                              ▼
  ├─ cache lookup (provider, prefer_env) ──→ hit ──→ return cached
  │                                       ──→ miss ──┐
  │                                                  ▼
  ├─ sync engine: SELECT api_key FROM api_keys
  │   WHERE provider = 'openai'
  │   ORDER BY created_at DESC LIMIT 1
  │                                       ──→ row ──→ cache + return
  │                                       ──→ none ──┐
  │                                                  ▼
  └─ raise KeyError("No API key found for provider='openai'")
```

關鍵設計選擇：

- **`prefer_env` 不快取**：每次呼叫都重讀 env，讓 dev 可以中途 export 不同值 debug；DB 結果才快取。
- **`ORDER BY created_at DESC`**：同 provider 多筆時取最新，符合 admin UI 「新增即啟用」直覺。
- **`LIMIT 1`**：本 change 不引入「key rotation 期同 provider 多筆並存」邏輯，未來若需要，新增 `label` 參數而非改本函式。
- **Cache scope**：module-level dict `_CACHE: dict[tuple[str, Optional[str]], str]`，process lifetime；scripts 都是短命進程，不需 invalidation。

## D3. DB session 策略

本 module 給離線 script 用，**不在 ASGI request scope**，不能用 `get_db()` dependency。

選擇 **sync engine + sessionmaker**（不用 async）：

- 理由：離線 scripts 多半 sync flow（embedding_bakeoff、backfill_topic_labels 都是 sync），強迫 `asyncio.run` 反而打架。
- 實作：`from sqlalchemy import create_engine`，從 `app.core.config.settings.database_url` 衍生 sync url（把 `postgresql+asyncpg://` 改 `postgresql+psycopg://` 或 `postgresql://`），module-level singleton。
- 不重用 `app.core.database.engine`（那是 async engine）。

## D4. Why no rename of OPENAI_API_KEY

per memory `reference_env_openai_key.md` + 專案 CLAUDE.md：

1. `OPENAI_API_KEY` 在 `backend/.env` 已固定為 AI Hub gateway key，多處（test conftest、alembic seed、admin LLM step migration）依賴這個命名
2. Zeabur prod env 也用同樣命名，rename 要動 Zeabur env + redeploy + 同步本機，high blast radius
3. 改 env 命名解決不了根本問題（離線 script vs in-request 兩條路徑 key 來源不同）
4. 新 resolver 讓 caller 可以用 distinct env var name（譬如 `OPENAI_OFFICIAL_KEY`）做 ad-hoc override，**並存** 不是 rename，零 blast radius

## D5. Logging discipline

- 函式內部任何 `print` / `logging.*` 呼叫，**不准** 把 `api_key` 變數塞 message
- success path：完全不 log（避免測試環境誤洩）
- miss path：`raise KeyError(f"No API key found for provider={provider!r}")` — 只含 provider 名
- DB 連線失敗：讓 SQLAlchemy 原 exception 直接 bubble up（其 message 不含 key 值；若含則 SQLAlchemy bug，另案）
- 測試 case 用 `caplog.records` 掃所有 log record 的 message，assert 任何已知 key prefix（`sk-`、`sk-proj-`、`sk-plhF`）都不出現

## D6. 未來可遷移 script 清單（**不在本 change apply**）

`grep -rln "OPENAI_API_KEY" backend/` 找到的 offline caller：

| 檔案 | 用途 | 遷移優先度 |
|---|---|---|
| `backend/eval/scripts/embedding_bakeoff.py` | embedding model bake-off | **高**（本 change 範例 caller，apply 階段先動這個） |
| `backend/eval/scripts/judge_bakeoff.py` | judge LLM bake-off | 中 |
| `backend/eval/scripts/build_golden_set.py` | 建 golden set | 中 |
| `backend/eval/metrics/judge_metrics.py` | judge metric 計算 | 中 |
| `backend/scripts/backfill_topic_labels.py` | topic label backfill | 中（已跑完，下次跑前清） |
| `backend/tests/conftest.py` | test fixture | **低**（test 用 mock key，不該動 prod resolver） |
| `backend/tests/test_admin_llm_step_migration.py` | migration test | **低**（同上） |
| `backend/alembic/versions/l0a1b2c3d4e5_*.py` | seed migration | **不動**（migration 是 historical record） |

每個遷移都是獨立 PR / 獨立 change，本 change 只 ship resolver + 改 `embedding_bakeoff.py` 一例做示範。

## D7. Test 策略（caplog 重點）

5 個 case，全在 `backend/tests/test_key_resolver.py`：

1. `test_prefer_env_set_returns_env_value` — monkeypatch env var → 回值、確認沒打 DB（mock session 不該被 called）
2. `test_prefer_env_empty_falls_back_to_db` — env 設空字串 / 未設 → DB row → 回 DB value
3. `test_db_multiple_rows_returns_latest` — fixture 插兩筆同 provider 不同 created_at → 回最新
4. `test_db_miss_raises_key_error` — provider 不存在 → `pytest.raises(KeyError, match="provider='nonexistent'")`
5. `test_no_key_logged` — `caplog.set_level(logging.DEBUG)` → 跑成功 path + 失敗 path → assert key value（fixture 的 fake `sk-test-xxxxx`）不出現在任何 `record.message`

## D8. 與 r3-4-embedding-model-swap 的關係

本 change 是 R3.4 task 1.x 隱含的「pre-flight handcraft」工具化。R3.4 task 1.1 寫的是 user 手動 export，本 change 完成後可以把 task 1.1 簡化成「caller 自動從 DB 抓」。但本 change **不修改** R3.4 的 tasks.md（避免 cross-change coupling），只在 R3.4 apply 時若本 change 已 ship，順手用即可。
