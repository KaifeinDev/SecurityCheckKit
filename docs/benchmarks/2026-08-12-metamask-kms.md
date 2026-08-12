# 回測：MetaMask Delegation Framework（KMS／金鑰管理與委派授權）vs Cyfrin

**執行日期**：2026-08-12
**目的**：以 KMS 領域（帳戶抽象、委派授權、簽章驗證）的公開審計報告回測工具能力，找出情境庫缺口。

## 標的

| 項目 | 內容 |
|---|---|
| 專案 | MetaMask DeleGator／Delegation Framework（ERC-4337 帳戶抽象上的階層式權限委派） |
| 原始碼 | [github.com/MetaMask/delegation-framework](https://github.com/MetaMask/delegation-framework) @ `d522a38b0b0f1c27d896790262302a52c3720e06` |
| 對照報告 | [Cyfrin Delegation Framework Audit part 1 v2.0](https://github.com/Cyfrin/cyfrin-audit-reports/blob/main/reports/2025-03-18-cyfrin-Metamask-DelegationFramework1-v2.0.pdf)（2025-03-18，11 天，13 findings） |
| Cyfrin findings | **High 1**、Medium 2、Low 5、Informational 4、Gas 1 |

選此標的的理由：涵蓋 HybridDeleGator（EOA + P256/WebAuthn passkey）、MultiSigDeleGator（門檻簽章）、EIP-7702 無狀態委派、以及 20+ 個 caveat enforcer，正是「誰能動資產、授權怎麼授出與收回」的合約層邏輯。且**有 High**，比 RWA 那次（0 High/Medium）更能測出能力。

**公開資料**：公開 repo、公開報告，不受 `domain_incidents/README.md` 去識別化限制。

## 環境

Foundry 專案，走標準路徑，**Step 0 一次通過**（對照 Matrixdock 的 Hardhat 需繞過）：

```bash
git submodule update --init --recursive --depth 1   # lib/ 有 8 個 submodule
python3 <kit>/scripts/cli.py check --src-prefix src/
# [build-system] foundry / [forge build] OK / OZ 5.0.2 / solc 0.8.24 / slither 0.11.4
```

## 掃描結果

Slither 對 `src/` 產出 **252 筆**（High 2、Medium 14、Low 20、Informational 216）。
風格預分類吃掉 209 筆（naming-convention 207、unindexed-event-address 2），**實際需人工判斷 43 筆**。

降噪效果比 RWA 那次好很多（217 → 43），因為這個 codebase 沒有 mock 目錄，且 naming-convention 佔比更集中。

## 逐條比對

| Cyfrin | 內容 | Slither 層 | 情境庫層 |
|---|---|---|---|
| **H-1** | EntryPoint 未納入 userOp 雜湊，可跨 EntryPoint 重放 | ❌ | ❌ **缺口** → 新增 **L18** |
| M-1 | Transfer Amount enforcer 未檢查實際轉帳就增加額度 | ❌ | ❌ **缺口** → 新增 **L17** |
| M-2 | Allowed 系 enforcer 重複項目造成 gas griefing | ❌ | 未涵蓋 |
| L-1 | EIP7702StatelessDeleGator 不符 EIP-4337 簽章驗證規範 | ❌ | 未涵蓋（規範遵循類） |
| L-2 | AllowedCalldataEnforcer 無法驗證空 calldata，擋掉 receive() | ❌ | 未涵蓋 |
| L-3 | ERC721TransferEnforcer 導致 safe transfer revert | ❌ | 未涵蓋 |
| L-4 | IdEnforcer::beforeHook() 事件參數錯置 | ❌ | 未涵蓋 |
| L-5 | TimestampEnforcer 時間範圍驗證不一致 | ❌ | 未涵蓋 |
| I-1〜I-4、G-1 | 資訊類與 gas | ❌ | — |

**Slither 層 13 筆命中 0。** 比 RWA 那次（命中 1 筆 gas 建議）更差——這個 codebase 是精心設計的權限框架，Slither 的模式比對完全使不上力。

### 一個差點誤判成命中的地方

Slither 的 `unused-return` 有 14 筆，其中 3 筆正好落在 M-1 所指的 `ERC20TransferAmountEnforcer._validateAndIncrease`、`NativeTokenTransferAmountEnforcer.beforeHook` 上。讀完描述才確認**兩者無關**：Slither 報的是 `(target_, , callData_) = _executionCallData.decodeSingle()` 這種**解構時丟棄欄位**，屬良性風格問題；M-1 講的是額度記帳與實際轉帳脫鉤。若只憑「檔名與函式名對得上」就宣稱命中，會得出完全錯誤的回測結論。

## 情境庫擴充（皆經原始碼確認）

### L17 記帳依「意圖」而非「實際結果」，且失敗不回滾

來源 Cyfrin **M-1**。`ERC20TransferAmountEnforcer._validateAndIncrease`（`src/enforcers/ERC20TransferAmountEnforcer.sol:76-97`）在 `beforeHook` 階段就以 calldata 的意圖值累加 `spentMap`：

```solidity
spent_ = spentMap[msg.sender][_delegationHash] += uint256(bytes32(callData_[36:68]));
require(spent_ <= limit_, "ERC20TransferAmountEnforcer:allowance-exceeded");
```

在 `EXECTYPE_TRY` 模式下轉帳失敗不會 revert，額度照樣被扣。惡意 delegate 可反覆送出注定失敗的轉帳，把 delegator 的額度耗盡而一毛錢都沒轉出。

**既有情境為何抓不到**：L9（記帳順序錯誤）的情境比對要求「**同一函式內**既更新記帳又移轉資產」。這裡記帳在 enforcer、轉帳由 DelegationManager 之後執行，enforcer 根本不碰資產，前置條件不成立就被跳過了。這是兩段式判定的正確行為——問題在情境本身的涵蓋面，不在判定流程。

### L18 簽章雜湊未涵蓋全部應綁定的上下文

來源 Cyfrin **H-1**。`getPackedUserOperationHash` 未把 EntryPoint 位址納入雜湊，同一份已簽 userOp 可在另一個 EntryPoint 上重放。MetaMask 已於 commit `1f91637` 修復。

**既有情境為何抓不到**：L1-L16 完全沒有觸及「簽章雜湊該綁定哪些上下文」這個面向。這類問題（EIP-712 domain separator 涵蓋不足、跨實例／跨鏈重放）是簽章驗證系統的常見缺口，且 KMS／AA 領域幾乎必然涉及。

## 觀察

1. **靜態分析器對權限框架幾乎無效**：兩次回測合計 30 筆第三方發現，Slither 精準命中 1 筆（且是 gas 建議）。這不是安裝或設定問題——Slither 找的是程式碼形狀，而審計公司找的是「這個授權模型在什麼情況下會被繞過」。
2. **情境庫是唯一有效的一層，但需要持續擴充**：這次兩條 Medium/High 都落在既有 18 條之外，補完後才涵蓋。兩次回測共長出 5 條情境（L14-L18）。
3. **降噪參數在乾淨 codebase 上效果更好**：252 筆 → 43 筆需人工判斷（83% 降幅）。

## 三次「檔名巧合」近似誤判（重要）

本次有三組 Slither 發現，其檔案與函式恰好就是 Cyfrin findings 所指的位置，讀完描述才確認**全部無關**：

| Slither | 落在 | 看似對應 | 實際 |
|---|---|---|---|
| `unused-return` ×3 | `ERC20TransferAmountEnforcer`、`NativeTokenTransferAmountEnforcer` | M-1 額度記帳缺陷 | 報的是 `decodeSingle()` 解構丟棄欄位，良性 |
| `timestamp` ×1 | `TimestampEnforcer` | L-5 時間範圍驗證不一致 | 通用「用了 block.timestamp 比較」，抓不到 before/after 一致性缺失 |
| `missing-zero-check` ×1 | `NativeTokenPaymentEnforcer` | I-4 delegate 位址驗證不足 | 報的是建構子參數缺零值檢查，與 `afterAllHook()` 的 delegate 驗證無關 |

若以「檔名＋函式名對得上」判定命中，這次回測會得出「13 筆命中 3」的錯誤結論。**回測比對必須逐筆讀描述，不能靠位置比對。** 三筆的 dev_note 都明確寫出「這與參考報告 X 不是同一個問題」，避免日後誤讀。

## 完整報告產出（Step 2 + Step 4）

**分類結果**（252 筆）：A 0、B 16、C 236（含風格預分類 209）、D 0。
**人工複核發現 2 筆**：M1（High／情境 L18）、M2（Medium／情境 L17）。
**資安等級第四級**，exit code 4——M1 為 High 且屬 A 類，依規則直接判第四級。Step 3 跳過（第三方 repo，不改其原始碼），故報告中「忽略前／忽略後」數字相同。

**來源揭露**：M1／M2 是**自參考報告轉錄後回到原始碼確認**，不是本工具獨立發現。兩筆的 `dev_note` 都以粗體明寫此事。回測的目的是誠實計算命中率，若把轉錄來的發現當成自有產出，整份比較就失去意義。

分類過程中依 L13 情境查證了 `entryPoint` 是否可事後替換（結論：`immutable`，不適用），這是 `arbitrary-send-eth` 判為誤判的必要前提——`_payPrefund` 的收款方恆為 EntryPoint，而非 Slither 所稱的任意地址。

## 補強一：建立 AA 領域事故庫

第一輪回測「命中 0」的根因不是方法不適用，而是**這個領域的知識沒進庫**：`domain_incidents/` 當時只有 `rwa.md`，KMS 跑 Rule 1 走的是「檔案不存在」分支，等於零先驗知識；而 18 條通用情境只有 2 條（還是這次才補的 L17／L18）碰得到授權框架。

依 Rule 1 對此領域做外部調查後建立 `references/domain_incidents/account-abstraction.md`，8 條模式：執行入口缺 EntryPoint 驗證、簽章未涵蓋 gas 欄位、驗證階段寫入狀態被同批次覆寫、ERC-1271 缺 domain 綁定、依賴 revert 阻止付款、ERC-7702 初始化搶跑、違反 ERC-7562 驗證範圍限制、重入防護前提被 AA 打破。

**循環論證警告**：這份領域檔是**讀過 part 1 之後**寫的。用 part 1 驗證它會是循環論證，故不計入命中率。可以說的只有：`D-AA-04` 的標準查證問題第 2 項（「是否綁定了所有可替換的執行入口——EntryPoint、router、實作版本？」）確實直指 part 1 的 H-1。

## 補強二：增量回測（part 2，未讀過即先寫下預測）

用 **Cyfrin part 2**（2025-04-01，commit `cdd39c6`，10 findings：Medium 4、Low 2、Info 1、Gas 3）做非循環驗證。撰寫 L17／L18 時尚未讀過此報告。

### L17 回歸驗證通過

part 2 的 **M-1「Streaming enforcers increase token spending even without actual token transfer」** 四個要素全中 L17：

```solidity
// ERC20StreamingEnforcer._validateAndConsumeAllowance
// @issue This line increases the spent amount BEFORE the actual transfer happens
allowance_.spent += transferAmount_;
```

前置鉤子記帳 ✓、取自 calldata 意圖值（`callData_[36:68]`）✓、`EXECTYPE_TRY` 失敗不回滾 ✓、反覆失敗執行耗盡額度 ✓。且發生在**不同的 enforcer 家族**（`ERC20StreamingEnforcer`／`NativeTokenStreamingEnforcer`，而非 part 1 的 TransferAmount 系列）。

這是 `logic_scan.md` 維護規則所要求的回歸驗證，且來源資料在情境撰寫時未被讀過，**非循環**。

### 一個對「情境庫 vs 逐檔人工審計」有利的觀察

MetaMask 在 part 1 修好了 TransferAmount enforcer 的這個缺陷（commit 已記於報告），但**同型 bug 在 Streaming enforcer 原封不動存在**，兩週後才由 part 2 抓到。逐檔人工審計會漏掉沒排進當次範圍的同型實例；而「對掃描範圍內每一份合約跑完全部情境」的系統性掃法，會一次抓到兩組。這正是 `logic_scan.md` 規則 3（不是「看到可疑才查」）存在的理由。

### part 2 仍未涵蓋的部分

| part 2 finding | 現有庫 |
|---|---|
| M-1 Streaming enforcer 額度耗盡 | ✅ **L17 命中** |
| M-2 API 與 swap payload 不一致可導致未授權轉帳 | 未涵蓋 |
| M-3 `SpecificActionERC20TransferBatchEnforcer` 可耗盡無限 gas | 部分（D-AA-05 的 griefing 主題，但非同一機制） |
| M-4 不相容 fee-on-transfer 代幣 | 未涵蓋（通用 DeFi 模式，非 AA 專屬） |
| L-1 匯入了有 bug 的 `erc7579-implementation` commit | 未涵蓋（相依套件版本，供應鏈類） |

10 筆命中 1 筆。比第一輪的 13 筆命中 0 有改善，但幅度有限——單一情境命中單一 finding，尚不足以宣稱這個領域已被有效涵蓋。

## 目前結論

- 「工具對 KMS 領域無效」在**第一輪的狀態下成立**，根因是領域知識未入庫、通用情境偏 DeFi 形狀。
- 補完 L17／L18 與 AA 領域檔後，在未讀過的 part 2 上取得 1 次非循環命中，證明**機制會累積、會泛化**，但覆蓋率仍低。
- 誠實的說法是：**方法可行，知識不足**。要讓這個領域達到可用水準，需要再跑 part 3／4／TotalBalanceEnforcer 並持續補條目，而非宣稱已解決。

## 可重現步驟

```bash
git clone https://github.com/MetaMask/delegation-framework.git && cd delegation-framework
git checkout d522a38b0b0f1c27d896790262302a52c3720e06
git submodule update --init --recursive --depth 1
python3 <kit>/scripts/cli.py check --src-prefix src/
python3 <kit>/scripts/cli.py scan --out-dir /tmp/bench-mm --src-prefix src/
```
