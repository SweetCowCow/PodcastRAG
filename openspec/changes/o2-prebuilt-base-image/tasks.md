## 1. 建立 base image 定義與發佈管線

> 對應 spec 需求「Base image is rebuilt when build inputs change」；落實 design D2（registry 用 ghcr、tag 用穩定 `base`）與 D3（base 重建走 gha，path-filter + 手動觸發）。

- [x] 1.1 新增 `Dockerfile.base`：`FROM python:3.12-slim`、`WORKDIR /app`，搬入現有 `Dockerfile` 的 apt 段（沿用 BuildKit apt cache mount：`build-essential` / `ffmpeg` / `age` / `ca-certificates` / `curl` / `gnupg` / `lsb-release` + 加 pgdg repo 後裝 `postgresql-client-18`），再 `COPY backend/requirements.txt .` + 帶 pip cache mount 的 `RUN pip install -r requirements.txt`
- [x] 1.2 新增 `.github/workflows/build-base-image.yml`：觸發 = `workflow_dispatch` + `push`（branch main，paths：`backend/requirements.txt`、`Dockerfile.base`、`.github/workflows/build-base-image.yml`）；權限 `packages: write`；步驟 checkout → 用 `GITHUB_TOKEN` 登入 `ghcr.io` → buildx build `Dockerfile.base` → push `ghcr.io/<owner>/podcastrag-base:base`（`<owner>` 取實際 repo owner，由 `git remote get-url origin` 確認）。落實 design d3：base 重建走 gha，path-filter + 手動觸發；d2：registry 用 ghcr、tag 用穩定 `base`；spec needs Base image is rebuilt when build inputs change
- [x] 1.3 commit + push 1.1/1.2 到 main，確認 workflow 被 path-filter 觸發（或手動 `workflow_dispatch`）並成功；GHA log 顯示 push 到 `ghcr.io/<owner>/podcastrag-base:base` 完成

## 2. 確認 base image 可公開 pull

> 對應 spec 需求「Base image is published to a public registry without pull authentication」；落實 design D2（registry 用 ghcr、tag 用穩定 `base`）。

- [x] 2.1 在 GitHub repo 的 Packages 確認 `podcastrag-base` package 存在且 tag `base` 已發佈
- [x] 2.2 將該 package visibility 設為 public；以無認證環境驗證可 pull（例如 `docker pull ghcr.io/<owner>/podcastrag-base:base` 在未 docker login 狀態成功）。spec needs Base image is published to a public registry without pull authentication

## 3. 改寫 app Dockerfile（base-as-cache）

> 對應 spec 需求「Application image derives from a prebuilt base image」；落實 design D4（單一共用 base，四服務不拆）。

- [x] 3.1 改寫根目錄 `Dockerfile`：`FROM ghcr.io/<owner>/podcastrag-base:base`；**移除** apt 段；**保留** `COPY backend/requirements.txt .` + 帶 pip cache mount 的 `RUN pip install -r requirements.txt`（自癒層）；保留 `COPY backend/ .`、`COPY entrypoint.sh /entrypoint.sh`、`chmod`、`EXPOSE 8000`、四服務 START_COMMAND 註解、`ENTRYPOINT ["/entrypoint.sh"]`。落實 design d4：單一共用 base；spec needs Application image derives from a prebuilt base image
- [x] 3.2 本機 `docker build -t podcastrag-app-test .` 成功；確認 build log 無 apt 安裝、pip 對既有套件判定 already satisfied（不重抓 ctranslate2 / faster-whisper 等大型 wheel）
- [x] 3.3 本機跑起該 image（backend 模式，餵必要 env / 連 prod 或本機 PG 皆可），`curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/` 回 200

## 4. base-as-cache 自癒驗證（模擬 base 過期）

> 對應 spec 需求「Base image is a cache, not a contract」；落實 design D1（base image 是「快取」非「契約」，採 route b、否決 route a）。

- [x] 4.1 在 base 未含某套件的情境下驗證自癒：暫時於 `backend/requirements.txt` 加一個 base image 尚未包含的小套件（或基於現有 `:base` 確知缺的套件），本機 `docker build` app image → 確認保留的 pip 層成功裝上該套件、image 內可 import；驗證後還原 `requirements.txt`。落實 design d1：base image 是「快取」非「契約」（採 route b，否決 route a）；spec needs Base image is a cache, not a contract

## 5. Prod 部署與驗收

- [x] 5.1 push 改寫後的 `Dockerfile` 到 main → Zeabur 觸發 build；記錄含 base pull 的整體 build 時間，確認 ≤ 3 分鐘（對照現況 ~10 分）
- [x] 5.2 確認 Zeabur 四服務 backend / worker / dispatcher / beat 皆 RUNNING（用 zeabur CLI 或 dashboard，逐一 service-id 對照 memory 部署清單）
- [x] 5.3 Prod smoke 抽驗行為不變：prod `GET /` 回 200；worker log 顯示訂閱四 queue（transcribe/topic/summary/control）；對任一節目跑一次 chat query 正常回應
- [x] 5.4 archive 前確認：若需回滾，`Dockerfile` 為單檔改動、git revert 該 commit 即回自含 apt+pip 舊 build（base image 保留不影響）
