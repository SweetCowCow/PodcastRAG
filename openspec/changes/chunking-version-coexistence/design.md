## Context

`r3-2-retrieval-fix` Phase 1 lever test 結論：Recall@5 = 0.1548 是 description chunk 顆粒太粗造成的結構性 ceiling，必須走 Phase 2 = Case C = re-chunk 每段 ≤ 200 chars + re-embed backfill。為了單節目 pilot → rollout 的安全進度條，需要 schema 支援 v1（整段）/ v2（細切）共存。

目前 `episode_description_chunks` 設計：

```python
class EpisodeDescriptionChunk(Base):
    __tablename__ = "episode_description_chunks"
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # ← 阻擋 v1+v2 共存
    )
    text: Text
    text_tsvector: TSVECTOR
    embedding: Vector(1536)
    ...
```

`unique=True` on `episode_id` 必須 drop / 改為 composite。

`transcript_chunks` **不在** 本 change 範圍 — 它本來就允許 (transcript_id, chunk_index) composite，未來若要 versioning 比較簡單，但目前無業務需求。

## Goals / Non-Goals

**Goals：**

- DB schema 支援 description chunks 多版本共存（per-episode 同時有 v1 + v2 row）
- Retrieval 對 v1+v2 透明合併（不需要呼叫端知道 versioning）
- 寫入端可指定要寫哪一版（預設 v1，pilot 寫 v2）
- 提供 ops cleanup 腳本（idempotent，per-show，dry-run default）

**Non-Goals：**

- 不寫 v2 的 re-chunking 演算法（屬 `r3-2-retrieval-fix` Section 3）
- 不執行 backfill embedding（pilot 在 `r3-2-retrieval-fix` Phase 2）
- 不動 transcript_chunks
- 不動 RAG retrieval 評分 / RRF 融合 / routing

## Decisions

### D1 — 用 smallint 欄位（不用 enum / string）

`chunking_version smallint NOT NULL DEFAULT 1`：

- smallint 夠用（不會超過幾百個版本）
- int 比 enum 容易加 / 比 string 省 index 空間
- DEFAULT 1 讓既有 row backfill 不需要 explicit update — 直接 `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT 1` 一行
- 未來若要 v3 切法（譬如 sentence-level）直接 `chunking_version=3` 寫入，no migration

### D2 — Composite unique on (episode_id, chunking_version)

原本 `unique(episode_id)` → 改 `unique(episode_id, chunking_version)`。

- 維持「同 episode 同版本只能有一 row」的合理性
- 允許 (episode_id, 1) + (episode_id, 2) 兩 row 共存
- description_indexer UPSERT 邏輯要改成 `on_conflict_do_update(index_elements=[episode_id, chunking_version])`

注意：如果未來想細切（v2 一集 N 個 chunks），constraint 必須改成 (episode_id, chunking_version, chunk_index)，但**本 change 暫不引入 chunk_index 欄位** — pilot 階段先把 v2 每段當 individual row 寫，每 row 一個短段、`episode_id` 不變但同集會有多 row，所以 unique(episode_id, chunking_version) 在 v2 變得不可用。

**修正決策**：constraint 改成 `unique(episode_id, chunking_version, chunk_index)`，並加 `chunk_index smallint NOT NULL DEFAULT 0` 欄位。v1 既有 row backfill `chunk_index=0`（每集本來就只一個），v2 寫入時帶 0..N-1 的 chunk_index。

### D3 — Retrieval 不過濾 chunking_version，但要把 version 帶進 ChunkHit

`backend/app/services/rag.py` 的 `_DESC_RRF_SQL` / `_DESC_SEMANTIC_ONLY_SQL` 兩條 query：

- WHERE 子句**不加** chunking_version filter — v1 + v2 進同一 RRF pool
- SELECT 多帶 `d.chunking_version`
- `ChunkHit` dataclass 新增 `chunking_version: int = 1` 預設值
- 下游（answer prompt、citation 構造、enrich_hits）**不需改**

