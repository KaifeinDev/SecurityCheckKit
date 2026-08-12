# 帳戶抽象／智能帳戶（ERC-4337、ERC-7702、委派授權）領域事故模式

last_reviewed: 2026-08-13

> 用法、條目模板與去識別化規則見 `README.md`。本檔涵蓋「誰能代表誰動用資產、授權如何授出與撤銷、
> 金鑰如何驗證與輪換」這一層的合約邏輯：ERC-4337 智能帳戶、EntryPoint 互動、paymaster、
> ERC-7702 委派、ERC-1271 簽章驗證、多簽與 passkey（P256/WebAuthn）帳戶、caveat/enforcer 式權限框架。
>
> **這個領域的共同特徵**：漏洞幾乎都不在「資金計算」而在「授權模型」。可程式化的驗證邏輯讓
> 「一個 bug 等同於洩漏私鑰」——這是本領域與 DeFi 類領域最大的差異，也是通用情境庫（偏資金流、
> 記帳、oracle）在此覆蓋率偏低的原因。

## 條目索引

| 編號 | 事故模式 |
|---|---|
| D-AA-01 | 執行入口缺少 EntryPoint 呼叫者驗證 |
| D-AA-02 | 簽章未涵蓋 gas 參數欄位 |
| D-AA-03 | 驗證階段寫入狀態，被同批次的其他 userOp 覆寫 |
| D-AA-04 | ERC-1271／自訂雜湊缺少 domain 綁定，可跨帳戶或跨鏈重放 |
| D-AA-05 | 依賴 revert 阻止付款，但付款已在驗證通過時發生 |
| D-AA-06 | ERC-7702 委派後的 initialize 可被搶跑 |
| D-AA-07 | 驗證階段違反 ERC-7562 範圍限制 |
| D-AA-08 | 重入防護的前提被帳戶抽象打破 |

---

## D-AA-01 執行入口缺少 EntryPoint 呼叫者驗證

- **描述**：智能帳戶的 `execute()`／`executeBatch()` 等執行入口若沒有驗證呼叫者，任何外部地址都能
  直接呼叫並以帳戶身分執行任意操作，完全繞過 `validateUserOp` 的簽章驗證。這是本領域最基本也最致命
  的一類，後果等同帳戶被完全接管。
