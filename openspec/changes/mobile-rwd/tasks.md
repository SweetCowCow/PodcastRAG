## 1. P0 — 首頁節目卡爆寬修復

- [x] 1.1 修 src/HomePage.jsx shows grid:手機分支 gridTemplateColumns 改 `minmax(0, 1fr)`、桌機分支改 `repeat(auto-fill, minmax(min(320px, 100%), 1fr))`;完成後在 375px emulation 下每張節目卡寬 ≤ 容器寬(overflow offender 掃描該區歸零),1280px 桌機多欄排版與現狀一致。驗證:emulation 掃描 + 截圖比對 audit shots/02。
- [x] 1.2 修 ShowCard RSS URL 行(src/HomePage.jsx inline 版與 src/Shared.jsx export 版兩份同步):URL 容器加 `minWidth: 0` + 單行 `textOverflow: 'ellipsis'`;完成後 375px 下塞掐(長 omnycontent URL)卡片的 RSS 行單行截斷、「進入節目」在 viewport 內可點。驗證:emulation 實測塞掐卡 + 點擊「進入節目」能進 QueryPage。

## 2. P1 — Btn nowrap 全站修復

- [x] 2.1 src/Shared.jsx Btn base style 加 `whiteSpace: 'nowrap'`;完成後 375px 下「送出」「搜尋」(QueryPage)、「新增金鑰」(admin API 金鑰)、「挑一個節目找找看」(home)全部單行。驗證:emulation 逐顆截圖確認 label 高度 = 單行行高。
- [x] 2.2 中英兩語系掃描按鈕溢出:en 語系下掃 home / query 三 tab / admin 前三 tab,確認無 Btn 溢出父容器;若個別長 label 溢出,以縮短 label 或該處 layout 調整處理(不回退全域 nowrap)。驗證:emulation offender 掃描(en)歸零 + 記錄處理過的個案清單於 change 註記。

## 3. P1 — 對話 citation 卡減層

- [x] 3.1 src/ConversationSourcePanel.jsx 與 src/SegmentCitationCard.jsx 的 isMobile 分支縮減水平 padding/margin 疊層;完成後 375px 對話實跑一題,引文區有效寬 ≥ 85% 氣泡內容寬(以 getBoundingClientRect 量測)。驗證:emulation 實跑 + 量測 script。
- [x] 3.2 citation 卡操作列(播放此段 / 跳到逐字稿):nowrap 生效後確認單行;若兩鈕同行放不下改為縱向堆疊(各自完整單行);集數標題單行 ellipsis 不得擠壓內容區。驗證:emulation 截圖比對 audit shots/11、12(修前直排 → 修後單行)。

## 4. P2 — 對話頁底部固定區收合

- [ ] 4.1 src/QueryPage.jsx 手機分支:對話串 messages 非空時預設收合範例 chips 區,保留「範例」開關可重新展開(展開後點 chip 行為不變);桌機不變。完成後 375×667 有對話時底部固定區高度 ≤ 25% viewport 高。驗證:emulation 量測 dock 高度 + 展開/收合/送出範例題全流程操作。

## 5. P2 — admin 表格與 tab bar

- [ ] 5.1 src/AdminAsrCorrectionTab.jsx 兩個 table(規則列表、候選列表)各包 `overflowX: 'auto'` 容器並設 table `minWidth`;完成後 375px 下兩表可橫捲至最右欄、無被切死內容;1280px 桌機無多餘捲軸。驗證:emulation 橫捲到最右欄截圖。
- [ ] 5.2 src/AdminPage.jsx tab bar:active tab 變更時 `scrollIntoView({ inline: 'nearest', behavior: 'smooth' })`、初次 mount 用 instant 定位;完成後 375px 切到「服務用量」等後段 tab 時該 tab 完整可見。驗證:emulation 依序切 3 個後段 tab 截圖確認。

## 6. 全站回歸驗證與收尾

- [ ] 6.1 mobile emulation 全站重掃(375×667 為主、320×568 抽驗 home):對 audit-report.md P0/P1/P2 六項逐項比對,全數符合 design.md Implementation Contract 第 1–6 點;overflow offender 掃描於 home(登入前後)、query 三 tab、對話實跑、admin 全 tab 歸零。驗證:重掃記錄 + 修後截圖存 docs/research/eq12-mobile-audit/shots-after/。
- [ ] 6.2 桌機回歸抽掃:1280px 下 home / query(對話實跑一題)/ admin 前三 tab 無新增 offender、與修前視覺一致(Implementation Contract 第 7 點)。驗證:emulation 1280px 掃描 + 截圖。
- [ ] 6.3 推 prod 後真機 Safari 抽驗:home 節目卡完整可點、對話跑一題 citation 卡可讀、輸入框聚焦(iOS 鍵盤彈出)時輸入列仍可見可用。驗證:真機操作確認,結果回報記入 change 註記(依 feedback_browser_verification,失敗不得靜默標完成)。
