# 回測：Matrixdock（RWA／貴金屬代幣化）vs Cyfrin

**執行日期**：2026-08-12
**目的**：拿公開的第三方審計報告當標準答案，回測 SecurityCheckKit 的偵測能力，找出情境庫的缺口。

## 標的

| 項目 | 內容 |
|---|---|
| 專案 | Matrixdock（RWA 代幣化：美國國債 STBT、實體黃金 XAUm） |
| 原始碼 | [github.com/Matrixdock-RWA/RWA-Contracts](https://github.com/Matrixdock-RWA/RWA-Contracts) @ `0a83a96aab623e20e1ae996df3cc9c025245d087` |
| 對照報告 | [Cyfrin Matrixdock Audit Report v2.0](https://github.com/Cyfrin/cyfrin-audit-reports/blob/main/reports/2025-04-09-cyfrin-matrixdock-v2.0.pdf)（2025-04-09，Lead auditors: Dacian、Hans） |
| 審計範圍 | `MTokenMessager.sol`、`MTokenMessagerBase.sol`、`MTokenMessagerLZ.sol`、`MTokenMessagerV2.sol` |
| Cyfrin findings | 17 筆：Critical 0、High 0、Medium 0、**Low 4**、Informational 10、Gas 3 |

選這個標的的理由：與 botgoldtoken 同為「單一發行方托管實體貴金屬」的 RWA 子領域，findings 可直接轉移。

**這是公開資料**：公開 repo、公開報告，不涉及任何客戶機密，本文件不受 `domain_incidents/README.md` 的去識別化限制。

## 環境

外部專案是 **Hardhat**，不是 Foundry。實測結論：

- `cli.py check`（Step 0）**硬性要求** `foundry.toml` + `forge build`，對 Hardhat 專案直接失敗。
- `cli.py scan`（Step 1）只呼叫 `slither . --json`，而 crytic-compile 會自動偵測建置系統，**因此對 Hardhat 專案可直接運作**，只要先讓專案能編譯。
- 實際流程：`npm install --legacy-peer-deps`（LayerZero 與 Chainlink CCIP 有 peer 衝突）→ 提供 dummy 環境變數（`KEY`／`ETHSCAN_KEY`／`BSCSCAN_KEY`，config 硬要求）→ `npx hardhat compile` 成功（89 檔，solc 0.8.24）→ `cli.py scan --src-prefix contracts/`。

## 掃描結果 vs Cyfrin

Slither 對全 repo 產出 **443 筆**專案自有發現（High 17／Medium 27／Low 162／Informational 225／Optimization 12）。
限縮到 Cyfrin 的四個 messager 檔（公平比較）後只剩 **26 筆**：naming-convention 13、reentrancy-events 9、unindexed-event-address 2、immutable-states 2。

### 逐條比對（Cyfrin 的 4 個 Low）

| Cyfrin | 內容 | 本工具 Slither 層 | 本工具情境庫層 |
|---|---|---|---|
| L-1 | 強制用原生幣付 CCIP 費用，LINK 持有者多付 10% | ❌ 未報 | ❌ 不適用（經濟設計取捨，非安全情境） |
| L-2 | 使用者可搶跑黑名單、用轉帳或跨鏈把資產移走規避凍結 | ❌ 未報 | ❌ **缺口** → 已新增 **L14** |
| L-3 | messager 缺 `receive()`，誤轉入的 ETH 永久卡住 | ❌ 未報（`locked-ether` 只在 `contracts/fake/` 測試樁觸發，非真實合約） | ❌ 未涵蓋（Slither 已有 `locked-ether` 偵測器，屬工具層而非情境層） |
| L-4 | 跨鏈黑名單處理錯誤（兩個子問題） | ❌ 未報 | ✅ **命中**（子問題一 → 新增的 L15；子問題二 → 既有 **L3**） |

**Informational／Gas 層**：

- **G-1**（`ccipClient` 應宣告 `immutable`）→ Slither `immutable-states` **精準命中**，且命中的兩個位置 `MTokenMessager.sol:14`、`MTokenMessagerBase.sol:6` 與 Cyfrin 列出的完全一致。
- **I-6**（internal 函式命名前綴不一致）→ 與 Slither `naming-convention`（13 筆）鬆散重疊，非精準對應。
- 其餘 I-1～I-10 與 G-2／G-3 皆未命中。

**結論：Slither 層 17 筆中精準命中 1 筆（G-1），全部 4 個 Low 皆未命中。** 這不是工具缺陷，而是靜態分析器的本質——4 個 Low 全是業務邏輯／跨鏈語意問題，正是 `logic_scan.md` 情境庫存在的理由。

### L-4 的細節（情境庫命中的驗證）

`contracts/MToken.sol`：

- `msgOfCcSendToken`（:371-379）在 **發送端** 呼叫 `_checkBlocked(receiver)`（:377）。但 receiver 是**目的鏈**上的地址，在來源鏈上查它的黑名單狀態恆為預設值 → 這個檢查無效。
- `ccReceiveToken`（:416-423）在 **接收端** 直接 `_mint(receiver, value)`（:421），**完全沒有**黑名單檢查 → 被封鎖地址可透過跨鏈轉入繞過限制。

子問題二（接收端漏檢查）是教科書等級的 **L3（旗標/開關未落實：寫入旗標的函式存在，但讀取它的 require 是否出現在所有該擋的路徑上）**，情境庫既有條目即可捕捉。
子問題一（檢查做在錯誤的一側）既有條目**捕捉不到**——L3 只問「有沒有檢查」，不問「檢查的狀態是否在這條鏈上」，因此新增 L15。

## 反向檢查：本工具有沒有找到 Cyfrin 沒報的東西？

Cyfrin 的範圍只有 4 個 messager 檔，以下都**在其宣告範圍之外**，因此不構成「Cyfrin 漏報」，但確實是本工具擴大掃描範圍後的產出：

| Slither check | 位置 | 初步研判 |
|---|---|---|
| `unprotected-upgrade` ×5 | `MTokenMain.sol`、`MTokenSide.sol`、`BullionMinter.sol`、`BullionNFT.sol`、`BullionNFTEnum.sol` | **值得追**。這些是 UUPS（`DelayedUpgradeable` 繼承 `UUPSUpgradeable`），且 `initialize` 未受保護；同一個 codebase 的 `XAUMDCA.sol:122` 與 `XAUMDCAMinter.sol:169` **有**呼叫 `_disableInitializers()`，核心代幣合約卻沒有——同專案內不一致，較像疏漏而非刻意設計。惟 Cancun（EIP-6780）之後 `selfdestruct` 已無法刪除實作碼，經典的「炸掉 implementation」升級路徑大幅減弱，故不宜直接判 A；屬 B/D 等級，需人工定奪 |
| `arbitrary-send-erc20` ×2 | `dca_adapters/OKXSwapAdapter.sol`、`AUSDTAdapter.sol` | 待查：`transferFrom` 的 `from` 是 `dca` 變數，需確認是否為不可變的信任地址 |
| `unchecked-transfer` ×2 | `BullionNFT.sol`、`BullionNFTEnum.sol` 的 `unpackAndRedeem` | 低風險：轉的是自家 MToken（會 revert），但對非標準 ERC20 不成立 |

## 情境庫擴充（本次產出）

兩條皆經原始碼逐行驗證為真後才寫入：

- **L14 特權管制動作可被搶跑規避** —— 來自 Cyfrin L-2。既有 L7 只涵蓋「可搶跑的初始化／認領」，不涵蓋「使用者搶跑管理員的管制動作（黑名單／凍結／沒收）」。條目中明確寫出與 L3 的分界：L3 是旗標沒被讀取，L14 是旗標讀取正確但施加旗標的動作可被搶跑。
- **L15 跨鏈／多實例狀態在錯誤的一側被驗證** —— 來自 Cyfrin L-4 子問題一。要求逐一比對「檢查執行的位置」與「被檢查狀態實際存放的位置」是否同一側，且兩側都要看。

同時修掉一個維護性缺陷：條目欄位原本叫 `對照 L1-L13`，情境每次增補都會讓這個標籤與所有既有條目、以及維護 skill 的驗證 grep 一起過期。已改為版本中立的 **`對照通用情境`**，並把 `logic_scan.md`／`SKILL.md` 中殘留的 `L1-L10`、「十條情境」等過期表述一併更新（其中 `L1-L10` 早在 L11-L13 加入時就已過期，屬既有漂移）。

## 對工具本身的觀察（本次回測順帶修掉）

這三個問題都是被這次回測逼出來的，已於同日修正並以本次資料驗證：

1. **Step 0 綁死 Foundry** → `env_check.py` 新增 `detect_build_system()`，Foundry／Hardhat 雙路徑。`scan` 本來就與建置系統無關（crytic-compile 自行驅動建置），只有 Step 0 擋著。Hardhat 走 `npx hardhat compile`，並針對實測踩到的兩個坑給出提示：config 要求環境變數金鑰（編譯用 dummy 即可）、peer dependency 衝突（`--legacy-peer-deps`）。驗證：本專案 `cli.py check` 由「直接失敗」變為通過，Foundry fixture 回歸測試不受影響。
2. **訊噪比 443:17** → 新增預設開啟的風格預分類，`naming-convention` 與 `unindexed-event-address` 自動預填 C 並標記 `auto_classified: "style"`（仍留在報告中，可用 `--no-auto-style` 關閉）。名單刻意保守，只收絕不可能代表安全問題的檢查器。
3. **`fake/` 測試樁污染** → `filter_results.py`／`scan.py` 新增 `--exclude-path`，可排除位於 `--src-prefix` 內部的 mock 目錄；排除優先於納入，避免 mock 與真合約同框時把真合約一起帶進來。

**綜合效果（本專案實測）**：443 筆 →（排除 `contracts/fake/`）419 筆 →（風格預分類 202 筆）**實際需人工判斷 217 筆，降幅 51%**。
**安全性回歸**：`test-fixtures/vulnerable-vault` 中刻意植入的 5 筆 High/Medium（`weak-prng`、`reentrancy-eth`、`suicidal`、`tx-origin`、`unchecked-lowlevel`）全部維持未分類、等待人工判斷，無任何一筆被自動預分類吃掉。

## 可重現步驟

```bash
git clone https://github.com/Matrixdock-RWA/RWA-Contracts.git && cd RWA-Contracts
git checkout 0a83a96aab623e20e1ae996df3cc9c025245d087
npm install --no-audit --no-fund --legacy-peer-deps
KEY=0x0000000000000000000000000000000000000000000000000000000000000001 \
  ETHSCAN_KEY=dummy BSCSCAN_KEY=dummy npx hardhat compile
KEY=0x0000000000000000000000000000000000000000000000000000000000000001 \
  ETHSCAN_KEY=dummy BSCSCAN_KEY=dummy \
  python3 <kit>/scripts/cli.py scan --out-dir /tmp/bench-matrixdock --src-prefix contracts/
```