- **來源**：[Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
- **標準查證問題**：
  1. 列出所有能造成外部呼叫或轉帳的函式，逐一確認呼叫者限制是什麼（`onlyEntryPoint`、
     `onlyEntryPointOrSelf`、owner）？
  2. 該 modifier 的**實作**是否真的比對 EntryPoint 位址並 revert，而不是只有名字看起來對？
  3. `entryPoint` 是 `immutable` 還是可被 setter 事後更換？可更換的話，此保護的有效期只到下次更換為止（見 L13）。
- **對照通用情境**：命中 L2（應保護而未保護的狀態變更）與 L1（權限檢查實作錯誤）。本條是這兩條在
  AA 領域的具體形；查證時仍走 L1／L2 的逐行確認流程。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-02 簽章未涵蓋 gas 參數欄位

- **描述**：只對 `callData` 做簽章驗證，而未把 `preVerificationGas`、`verificationGasLimit`、
  `callGasLimit`、`maxFeePerGas`、`maxPriorityFeePerGas` 綁進簽章雜湊。這些欄位未受簽章保護時，
  bundler 或搶跑者可在傳輸途中竄改；灌高 `preVerificationGas` 會直接放大帳戶需償付的金額，
  攻擊者反覆送出即可抽乾帳戶 ETH。
- **來源**：[Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
- **標準查證問題**：
  1. 逐欄位比對 `PackedUserOperation` 的**每一個**成員，哪些進了待簽雜湊、哪些沒有？
  2. 沒進雜湊的欄位，被第三方竄改後會影響什麼？特別追 gas 相關欄位與付款金額的關係。
  3. 專案是自行組裝雜湊，還是沿用 EntryPoint 的 `getUserOpHash`？自行組裝者需逐欄位核對。
- **對照通用情境**：命中 L18（簽章雜湊未涵蓋全部應綁定的上下文）。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-03 驗證階段寫入狀態，被同批次的其他 userOp 覆寫

- **描述**：EntryPoint 會先驗證整批 userOp、再依序執行。若 `validateUserOp()` 把資料寫進儲存
  供後續 `execute()` 使用，同一批次中第二筆 userOp 的驗證會覆寫第一筆寫入的值，導致執行時讀到
  錯誤參數（例如接上錯誤的簽章者），進而執行未授權的動作。
- **來源**：[Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
- **標準查證問題**：
  1. `validateUserOp()` 是否對儲存有任何寫入？寫入的變數被哪些函式在**執行階段**讀取？
  2. 若同一帳戶在同一批次有兩筆以上 userOp，這些變數的值會是誰寫的？
  3. 跨階段傳遞的資料能否改為放在 calldata 或以 userOp 雜湊為 key，而非共用單一槽位？
- **對照通用情境**：不在通用情境涵蓋範圍（驗證／執行兩階段語意分離）。通用情境庫預設「函式呼叫即
  完整執行」，抓不到「驗證全部做完才開始執行」造成的批次內互相覆寫。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-04 ERC-1271／自訂雜湊缺少 domain 綁定，可跨帳戶或跨鏈重放

- **描述**：以原始雜湊驗證簽章而未做 EIP-712 domain 分離，未綁定 `chainId` 與合約位址。只要
  兩個帳戶使用相同的簽署邏輯，對帳戶 A 在鏈 X 上核准的簽章即可對帳戶 B 或在鏈 Y 上重放。
  同型問題也發生在自行組裝的 userOp 雜湊未納入執行入口位址（EntryPoint）時。
- **來源**：
  - [Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
  - [ERC-4337 Vulnerability: How Malformed Calldata Can Break Account Abstraction — NioLabs](https://medium.com/@niolabsofficial/erc-4337-vulnerability-how-malformed-calldata-can-break-account-abstraction-01b28f689b2b)
- **標準查證問題**：
  1. 待簽雜湊是否綁定 `chainId`、`verifyingContract`（本帳戶位址）、nonce？
  2. 是否綁定了**所有可替換的執行入口**——EntryPoint、router、實作版本？官方更換 EntryPoint 後舊簽章是否仍有效？
  3. 同一份簽章拿到同一使用者的另一個帳戶實例上，會不會通過？（多實例部署的帳戶特別容易中）
- **對照通用情境**：命中 L18（簽章雜湊未涵蓋全部應綁定的上下文）。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-05 依賴 revert 阻止付款，但付款已在驗證通過時發生

- **描述**：`validateUserOp()` 一旦回傳成功，bundler 就會取得償付，與執行階段的成敗無關；
  paymaster 的 `postOp()` revert 也無法收回先前自共用資金池支出的款項。設計上若假設「執行失敗
  就不會付錢」，惡意 bundler 可反覆送出注定失敗的 userOp 抽取 gas 費，把共用 paymaster 池抽乾。
- **來源**：[Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
- **標準查證問題**：
  1. paymaster 的付款決策在哪一階段做成？該決策是否假設了執行階段的結果？
  2. `postOp()` 內的 revert 或狀態回滾，實際上能不能收回已支付的 gas？
  3. 共用資金池是否對單一使用者／單一時間窗設有支出上限，以限制反覆失敗造成的損耗？
- **對照通用情境**：命中 L17（記帳依「意圖」而非「實際結果」，且失敗不回滾）。方向相反但同源：
  L17 是額度被無效消耗，本條是款項被無效支出，兩者都源自「記帳／付款」與「實際結果」脫鉤。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-06 ERC-7702 委派後的 initialize 可被搶跑

- **描述**：EOA 透過 ERC-7702 委派到智能帳戶程式碼後，若 `initialize(owner)` 沒有呼叫者限制，
  攻擊者可在正牌擁有者送出初始化交易之前搶跑，把自己設成 owner，取得該帳戶的控制權。
- **來源**：[Six mistakes in ERC-4337 smart accounts — Security Boulevard](https://securityboulevard.com/2026/03/six-mistakes-in-erc-4337-smart-accounts/)
- **標準查證問題**：
  1. `initialize` 類函式有沒有呼叫者限制？是否綁定委派的 EOA 本身（`msg.sender == address(this)`）？
  2. 委派生效與初始化之間是否存在任何人都能插入的窗口？
  3. 若已被搶先初始化，正牌擁有者有沒有補救路徑（重新委派、reinitialize）？
- **對照通用情境**：命中 L7（可搶跑的初始化/認領）。本條是 L7 在 ERC-7702 情境的具體形。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-07 驗證階段違反 ERC-7562 範圍限制

- **描述**：ERC-7562 規定驗證階段禁用一組 opcode（`TIMESTAMP`、`SELFBALANCE`、`NUMBER` 等）
  並限制只能讀取 sender 自身的儲存，目的是讓 bundler 能安全維護 mempool、避免互相使 userOp 失效
  造成的 DoS。違反者的 userOp 會被公開 mempool 拒絕，帳戶在實務上無法使用；部分 Solidity 寫法
  會編譯出被禁的 opcode 而不自知。呼叫非 staked 合約亦受限。
- **來源**：
  - [ERC-7562: Account Abstraction Validation Scope Rules — ethereum/ERCs](https://eips.ethereum.org/EIPS/eip-7562)
  - [ERC-7562 — ERC-4337 Documentation](https://docs.erc4337.io/core-standards/erc-7562.html)
- **標準查證問題**：
  1. `validateUserOp()` 及其呼叫到的所有函式，是否讀取 `block.timestamp`／`block.number`／
     `address(this).balance`？（時間類 enforcer 特別容易踩到）
  2. 驗證路徑是否讀取 sender 以外地址的儲存，或呼叫未 staked 的外部合約？
  3. 有沒有對**編譯後 bytecode** 做過禁用 opcode 的靜態檢查，而不只是看原始碼？
- **對照通用情境**：不在通用情境涵蓋範圍（標準規範遵循）。這類問題不是邏輯寫錯，而是違反外部
  規範導致實務上不可用，逐行讀碼看不出來，必須先知道規範存在。
- **實戰命中摘要**：（尚無命中案例）

---

## D-AA-08 重入防護的前提被帳戶抽象打破

- **描述**：許多重入防護（含廣泛使用的 reentrancy guard）建立在「同一呼叫堆疊中不會有攻擊者控制
  的程式碼先於本函式執行」這個假設上。帳戶抽象讓帳戶自己的驗證與執行邏輯可任意編程，該假設不再
  成立，既有 DeFi 合約與智能帳戶互動時可能出現原設計未預期的重入路徑。EntryPoint v0.9 已加入
  緩解（`handleOps`／`handleAggregatedOps` 限最上層交易且由 EOA 發起）。
- **來源**：
  - [ERC-4337 & Account Abstraction: A Comprehensive Overview — Hacken](https://hacken.io/discover/erc-4337-account-abstraction/)
  - [Core Standards — ERC-4337 Documentation](https://docs.erc4337.io/core-standards/index.html)
- **標準查證問題**：
  1. 本專案的重入防護，是否假設了「沒有攻擊者程式碼會在更早的堆疊層執行」？
  2. 帳戶的 `validateUserOp`／`execute` 會呼叫哪些外部 DeFi 合約？那些合約的防護是否建立在上述假設上？
  3. 使用的 EntryPoint 版本為何？是否已含 v0.9 的最上層交易限制？
- **對照通用情境**：與 L13（信任地址假設可被推翻）同屬「前一輪安全判斷的前提失效」這一類，但
  觸發原因不同：L13 是位址可被替換，本條是執行模型本身改變了呼叫堆疊的假設。查證時兩條都要跑。
- **實戰命中摘要**：（尚無命中案例）
