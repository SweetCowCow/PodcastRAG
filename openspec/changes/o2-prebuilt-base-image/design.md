## Context

`Dockerfile`（repo 根）以 `python:3.12-slim` 為底，單一 image 供 backend / worker / dispatcher / beat 四服務共用（`entrypoint.sh` 靠 `START_COMMAND` 切換）。每次 `git push` 到 main 觸發 Zeabur git-based build，重跑：

1. **apt**：`build-essential`、`ffmpeg`、`age`，加 pgdg repo 後裝 `postgresql-client-18`。
2. **pip**：`backend/requirements.txt` 共 30 套件，其中 `faster-whisper`（含 ctranslate2 等大型 wheel）下載/安裝最耗時。

`Dockerfile` 已用 BuildKit cache mount（apt、pip），但實測單次 build 約 10 分鐘 → 研判 Zeabur 不穩定保留跨 deploy 的 BuildKit cache，幾乎每次冷建。

約束：

- 部署模型 = **直推 main → Zeabur 立即 push-build**，無實質 PR review gate、Zeabur 不會等 CI 綠才建。
- repo 公開於 GitHub。
- 已有 5 個 GHA workflow（`backend-tests.yml` 等），新增一支自然。

## Goals / Non-Goals

**Goals:**

- 把 apt + pip 重層抽進一個預建、可重用的 base image，使後續 Zeabur build 不再跑 apt、pip 僅補差額。
- 在直推 main 的現實下，**base 過期絕不導致 prod 缺套件**（正確性與 base 新鮮度脫鉤）。
- 含 base pull 的 Zeabur build 時間目標 1–3 分鐘（vs 現況 ~10 分）。

**Non-Goals:**

- 不拆 per-service image（不為省 worker-only 的 `faster-whisper` 體積而多維護 base / Dockerfile / 服務設定）。
- 不重做部署管線（不引入「deploy 等 CI」機制）。
- 不採 base-as-contract（Route A）。
- 不移除既有 BuildKit cache mount；不動 `entrypoint.sh` 的四服務切換。

## Decisions

### D1：base image 是「快取」非「契約」（採 Route B，否決 Route A）

app `Dockerfile` `FROM` base image 後，**保留** `pip install -r requirements.txt`：base 已含 → pip 判定已滿足、不重抓大型 wheel（近乎 no-op）；base 缺 → 只裝差額。base 過期僅讓某次 build 變慢，永不缺套件。

- 否決 Route A（base-as-contract：app pin `base:<requirements-hash>`、CI 比對 hash 不符即擋）：在直推 main + Zeabur 立即 build 下，CI 是事後/並行跑、**擋不住已啟動的 deploy** → 改 deps 忘記 bump pin 會靜默缺套件（R2）；且改 deps 時「Zeabur pull `base:新hash`」與「GHA push `base:新hash`」競態（R1）會 deploy 失敗。詳細權衡見 `docs/research/`（discuss 紀錄）/ proposal Non-Goals。

### D2：registry 用 GHCR、tag 用穩定 `base`

repo 公開 → base image 公開 → Zeabur pull 免 registry 憑證。tag 固定為 `base`（穩定、可變指標）。因 D1 把 base 當快取，tag 浮動不影響正確性，故不需不可變 hash tag。

- 否決 Docker Hub（pull rate limit）、Zeabur 內部 registry（憑證複雜）。

### D3：base 重建走 GHA，path-filter + 手動觸發

`build-base-image.yml`：`workflow_dispatch`（手動）＋ `push`（main，path-filter：`backend/requirements.txt`、base Dockerfile、workflow 自身）觸發；build base image 後 push 到 GHCR `:base`。因 D1，「漏觸發/重建慢」只損速度不損正確性，故不需嚴格 gate。

### D4：單一共用 base

四服務沿用單一 image（`START_COMMAND` 切換）。`faster-whisper` 留在共用 base。

## Implementation Contract

**Behavior（可觀察結果）：**

- 操作者 push 一般程式碼變更（不含 `requirements.txt`）到 main 後，Zeabur build 不執行 apt 安裝、pip 僅對 PyPI 做 metadata 確認後判定已滿足；含 base pull 的整體 build 時間明顯低於現況（目標 1–3 分鐘）。
- 四服務（backend / worker / dispatcher / beat）部署後行為與現況一致（同一 image、同 `entrypoint.sh` 切換、同 `START_COMMAND`）。
- 操作者更新 `backend/requirements.txt` 並 push 後，即使 base image 尚未重建，app build 仍會透過保留的 `pip install` 裝上新套件 → prod 不缺套件（base-as-cache 自癒）。

