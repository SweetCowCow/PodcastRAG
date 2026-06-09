## Context

`backend/app/services/rag.py` 目前 1330 行，含 26 個函式 + 3 個 class，混合五種職責。經對源碼 1:1 驗證，外部介面狀況如下（這是設計的事實基礎，非推測）：

- 對 rag 的存取幾乎全是「模組屬性」形式（`rag.retrieve_hybrid` 等），共 24 處，其中 `rag.retrieve_hybrid` 佔 19 處。
- 真實 importer 僅三個非測試檔：`app/api/query.py`（`from app.services import rag` + `from app.services.rag import ChunkHit as RagHit, MetadataFilters`）、`app/services/chat_agent/tools.py`（`from app.services import rag, rag_rerank`）、`app/api/admin/rrf_sweep.py`（執行期對 `rag.RRF_WEIGHTS` 做 in-place clear/update）。
- 公開常數被外部依賴：`rag.RRF_WEIGHTS`、`rag.RRF_K`、`rag.RETRIEVAL_TOP_K`、`rag.HISTORY_WINDOW` 等。
- 私有 symbol 也被外部（測試）使用：`rag._build_ts_query`、`rag._hit_key`、`rag._should_skip_routing`。
- 內部依賴圖揭露關鍵耦合：`_build_ts_query` 被 retrieval（`retrieve`/`retrieve_descriptions`/`retrieve_titles`）與 enrich（`_fetch_highlight` line ~1069）**兩層共用**（已 grep 確認）。`ChunkHit` 被 retrieval/enrich/generation 三層共用。

約束：純內部重構，行為零改變；不得新增依賴；須維持 prod chat query 行為不變。

## Goals / Non-Goals

**Goals:**

- 把 rag.py 依單一職責拆成 6 個子模組，降低未來改動的耦合半徑。
- 維持所有外部 `rag.X` 介面與 admin 對 `RRF_WEIGHTS` 的執行期改寫完全不變（零 importer 修改）。
- 把 `_build_ts_query` 隔離進 `rag_sql`，為後續 EQ3c BM25 縮小改動面。
- 全程可漸進、每步可獨立 commit、每步測試綠。

**Non-Goals:**

- 不消滅 rag.py（刻意保留為 facade）。
- 不改任何檢索/生成/SQL 行為或參數。
- 不做 BM25（EQ3c 獨立 change）。
- 不動 `rag_rerank.py`。

## Decisions

### D1：採 facade re-export（路線 A），否決徹底清空（B）與保守半拆

rag.py 改為 `from rag_types import *`、`from rag_config import *` … 並以各子模組的 `__all__` 控制 re-export 面。理由：外部存取幾乎全是 `rag.X` 模組屬性形式，facade 讓三個 importer + admin sweep 零修改。否決 B（徹底清空）因 churn 大且無對應收益；否決保守半拆因會讓 `_build_ts_query` 留在 rag.py、EQ3c 前置目標落空。

### D2：`ChunkHit` + `MetadataFilters` 獨立成 `rag_types`（最底層）

三層共用，放任一層都造成循環 import。`rag_types` 不 import 任何其他 rag 子模組，位於依賴圖最底。

### D3：`_build_ts_query` 進 `rag_sql`，retrieval 與 enrich 都向下依賴它

已驗證 enrich 的 `_fetch_highlight` 也呼叫 `_build_ts_query`。故 `rag_sql` 位於 retrieval 與 enrich 之下，兩者 `from app.services import rag_sql` 後以 `rag_sql._build_ts_query` 呼叫。

### D4：測試 patch 策略改為「patch 來源模組」

- reload 型測試（`test_rag_retrieval_flags`、`test_rag_embedding_v2_flag`）原 `importlib.reload(app.services.rag)` 來重跑 config 解析 → 改為 reload `app.services.rag_config`（解析與 module-level 快取變數的新家）。
- tokenizer patch 測試（`test_tokenizer_show_name_filter`、`test_rag_rrf` 等）原 `monkeypatch.setattr(rag.tokenizer, "get_show_name_terms", …)` → 改為直接 patch 來源 `app.services.tokenizer.get_show_name_terms`。此寫法不再依賴 rag 命名空間的 re-import，本質上更穩。
- 對 `rag._build_ts_query(...)` 的「直接呼叫」測試靠 facade re-export 仍有效，不需改呼叫點，只需改 patch target。

### D5：`RRF_WEIGHTS` 必須是單一 dict 物件

`admin/rrf_sweep.py` 對 `rag.RRF_WEIGHTS` 做 in-place `.clear()`/`.update()`。`RRF_WEIGHTS` 定義在 `rag_config`，retrieval 與 facade 皆以 `from rag_config import RRF_WEIGHTS` 取得**同一個 dict 物件**，in-place 改寫對所有引用可見。任何子模組都不得 rebind（重新賦值）此名稱，否則切斷可見性。

