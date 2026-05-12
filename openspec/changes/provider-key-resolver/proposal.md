# Provider Key Resolver — 小工具 module

## Problem

PodcastRAG 的 provider key 來源有一個結構性 asymmetry：

| 路徑 | Key 來源 | 狀態 |
|---|---|---|
| In-request 後端（`embedding.py` / `whisper_provider.py` 等） | DB `api_keys` 表 經 `step_config.api_key` 注入 | 正常 |
| 離線 standalone scripts（`backend/eval/scripts/embedding_bakeoff.py`、`backend/scripts/backfill_topic_labels.py` 等） | `os.environ['OPENAI_API_KEY']` 直接讀 env | **撞坑** |

`backend/.env` 的 `OPENAI_API_KEY` 是 **Zeabur AI Hub gateway key**（`sk-plhF...`），AI Hub gateway **不支援 embedding model**。真正可呼叫 `text-embedding-3-large` 的 **OpenAI 官方 key**（`sk-proj-...`）只存在 DB `api_keys` 表 `provider='openai'` 一筆。

具體後果：`r3-4-embedding-model-swap` task 1.2 pre-flight bake-off 跑 `embedding_bakeoff.py` 時抓到 AI Hub key → 401 / "no embedding model"，必須要 user 手動從 DB 撈 key、`export OPENAI_API_KEY=...` 後再跑，每次都是手工坑。

env var 命名包袱（`OPENAI_API_KEY` 已被 AI Hub 佔住）按 memory `reference_env_openai_key.md` 不動。需要一個小工具 module，讓任何離線 script 用一致 API 拿到指定 provider 的正確 key。

## Proposed Solution

新增 `backend/app/services/key_resolver.py`，提供：

```python
get_provider_key(provider: str, prefer_env: Optional[str] = None) -> str
```

優先順序：

1. **prefer_env**：若呼叫端傳 `prefer_env='OPENAI_OFFICIAL_KEY'` 且該 env var 已設且非空 → 回該值（讓 dev 可以 ad-hoc override，不必動 DB）
2. **DB**：`SELECT api_key FROM api_keys WHERE provider = :provider ORDER BY created_at DESC LIMIT 1`
3. **找不到**：raise `KeyError` with clear message（**絕不 print / log 任何 key 值**）

同 process 內 in-memory cache，多次呼叫同 provider 只打 DB 一次。

範例 caller migration（**本 change 不 apply，只寫進 tasks.md 等 user review**）：

```python
# Before（embedding_bakeoff.py 現況）
api_key = os.environ.get("OPENAI_API_KEY")  # 抓到 AI Hub key、爆炸

# After
from app.services.key_resolver import get_provider_key
api_key = get_provider_key('openai', prefer_env='OPENAI_OFFICIAL_KEY')
```

## Out of Scope

- **不動 in-request 路徑**（`embedding.py` / `rag.py` / `whisper_provider.py` 等走 `step_config.api_key` 的，本來就正常）
- **不動 `backend/.env`** 任何 env var
- **不動 Zeabur prod env**
- **不 rename `OPENAI_API_KEY`**（命名包袱保留，per memory `reference_env_openai_key.md`）
- **不執行 corpus / eval / 真 API 呼叫**
- **不 commit**（apply / commit 留給 user review）

## Effort 估算

- 實作 module + cache：~1 hr
- 單元測試 5 case：~30 min
- 範例 caller migration（`embedding_bakeoff.py`）：~15 min（apply 階段才動）
- **合計 ~1.75 hr**，獨立 PR / 不阻塞 R3.4

## Ship 標準

1. `pytest backend/tests/test_key_resolver.py -v` 全綠
2. caplog assertion 驗證 resolver 在任何 path（success / fail / cache hit）**都不 log key 值**
3. 範例 caller `embedding_bakeoff.py` 改用新 resolver 後，本地 dry-run `python3 -m eval.scripts.embedding_bakeoff --help` 仍能正常 import（不執行 API 呼叫）
4. tasks.md 列的「未來可遷移 script 清單」記錄在 design.md，作為後續清理工作 backlog（不在本 change apply）

## Risk

- **低**。純新增 module，不動現有路徑；in-request flow 完全不受影響。
- 唯一風險：DB query 失敗時 raise 行為要明確（KeyError 帶 provider 名，**不帶 key 值**），測試 case 覆蓋。
