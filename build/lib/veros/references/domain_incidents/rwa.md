# RWA（實體資產代幣化）領域事故模式

last_reviewed: 2026-08-12

> 用法、條目模板與去識別化規則見 `README.md`。本檔只放通用的領域知識，不記錄任何個別客戶
> 專案的可識別資訊。

## 條目索引

| 編號 | 事故模式 |
|---|---|
| D-RWA-01 | 觸發 mint/burn 的鏈下流程本身無法被合約驗證 |
| D-RWA-02 | 升級／托管權限集中於單一私鑰，入侵後可繞過全部鏈上邏輯 |
| D-RWA-03 | 單一來源、無邊界的價格 Oracle |
| D-RWA-04 | 未認證的資產贖回 |
| D-RWA-05 | 缺少儲備證明（Proof of Reserves）機制 |

---

## D-RWA-01 觸發 mint/burn 的鏈下流程本身無法被合約驗證

- **描述**：RWA 領域最根本的結構性風險——鏈上程式碼完全正確，不代表系統安全。決定何時
  mint/burn 的關鍵事件（實體交割確認、KYC 核准）發生在鏈下，合約只能被動信任一次鏈上呼叫。
  審計能抓出 mint/burn 函式的邏輯錯誤，但抓不出觸發它的鏈下流程是否可信。
