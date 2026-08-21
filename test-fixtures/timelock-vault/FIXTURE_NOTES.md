# TimelockVault — 第二級（可交付）對照 fixture

`vulnerable-vault` 是「第四級（不通過）」的 ground truth；這個 fixture 是光譜另一端的對照組：
一份**本身寫得正確、但帶有典型「可接受風險」模式**的合約，完整走完 Step 1～4 後應判定
**第二級（可交付，但需揭露已知風險）**，`veros report` 的 exit code 為 **0**（閘門通過），
報告開頭**不得**出現「內部工作版本」浮水印。

兩個 fixture 合起來覆蓋交付閘門的兩側：改動判級邏輯後，vulnerable-vault 必須仍是第四級
（exit 4），本 fixture 必須仍是第二級（exit 0），任何一邊翻掉都代表判級規則被改壞了。

## 合約設計（刻意安排的發現組合）

`src/TimelockVault.sol`：7 天定存 ETH 金庫。與 VulnerableVault 相反，這裡的防護都是真的：

- `withdraw()`/`sweepFees()` 遵循 checks-effects-interactions，狀態先更新才做外部呼叫
- `onlyOwner` 的 require 邏輯有效（對照 VulnerableVault 的 `|| true` 後門）
- `sweepFees()` 有 zero-address 檢查（避開 `missing-zero-check`）
- `owner` 宣告為 `immutable`（避開 `immutable-states`）
- 無 tx.origin、無 selfdestruct、無鏈上隨機數

Slither 掃描（0.11.5）對未加抑制註解的版本產出 **5 筆發現，無 High/Medium**：

| # | check | impact | 分類 | 設計意圖 |
|---|---|---|---|---|
| 1 | reentrancy-events | Low | C | CEI 已保護，僅事件順序 —— 誤報 |
| 2 | reentrancy-events | Low | C | 同上（sweepFees） |
| 3 | timestamp | Low | **B** | 鎖倉判斷真的依賴 block.timestamp，秒級誤差 vs 7 天定存 —— 教科書級「可接受風險」 |
| 4 | low-level-calls | Informational | C | call{value:} 是建議寫法且有檢查回傳值 |
| 5 | low-level-calls | Informational | C | 同上 |

另有一筆人工複核發現 `M1`（分類 B）：`deposit()` 每次加碼會把整筆餘額的鎖倉期重置為
7 天 —— 屬 Slither 抓不到的業務邏輯行為，作為 manual_findings 參與判級（B 類）的測試樣本。

判級推導：無 High（不觸發第四級）→ 無 A/D/未分類（不觸發第三級）→ 存在 B（掃描 #3 + 人工 M1）
→ **第二級**。

## 與 vulnerable-vault 的另一個差異：before ≠ after

vulnerable-vault 的報告是「工具原始輸出 = 交付版掃描結果」的路徑（未做 Step 3，報告顯示
兩者相同的說明註記）；本 fixture 則實際執行了 Step 3 —— 五筆 B/C 發現都已在合約中加上
區塊式 `slither-disable-start/end` 註解（含 Dev Note），重掃後交付版掃描結果為 **0 筆**。
因此本 fixture 同時驗證：

1. 摘要統計的「工具原始輸出 5 → 交付版掃描結果 0」對照與逐筆理由揭露
2. 抑制註解語法對 Slither 0.11.5 實際生效
3. classification.json 的行號以 `results_before.json`（抑制前掃描）為準 ——
   加註解造成的行號位移不影響 Step 4 的逐筆核對

## 重新產生報告

```bash
cd test-fixtures/timelock-vault
veros report \
  --before security-scan-report/results_before.json \
  --classification security-scan-report/classification.json \
  --env security-scan-report/scan_env.json \
  --scope security-scan-report/scope.json \
  --overview audit/overview.md \
  --client "（測試夾具）" \
  --engagement-from 2026-08-14 --engagement-to 2026-08-14 \
  --worksheet audit/worksheet.md \
  --out-dir security-scan-report
# 預期：資安等級第二級、exit code 0、report.md 開頭無「內部工作版本」浮水印
```

`src/TimelockVault.sol.original`（無 slither-disable 註解的最原始版本）與
`src/TimelockVault.sol`（Step 3 加上抑制註解後、實際交付的版本）兩份都保留在 repo 裡，
方便直接比對兩個階段的差異。若要從頭重掃：把 `TimelockVault.sol.original` 換成
`TimelockVault.sol` 跑 `veros scan` 得到 before/skeleton，再換回加了註解的版本重掃產
after —— 順序反了會讓 before 變成 0 筆。

**關於抑制註解**：本樣本保留 `src/TimelockVault.sol.original`（加註解前）與 `src/TimelockVault.sol`（加註解後）兩份，是抑制註解的唯一範例。2026-08 起這個動作已不是編號步驟，改為選配的 CI 衛生收尾（見 `SKILL.md` 最後一節）；報告也不再呈現加註解前後的數量對照。