**Interface / 產物：**

- base Dockerfile（暫名 `Dockerfile.base`）：`FROM python:3.12-slim` + 既有 apt 段（含 pgdg repo + `postgresql-client-18`，沿用既有 BuildKit apt cache mount）+ `COPY backend/requirements.txt` + `pip install -r requirements.txt`。
- app `Dockerfile`：`FROM ghcr.io/<owner>/podcastrag-base:base`；移除 apt 段；保留 `COPY backend/requirements.txt .` + 帶 pip cache mount 的 `RUN pip install -r requirements.txt`；保留 `COPY backend/ .`、`COPY entrypoint.sh`、`chmod`、`EXPOSE 8000`、`ENTRYPOINT`。`<owner>` 取實際 GitHub repo owner。
- `.github/workflows/build-base-image.yml`：觸發 = `workflow_dispatch` + `push`（branch main，paths：`backend/requirements.txt`、base Dockerfile、本 workflow）。步驟 = checkout → docker login GHCR（`GITHUB_TOKEN`，`packages: write` 權限）→ buildx build base Dockerfile → push `ghcr.io/<owner>/podcastrag-base:base`。

**Failure modes：**

- base image 尚未存在於 GHCR（首次、或刪除後）→ app build 的 `FROM` 失敗。對策：首建走「先手動 `workflow_dispatch` 跑一次 base build、確認 GHCR 有 `:base` package 後，才 push 改寫後的 app Dockerfile」（見 Migration Plan）。
- base 過期（requirements 已改、base 未重建）→ app build 的保留 pip 層裝差額，build 略慢但成功、prod 不缺套件（預期行為，非故障）。
- GHCR package 預設可能為 private → Zeabur pull 失敗。對策：首建後確認該 package visibility 設為 public。

**Acceptance criteria：**

1. 手動觸發 `build-base-image.yml` 成功，GHCR 出現公開 package `podcastrag-base:base`。
2. 改寫後 app `Dockerfile` 本機 `docker build` 成功；產出 image 能跑起 backend（`GET /` 回 200）。
3. push 到 main 後 Zeabur 四服務（backend / worker / dispatcher / beat）皆 RUNNING；prod `GET /` 200、worker 訂閱四 queue、一次 chat query 正常（行為不變抽驗）。
4. 含 base pull 的 Zeabur build 時間 ≤ 3 分鐘（對照現況 ~10 分）。
5. 模擬 base 過期：在 base 未重建情況下，app build 仍因保留的 pip 層而成功且不缺套件（可本機在 base 故意缺一套件時驗證 pip 補裝）。

**Scope boundaries：**

- In scope：新增 base Dockerfile、改寫 app `Dockerfile`、新增 base build workflow、首建與 prod 部署驗證。
- Out of scope：per-service image 拆分、部署管線改造、移除既有 cache mount、`entrypoint.sh` 改動、frontend（`zbpack.frontend.json` static plan）build。

## Risks / Trade-offs

- [base image 尚未存在導致 app `FROM` 失敗] → Migration Plan 強制「先建 base、確認 GHCR 有 image，再 push app Dockerfile」的順序。
- [GHCR package 預設 private] → 首建後手動確認/設為 public，並在 acceptance criteria 1 驗證。
- [保留 pip 層的網路依賴：PyPI 慢/掛時 build 變慢] → 仍遠優於現況；屬可接受的速度退化、非正確性問題。
- [base 與 app 對 `requirements.txt` 的兩處 `pip install` 重複] → 刻意設計（D1 自癒），非冗餘；base 命中時 app 層近 no-op。
- [Zeabur 偵測根目錄 Dockerfile 的行為] → 沿用既有「根目錄單一 Dockerfile」慣例；base Dockerfile 命名為 `Dockerfile.base` 避免被誤當部署入口。

## Migration Plan

1. 新增 `Dockerfile.base` 與 `build-base-image.yml`（此時 app `Dockerfile` 尚未改）。
2. push 上述兩檔到 main → path-filter 觸發（或手動 `workflow_dispatch`）→ GHA build 並 push `ghcr.io/<owner>/podcastrag-base:base`。
3. 確認 GHCR package 存在且 visibility = public。
4. 改寫 app `Dockerfile`（`FROM` base + 移除 apt + 保留 pip），本機 `docker build` 驗證成功。
5. push app `Dockerfile` → Zeabur build → 驗四服務 RUNNING + prod smoke（acceptance criteria 2–5）。
6. 回滾路徑：app `Dockerfile` 改動為單檔，git revert 該 commit 即回到自含 apt+pip 的舊 build（base image 留著不影響）。
