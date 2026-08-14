# 工作底稿（內部）

本檔為交付報告的內部工作底稿，**不隨交付物提供給甲方**：內容包含全量逐筆分類、複核提醒與完整覆蓋矩陣，寫作語氣以內部溝通為準。

## 複核提醒

（無）

## 完整情境庫覆蓋矩陣

| 合約 | 已查證情境 | 不適用 | 命中 |
|---|---|---|---|
| `src/TimelockVault.sol` | L1、L2、L3、L9、L11、L12、L13、L14 | L4、L5、L6、L7、L8、L10、L15、L16、L17、L18、L19 | TLV-06 |

## 全量逐筆分類

- **TLV-01｜reentrancy-events** — src/TimelockVault.sol:46-57｜severity Low／impact Low／誤報（C）
  - 判斷依據：withdraw() 遵循 checks-effects-interactions：balances[msg.sender] 與 accruedFees 皆在外部呼叫前完成更新（L51-53），重入時餘額已歸零、require(amount > 0) 會擋下。工具指出的只是 Withdrawn 事件在外部呼叫之後才發出，僅影響鏈下索引器看到的事件順序，無資金風險。
- **TLV-02｜reentrancy-events** — src/TimelockVault.sol:66-74｜severity Low／impact Low／誤報（C）
  - 判斷依據：sweepFees() 同樣先把 accruedFees 歸零（L70）才做外部呼叫，且有 onlyOwner 保護（已檢查 modifier 實作：require(msg.sender == owner)，owner 為 immutable、建構時設定，邏輯有效）。工具指出的僅是 FeesSwept 事件順序問題，無資金風險。
- **TLV-03｜timestamp** — src/TimelockVault.sol:46-57｜severity Low／impact Low／已知風險但可接受（B）
  - 判斷依據：鎖倉判斷確實依賴 block.timestamp，出塊者可在共識容忍範圍內（秒級）微調時間戳，理論上能讓提款提早數秒解鎖。但 LOCK_PERIOD 為 7 天，秒級誤差對業務無實質影響，且合約內沒有以 timestamp 作為隨機性或計價來源的用法。評估為可接受風險，保留現狀。
- **TLV-06｜deposit() 每次加碼會重置整筆餘額的鎖倉期** — src/TimelockVault.sol:38-43｜severity Low／impact —／已知風險但可接受（B）
  - 判斷依據：與產品方確認過這是刻意設計（「任何異動重新起算定存期」），且已寫入使用者文件；技術上若要改為分批鎖倉需要 per-deposit 的紀錄結構，成本與收益不成比例。評估為可接受風險，於文件揭露。
- **TLV-04｜low-level-calls** — src/TimelockVault.sol:46-57｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：刻意選用 call{value:} 而非 transfer/send：後兩者的 2300 gas 上限在收款方是合約（多簽、智能錢包）時會失敗，call 是 Istanbul 之後的建議寫法。回傳值有 require(ok) 檢查，非未檢查的低階呼叫。
- **TLV-05｜low-level-calls** — src/TimelockVault.sol:66-74｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：同 #4：call{value:} 為建議寫法（國庫地址可能是多簽合約），回傳值有 require(ok) 檢查。