- **來源**：[Designing Proof of Reserves for Tokenized Gold — CertiK](https://www.certik.com/blog/designing-proof-of-reserves-for-tokenized-gold)
- **標準查證問題**：
  1. 哪些函式的呼叫代表「現實世界已經發生某件事」？這些函式各由誰有權呼叫？
  2. 這些函式之後，是否還存在能撤銷／推翻該既成事實的函式？撤銷的 status 前置檢查卡在轉換
     之前還是之後？
  3. 若鏈下流程被誤操作或被入侵，合約有沒有任何機制能察覺不一致？
- **對照通用情境**：命中 L12（鏈上可逆狀態與現實不可逆事實矛盾）。本條可視為 L12 在 RWA 領域
  的動機說明，實際查證仍走 L12 的狀態機圖流程。
- **實戰命中摘要**：某代幣化實體資產專案，在合約確認現實交付完成之後，仍存在一個撤銷類函式可
  退還托管資產，且其狀態檢查允許在「已交付」狀態下執行。鏈上退款與現實中已無法收回的實體交付
  並存，同一份價值可能被兌現兩次。此問題單看該函式本身（含其存取控制）看不出來，是攤開狀態機
  圖比較多個函式的效果後才浮現。（命中日期：2026-08）

---

## D-RWA-02 升級／托管權限集中於單一私鑰，入侵後可繞過全部鏈上邏輯

- **描述**：可升級合約的升級權限若由單一 EOA 持有，攻擊者取得該私鑰即可替換 implementation，
  使所有鏈上邏輯與存取控制同時失效。2025 年 RWA 領域最大宗事故即為此模式：攻擊者取得 deployer
  錢包私鑰，對 proxy 呼叫 `upgradeToAndCall` 換掉正版 implementation，損失約 850 萬美元；根因
  是單一金鑰控制升級權限，無多簽、無 timelock、無第二人核准。
- **來源**：
  - [RWA protocol exploits reach $14.6M in H1 2025, surpassing 2024 — Cointelegraph](https://cointelegraph.com/news/rwa-protocol-exploits-14-6m-in-h1-2025-surpassing-2024)
  - [RWA Security Risks & Practices: Securing Tokenized Assets — QuillAudits](https://www.quillaudits.com/blog/rwa/rwa-security-risks-and-practices)
- **標準查證問題**：
  1. 合約是否可升級（UUPS／Transparent Proxy）？升級授權函式由誰控制？
  2. 該控制者是 EOA 還是多簽？有無 timelock 或第二人核准？
  3. 除了升級權限，是否還有其他單點權限（暫停、鑄造、提領托管資產）落在同一個地址上？
- **對照通用情境**：不在 L1-L15 涵蓋範圍（權限集中／營運風險）。L1 查的是存取控制**實作錯誤**，
  本條的存取控制實作通常完全正確，問題在於權力邊界本身過大。
- **實戰命中摘要**：某貴金屬托管代幣專案採用可升級代理架構，升級權限由單一 owner 位址持有，
  未使用多簽，亦無 timelock 或第二人核准。此配置下 owner 私鑰一旦外洩，攻擊者可替換
  implementation 並繞過所有既有的存取控制與業務邏輯。（命中日期：2026-08）

---

## D-RWA-03 單一來源、無邊界的價格 Oracle

- **描述**：以單一餵價來源決定資產計價，且對寫入的價格數值不設上下限時，不論是私鑰外洩或
  單純的操作失誤（手滑、進位算錯），錯誤價格都會立即生效並持續累積後果，直到治理機制介入。
  2026 年 2 月一起 RWA 協議的 oracle 設定錯誤使資產價格偏離達 99.95%，清算持續了五天才被
  治理機制修正。
- **來源**：[Designing Proof of Reserves for Tokenized Gold — CertiK](https://www.certik.com/blog/designing-proof-of-reserves-for-tokenized-gold)
- **標準查證問題**：
  1. 價格從哪裡來？單一來源還是多來源？有無 TWAP 或偏離度檢查？
  2. 餵價函式對數值本身有沒有上下限檢查？上下限是否**雙側**都設了（見 L11）？
  3. 價格更新有無時效性檢查（stale price）？過期價格會被拒絕還是照用？
- **對照通用情境**：命中 L5（價格/匯率來源可操縱）與 L11（特權參數僅單側設界）。
- **實戰命中摘要**：某托管代幣專案的報價提交函式對價格數值未設任何上下限，餵價角色的操作失誤
  或私鑰遭竊即可寫入極端價格，且合約不會阻擋。此類缺口的後果會持續累積到有人發現並以治理手段
  介入為止。（命中日期：2026-08）

---

## D-RWA-04 未認證的資產贖回

- **描述**：部分 RWA 實作允許任何帳戶觸發合約控制資產的贖回／提領，屬已知的關鍵漏洞類別。
- **來源**：[RWA Tokenization Security Risks and How to Mitigate Them — Codezeros](https://www.codezeros.com/common-security-risks-in-rwa-tokenization-and-how-to-mitigate-them)
- **標準查證問題**：
  1. 贖回／提領類函式的呼叫者限制是什麼？是否綁定申請人自己的簽章或授權？
  2. 若使用簽章授權（如 Permit2 witness），witness 是否確實綁定申請人身分與該筆申請內容？
  3. 贖回的受款地址是呼叫者本身，還是可任意指定的參數？
- **對照通用情境**：命中 L8（未授權轉帳）與 L2（應保護而未保護的狀態變更）。
- **實戰命中摘要**：（尚無命中案例）

---

## D-RWA-05 缺少儲備證明（Proof of Reserves）機制

- **描述**：代幣供給端若沒有任何機制可讓外部獨立驗證「流通代幣總量對應的實體儲備是否足額」，
  則發行方營運安全一旦失守，代幣可在沒有對應實體資產買入的情況下被鑄造，稀釋所有既有持有人。
  失配也可能來自 mint/burn 邏輯的 bug、未反映到鏈上的鏈下儲備異動、或造假的儲備證明。這類
  缺口的特徵是「**沒有寫的機制**」而非「寫錯的邏輯」，逐行讀碼看不出來，必須先知道這個領域
  通常應該要有什麼才查得到。
- **來源**：
  - [Designing Proof of Reserves for Tokenized Gold — CertiK](https://www.certik.com/blog/designing-proof-of-reserves-for-tokenized-gold)
  - [Secure Mint Explained: How Chainlink Proof of Reserve Enhances the Security of Stablecoins, Tokenized Assets, and Wrapped Tokens — Chainlink](https://blog.chain.link/secure-mint/)
- **標準查證問題**：
  1. 除了標準的 `totalSupply()`，合約有沒有任何 attestation 函式或鏈下儲備報告的串接點？
  2. 代幣持有人以外的第三方（監管單位、合作機構）能否獨立驗證儲備充足？
  3. 有沒有事件記錄稽核時點，讓「代幣與儲備何時對不上」可以事後追溯？
  4. 若儲備已經對不上，系統要到什麼時候才會現形？是否只有在贖回擠兌時才會被發現？
- **對照通用情境**：不在 L1-L15 涵蓋範圍（機制缺失類）。這是本庫存在價值的典型案例——純靠
  L1-L15 逐條比對或逐行讀碼都不會發現，只有領域先驗知識查得到。
- **實戰命中摘要**：某實體貴金屬托管代幣專案具備標準的總量查詢函式，但沒有任何機制可讓外部
  獨立驗證流通代幣量是否對應托管方實際持有的實體儲備：無 attestation 函式、未串接任何鏈下
  儲備報告機制、無稽核時點的事件記錄。結果是系統無法提早發現「流通代幣與實體儲備已經對不上」，
  只能等到贖回擠兌時才現形。此發現是該次審計中，前面所有讀碼步驟與通用情境庫都未曾觸及的
  全新缺口。（命中日期：2026-08）