理由：retrieval 端是 dumb pool，rollout 過程中 v1+v2 哪個贏看 RRF score 自然決定。如果發現 v2 顯著贏（pilot 收尾的 eval 證據），rollout 後就 cleanup v1。

### D4 — Indexer 寫入帶 version 參數

`description_indexer.index_episode_description()` 的 signature 加 `chunking_version: int = 1` keyword。預設 1 → 既有呼叫端零改動。Phase 2 pilot 的新 rechunker 呼叫時傳 `chunking_version=2`。

UPSERT 邏輯：

```python
stmt = pg_insert(EpisodeDescriptionChunk.__table__).values(
    episode_id=episode_id,
    chunking_version=chunking_version,
    chunk_index=chunk_index,
    text=text,
    embedding=embedding,
    ...
)
stmt = stmt.on_conflict_do_update(
    index_elements=[
        EpisodeDescriptionChunk.episode_id,
        EpisodeDescriptionChunk.chunking_version,
        EpisodeDescriptionChunk.chunk_index,
    ],
    set_={...},
)
```

### D5 — Cleanup 腳本 per-show + dry-run default

`backend/scripts/cleanup_v1_description_chunks.py`：

```
usage: cleanup_v1_description_chunks.py [-h] --show-id SHOW_ID [--execute]

dry-run（預設）→ 印出將刪除的 chunk 數 + episode title 清單 + 「需確認 v2 chunks 已存在於每集才能刪」摘要
--execute → 真實執行 DELETE，per-episode 內 transactional（一集刪不掉就回滾該集，繼續下一集）
```

防呆：

- 對指定 show，刪 v1 前 SQL 驗證每集都有 ≥1 個 v2 chunk — 任一集缺 v2 就 abort（除非 `--force`）
- 印出明確的 「總 N 集；已有 v2：M 集；缺 v2：K 集」 統計
- `--force` 才能略過防呆

不在本 change 執行 — 留給 `r3-2-retrieval-fix` Phase 2 收尾後 ops 跑。

### D6 — Migration 步驟

Alembic revision `t8_chunking_version_description_chunks`（depends_on `s7f8a9b0c1d2`）：

**upgrade()**：

```python
# 1. 加 chunking_version 欄位（先帶 default 讓既有 row 自動 backfill）
op.add_column(
    "episode_description_chunks",
    sa.Column(
        "chunking_version",
        sa.SmallInteger(),
        nullable=False,
        server_default=sa.text("1"),
    ),
)
# 2. 加 chunk_index 欄位（同上）
op.add_column(
    "episode_description_chunks",
    sa.Column(
        "chunk_index",
        sa.SmallInteger(),
        nullable=False,
        server_default=sa.text("0"),
    ),
)
# 3. drop 舊 unique constraint（名稱看 schema dump，估計是 episode_description_chunks_episode_id_key）
op.drop_constraint(
    "episode_description_chunks_episode_id_key",
    "episode_description_chunks",
    type_="unique",
)
# 4. add 新 composite unique
op.create_unique_constraint(
    "uq_desc_chunk_episode_version_index",
    "episode_description_chunks",
    ["episode_id", "chunking_version", "chunk_index"],
)
# 5. 改後 server_default 留著也無妨（保險），不刪
```

**downgrade()**：

```python
op.drop_constraint("uq_desc_chunk_episode_version_index", "episode_description_chunks", type_="unique")
op.create_unique_constraint(
    "episode_description_chunks_episode_id_key",
    "episode_description_chunks",
    ["episode_id"],
)
op.drop_column("episode_description_chunks", "chunk_index")
op.drop_column("episode_description_chunks", "chunking_version")
```

注意：downgrade 在 v2 chunks 已存在的情況下會 FK constraint violation — migration docstring 註明「downgrade only safe before any v2 row written」。

### D7 — 監控 endpoint（可選）

`GET /admin/chunking-status` → 回每個 show 的 (v1_count, v2_count, episode_total) breakdown：