## Implementation Contract

**Behavior（可觀察）**：重構前後，prod chat query 與三種搜尋模式的輸出完全一致；全測試套件綠。無任何使用者可見差異。

**外部介面（須維持不變）**：
- `rag.retrieve_hybrid`、`rag.retrieve`、`rag.retrieve_descriptions`、`rag.retrieve_titles`、`rag.route_episodes`、`rag.enrich_hits`、`rag.answer_with_chunks`、`rag.rewrite_question`、`rag.format_enumeration_block`、`rag.strip_citations`、`rag._should_skip_routing`、`rag._build_ts_query`、`rag._hit_key` 皆可透過 rag facade 取用。
- 資料結構 `rag.ChunkHit`、`rag.MetadataFilters` 可取用；`query.py` 的 `from app.services.rag import ChunkHit as RagHit, MetadataFilters` 仍有效。
- 公開常數 `rag.RRF_WEIGHTS`（可 in-place 改寫）、`rag.RRF_K`、`rag.RRF_PER_SIDE`、`rag.RETRIEVAL_TOP_K`、`rag.DESCRIPTION_CAP`、`rag.ROUTE_EPISODES_K`、`rag.HISTORY_WINDOW`、`rag.TITLE_RRF_PER_SIDE`、`rag.REWRITE_SYSTEM_PROMPT`、`rag.ENUMERATION_BLOCK_MAX_LIST_ROWS` 皆可取用。

**模組依賴方向（不得有循環）**：`rag_types`（底）← `rag_config` ← `rag_sql` ← `rag_retrieval` / `rag_enrich` ← `rag_generation`；`rag.py` facade 在最上層 re-export 全部。

**Failure modes**：任何 import error、循環 import、或測試紅燈即視為該步失敗，當步 revert 不繼續。`_chat_with_tracker` 的 langfuse 注入須維持原行為（不得因搬移改變 tracker 初始化時機）。

**Acceptance criteria**：
- 全 `backend/tests/` 綠（特別是 `test_rag_*`、`test_tokenizer_show_name_filter`、`test_admin_rrf_sweep`、`test_chat_*`）。
- `python -c "from app.services import rag"` 無 error 且 `rag.RRF_WEIGHTS` 等 symbol 可存取。
- prod chat query smoke：同一問題回傳 200 + citations 數與重構前一致。

**Scope 邊界**：in scope = rag.py 拆分 + facade + 4 測試檔 patch target 更新；out of scope = 行為/參數/SQL/prompt 任何改動、BM25、rag_rerank。

## Risks / Trade-offs

- [reload 型 env 測試命名空間失效] → reload `rag_config`（解析新家）而非 rag facade（D4）。
- [tokenizer patch 命名空間失效] → 改 patch 來源 `app.services.tokenizer.get_show_name_terms`（D4）。
- [`RRF_WEIGHTS` 被 rebind 切斷 admin in-place 改寫可見性] → 全程只 in-place 改寫、子模組與 facade 共用同一 dict，禁止重新賦值（D5）。
- [langfuse tracker 注入時機改變] → 搬 `_chat_with_tracker` 後比對 trace，確認 tracker 初始化與 api_health 記錄不變。
- [循環 import] → 嚴格分層依賴方向，`rag_types` 不依賴任何 rag 子模組。
- [facade `import *` 遮蔽 linter 未使用 import 偵測] → 每個子模組定義明確 `__all__`，facade re-export 受控。

## Migration Plan

採 spike 節奏，每步一個獨立 commit + 跑全測試綠，紅燈即停：

1. 抽 `rag_types.py`（`ChunkHit`、`MetadataFilters`），rag.py re-export，跑全測試。
2. 抽 `rag_config.py`（`_parse_*` + 公開常數 + runtime 快取變數），更新 `test_rag_retrieval_flags`/`test_rag_embedding_v2_flag` 改 reload `rag_config`，跑全測試。
3. 抽 `rag_sql.py`（`_build_ts_query` 等 + SQL 模板），更新 tokenizer patch 測試改 patch 來源模組，跑全測試。
4. 抽 `rag_enrich.py`（`enrich_hits` + `_fetch_*`），跑全測試。
5. 抽 `rag_generation.py`（`answer_with_chunks` + JSON 修復 + `rewrite_question`），跑全測試。
6. 抽 `rag_retrieval.py`（`retrieve*` + `route_episodes` + `retrieve_hybrid`），跑全測試。
7. rag.py 收斂為純 facade（只剩 re-export + `__all__`），跑全測試 + prod chat query smoke 比對。
