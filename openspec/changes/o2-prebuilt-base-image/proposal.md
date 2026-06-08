## Why

Zeabur git-based deploy 每次 push 都從 `python:3.12-slim` 重跑整段 apt（build-essential / ffmpeg / age / postgresql-client-18，含加 pgdg repo）＋ pip（30 套件，含 ctranslate2 等大型 wheel 的 `faster-whisper`），單次 build 約 10 分鐘。Dockerfile 雖有 BuildKit cache mount，但 Zeabur 不穩定保留跨 deploy 的 cache，導致幾乎每次都是冷建。四個服務（backend / worker / dispatcher / beat）共用同一 image，任何一次部署都吃這 10 分鐘。

## What Changes

- 新增 base Dockerfile（暫名 `Dockerfile.base`）：`python:3.12-slim` + 既有 apt 套件 + `pip install -r requirements.txt`，把「重層」一次烤進可重用 image。
- 改寫 app `Dockerfile`：`FROM ghcr.io/<owner>/podcastrag-base:base`（穩定 tag）＋ `COPY backend/` ＋ `COPY entrypoint.sh`，**並保留**帶 BuildKit cache mount 的 `pip install -r requirements.txt` 作為自癒層（base 已含則近乎 no-op，base 缺則只裝差額）。
- 新增 GitHub Actions workflow `build-base-image.yml`：`workflow_dispatch` ＋ path-filter（`backend/requirements.txt`、base Dockerfile 變更）觸發，build base image 並 push 到 GHCR。repo 為公開 → image 公開 → Zeabur pull 免 registry 憑證。
- 設計原則：**base image 是「快取」非「契約」**。base 過期只讓某次 build 變慢（pip 自癒補上差額），絕不導致 prod 缺套件。base 重建是純優化、非正確性依賴。
- 單一共用 base，四服務不拆；`faster-whisper` 雖僅 worker 用，仍留在共用 base（避免維護多 base / 多 Dockerfile / 多服務設定）。

## Non-Goals

- **不拆 per-service image**：不為了省 worker-only 的 `faster-whisper` 體積而拆成多個 base / app image。
- **不改部署觸發模型**：維持「直推 main → Zeabur push-build」；不引入「deploy 等 CI 綠才跑」的管線重做。
- **不採用「base 當契約」方案（Route A）**：已於 /spectra-discuss 否決——在直推 main、Zeabur 立即 build 的現實下，CI hash gate 擋不住已啟動的 deploy（會靜默缺套件），且改 deps 會有 base-push 與 Zeabur-pull 的競態。
- **不移除既有 BuildKit apt cache mount**：base Dockerfile 沿用既有 cache mount 寫法。
- **不動 entrypoint.sh 的 START_COMMAND 四服務切換邏輯**。

## Capabilities

### New Capabilities

- `container-build-pipeline`: 定義容器 image 的兩段式 build（prebuilt base + app 層）、base-as-cache 自癒語意、base image 的發佈與重建觸發、以及公開可 pull 的 registry 來源。

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 `container-build-pipeline`
- Affected code:
  - New:
    - `Dockerfile.base`
    - `.github/workflows/build-base-image.yml`
  - Modified:
    - `Dockerfile`
  - Removed: (none)
- 部署影響：base image 首建後，後續 Zeabur build 不再跑 apt、pip 僅補差額；含 base pull 的 build 目標 1–3 分鐘（非字面 30 秒）。四服務 deploy 行為不變（同一 image、START_COMMAND 切換）。
- 外部依賴：新增對 GHCR（`ghcr.io`）的 pull 依賴；base 公開故 Zeabur 端免設憑證。
