本受檢對象為**迴歸測試夾具**，不是要交付的產品合約：`VulnerableVault` 刻意植入了 9+1 個已知漏洞，
用來驗證本工具的偵測與判級是否被改壞（完整解答見 `VULNERABILITY_CATALOG.md`）。此節的內容僅供版面驗證之用。

**合約職責**

| 合約 | 職責 |
|---|---|
| `VulnerableVault.sol` | 存提款、批次付款、依 oracle 報價兌換代幣、抽獎，以及數個管理入口 |

**資產與托管**

使用者存入的 ETH 停在 `VulnerableVault` 自身，以 `balances` 記帳；獎池另以 `rewardPool` 記錄。

**特權角色權限表**

| 角色 | 可呼叫 | 後果 |
|---|---|---|
| `owner` | `emergencyWithdraw`、`topUpRewardPool`、`batchPay`、`shutdown` | 可轉出合約內資產、可自毀合約 |
| （無保護） | `creditBonus`、`adminSetPaused` | 實際上任何人皆可呼叫——這正是本夾具植入的漏洞之一 |

**注意**：上表的 `owner` 保護在本夾具中是**失效的**（`onlyOwner` 的判斷式恆為真），詳見發現明細。
