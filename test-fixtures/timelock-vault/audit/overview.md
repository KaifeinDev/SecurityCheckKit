本受檢對象為**迴歸測試夾具**，不是要交付的產品合約：`TimelockVault` 是為驗證本工具判級邏輯而刻意設計的
最小化定存型金庫，預期結果事先寫死（見 `FIXTURE_NOTES.md`）。此節的內容僅供版面驗證之用。

**合約職責**

| 合約 | 職責 |
|---|---|
| `TimelockVault.sol` | 接受 ETH 存入並鎖倉 7 天；到期後可提領，提領時收取手續費並累計於合約內 |

**資產與托管**

使用者存入的 ETH 全部停在 `TimelockVault` 自身；`balances` 記錄各地址可提領餘額，`accruedFees` 記錄
尚未被提走的手續費。

**特權角色權限表**

| 角色 | 可呼叫 | 後果 |
|---|---|---|
| `owner`（建構時設定，`immutable`） | `sweepFees(address to)` | 把 `accruedFees` 全額轉往指定地址。不能動使用者的 `balances`。 |