```json
{
  "shows": [
    {
      "show_id": "45fc2462-...",
      "title": "這又沒有很屌",
      "episode_total": 163,
      "v1_chunks": 163,
      "v2_chunks": 0,
      "rollout_progress": "0/163"
    }
  ]
}
```

如果時間不夠，本 change 只實作後端 endpoint + 寫進 admin queue UI（Phase 2 開始實際 backfill 時看數字）。如果 Admin UI 太花時間就先只做 endpoint，UI 留給後續 change。

## Implementation Contract

### Schema Diff

`episode_description_chunks`：

| 欄位 | Before | After |
|---|---|---|
| `chunking_version` | (不存在) | `smallint NOT NULL DEFAULT 1` |
| `chunk_index` | (不存在) | `smallint NOT NULL DEFAULT 0` |
| unique | `(episode_id)` | `(episode_id, chunking_version, chunk_index)` |

SQLAlchemy model：

```python
class EpisodeDescriptionChunk(Base):
    __tablename__ = "episode_description_chunks"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "chunking_version", "chunk_index",
            name="uq_desc_chunk_episode_version_index",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(...)
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
        # 拿掉 unique=True
    )
    chunking_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sa.text("1"),
    )
    chunk_index: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sa.text("0"),
    )
    text: ...
    text_tsvector: ...
    embedding: ...
```

### Retrieval Query Diff

`_DESC_RRF_SQL`（before / after diff 示意）：

```sql
-- before
SELECT cb.chunk_id, cb.rrf_score, d.text,
       e.id AS episode_id, e.title AS episode_title
FROM combined cb
JOIN episode_description_chunks d ON d.id = cb.chunk_id
JOIN episodes e ON e.id = d.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k

-- after（加 d.chunking_version SELECT，無 WHERE 變動）
SELECT cb.chunk_id, cb.rrf_score, d.text,
       d.chunking_version,
       e.id AS episode_id, e.title AS episode_title
FROM combined cb
JOIN episode_description_chunks d ON d.id = cb.chunk_id
JOIN episodes e ON e.id = d.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k
```

同理 `_DESC_SEMANTIC_ONLY_SQL` 也加 `d.chunking_version` 進 SELECT。

`ChunkHit` dataclass：

```python
@dataclass
class ChunkHit:
    ...
    chunking_version: int = 1   # 新欄位；transcript hits 預設 1 不影響行為
```

`retrieve_descriptions()` 內構造 ChunkHit 時 `chunking_version=int(row["chunking_version"])`。

### Indexer Diff

`index_episode_description(... , chunking_version: int = 1, chunk_index: int = 0)`：

- 預設 (1, 0) 保留現有 caller 零改動
- UPSERT index_elements 改 `[episode_id, chunking_version, chunk_index]`
- 「delete-existing-row when empty」邏輯改成 `WHERE episode_id = ? AND chunking_version = ?`（只刪同版本的，不殃及另一版本）

### Cleanup CLI

`backend/scripts/cleanup_v1_description_chunks.py`：

```python
# 簡化骨幹
async def main():
    args = parse_args()  # --show-id, --execute, --force
    async with get_session() as db:
        eps = await db.execute(select(Episode.id, Episode.title).where(Episode.show_id == args.show_id))
        eps = list(eps)
        v2_counts = {ep_id: cnt for ep_id, cnt in await db.execute(
            select(EpisodeDescriptionChunk.episode_id, func.count())
            .where(EpisodeDescriptionChunk.chunking_version == 2)
            .group_by(EpisodeDescriptionChunk.episode_id)
        )}
        missing_v2 = [ep for ep in eps if v2_counts.get(ep.id, 0) == 0]
        print(f"Show {args.show_id}: total={len(eps)} with_v2={len(eps) - len(missing_v2)} missing_v2={len(missing_v2)}")
        if missing_v2 and not args.force:
            print("Refusing to delete v1: some episodes have no v2 chunk yet. Use --force to override.")
            sys.exit(2)
        if not args.execute:
            print(f"[dry-run] would delete v1 chunks for {len(eps) - len(missing_v2)} episodes")
            return
        # execute deletion per-episode
        ...
```

### Monitoring Endpoint（可選）

`GET /admin/chunking-status`，admin-only auth：

```python
SELECT
    s.id AS show_id, s.title,
    COUNT(DISTINCT e.id) AS episode_total,
    COUNT(d.id) FILTER (WHERE d.chunking_version = 1) AS v1_chunks,
    COUNT(d.id) FILTER (WHERE d.chunking_version = 2) AS v2_chunks
FROM shows s
JOIN episodes e ON e.show_id = s.id
LEFT JOIN episode_description_chunks d ON d.episode_id = e.id
GROUP BY s.id, s.title;
```

## Rollback Plan

| 階段 | Rollback 動作 |
|---|---|
| Migration 跑完，沒寫 v2 | `alembic downgrade -1` — drop unique、drop column；安全 |
| 寫過 v2 chunks 想 rollback | 先跑 cleanup 腳本刪所有 v2 chunks（`WHERE chunking_version = 2`），再 `alembic downgrade -1` |
| Pilot v2 retrieval 變差 | 不需要 schema rollback — 直接保留 v1+v2 共存，rag 端 v2 自然輸 RRF；或刪 v2 chunks 退回 |
| Migration 跑到一半失敗（極罕見） | Alembic transaction atomic 不會壞表；重跑 |

## Risks / Trade-offs

| 風險 | 嚴重性 | 緩解 |
|---|---|---|
| `unique(episode_id)` drop 後不小心 indexer bug 寫 N 個 v1 chunk | 中 | 新 unique(episode_id, chunking_version, chunk_index) 仍會擋；單元測試覆蓋 |
| Retrieval pool 拿到 v1+v2 同 episode 兩 hit，top-K 出現 dedup 重複 | 中 | 下游 SourceCard 用 (episode_id, start_time) 去重；description chunks `start_time=0` 對所有 desc 都一樣，本來就需要 dedup 邏輯 — 在 enrich_hits 階段 dedup by (episode_id, chunking_version, chunk_index) 避免兩版同集都顯示 |
| Migration 在 prod 跑時鎖表 | 低 | `ALTER TABLE ADD COLUMN ... DEFAULT 1` 在 PG ≥ 11 是 metadata-only fast path；資料量小（≤ 500 row）無感 |
| downgrade 在 v2 已寫入後跑會壞 unique | 中 | docstring 註明先 cleanup v2；CI 不跑 downgrade |
| Cleanup 腳本誤刪別 show 的 v1 | 高 | 強制 `--show-id` 必填、`--execute` 不加就 dry-run、`--force` 才略過 v2-existence 防呆 |
| monitoring endpoint 把 admin 路由弄壞 | 低 | endpoint 是新加路由，無 side effect；單元測試覆蓋 |

## 與 r3-2-retrieval-fix 的依賴關係

```
r3-2-retrieval-fix Phase 1（lever test）  ──完成 2026-05-12
                ↓ 證實 Case C
chunking-version-coexistence（本 change） ──現在 propose
                ↓ archive
r3-2-retrieval-fix Phase 2（pilot rechunk + re-embed「這又沒有很屌」）
                ↓ pilot pass
r3-2-retrieval-fix Phase 2 Rollout（「曼報」「壹加壹電台」）
                ↓ 全 rollout 完
ops 跑 cleanup_v1_description_chunks.py per-show
                ↓
final eval pass → r3-2-retrieval-fix archive
```

本 change 卡 r3-2-retrieval-fix Phase 2 入口；本 change 不 archive，pilot 就動不了。

## 變更歷史

- 2026-05-12 propose：r3-2-retrieval-fix Phase 1 lever 結論定 Case C → 本 change 開出來解 schema 共存問題
