# 工作底稿（內部）

本檔為交付報告的內部工作底稿，**不隨交付物提供給甲方**：內容包含全量逐筆分類、複核提醒與完整覆蓋矩陣，寫作語氣以內部溝通為準。

## 複核提醒

（無）

## 完整情境庫覆蓋矩陣

| 合約 | 已查證情境 | 不適用 | 命中 |
|---|---|---|---|
| `src/VulnerableVault.sol` | L1、L2、L3、L4、L5、L7、L9、L10、L11、L13、L14 | L6、L8、L12、L15、L16、L17、L18、L19 | VLV-20、VLV-21、VLV-22、VLV-23 |

## 全量逐筆分類

- **VLV-20｜onlyOwner modifier 的權限檢查恆為真** — src/VulnerableVault.sol:32-35｜severity Critical／impact —／已確認需修復（A）
  - 判斷依據：人工複核發現（VULNERABILITY_CATALOG.md V3，Slither 漏報）：權限檢查實作邏輯錯誤，屬語意層級問題，靜態分析無對應 detector，需修復。
- **VLV-21｜creditBonus() 完全沒有存取控制** — src/VulnerableVault.sol:103-107｜severity Critical／impact —／已確認需修復（A）
  - 判斷依據：人工複核發現（VULNERABILITY_CATALOG.md V6，Slither 漏報）：應受保護的函式完全缺少存取控制，工具無「此函式該保護而未保護」的判斷能力，需修復。
- **VLV-01｜weak-prng** — src/VulnerableVault.sol:90-100｜severity High／impact High／已確認需修復（A）
  - 判斷依據：真實漏洞（見 VULNERABILITY_CATALOG.md V5）：得獎者可被驗證者/礦工操縱，需修復，不可忽略。
- **VLV-02｜reentrancy-eth** — src/VulnerableVault.sol:48-56｜severity High／impact High／已確認需修復（A）
  - 判斷依據：真實漏洞（見 VULNERABILITY_CATALOG.md V1）：經典重入攻擊，可被惡意合約清空金庫，需修復，不可忽略。
- **VLV-03｜suicidal** — src/VulnerableVault.sol:85-87｜severity High／impact High／已確認需修復（A）
  - 判斷依據：真實漏洞（見 VULNERABILITY_CATALOG.md V2）：任何人皆可自毀合約，需修復，不可忽略。
- **VLV-04｜tx-origin** — src/VulnerableVault.sol:79-82｜severity Medium／impact Medium／已確認需修復（A）
  - 判斷依據：真實漏洞（見 VULNERABILITY_CATALOG.md V4）：可被釣魚合約繞過權限檢查，需修復，不可忽略。
- **VLV-05｜unchecked-lowlevel** — src/VulnerableVault.sol:117-121｜severity Medium／impact Medium／已確認需修復（A）
  - 判斷依據：真實漏洞（見 VULNERABILITY_CATALOG.md V7）：轉帳失敗會被靜默吞掉，帳務與實際資金不一致，需修復，不可忽略。
- **VLV-22｜swap() 無滑點保護與 deadline** — src/VulnerableVault.sol:125-130｜severity Medium／impact —／已確認需修復（A）
  - 判斷依據：人工複核發現（VULNERABILITY_CATALOG.md V8，Slither 漏報）：經濟層級攻擊面，純商業邏輯問題，需修復。
- **VLV-23｜paused 旗標未被任何函式檢查** — src/VulnerableVault.sol:20｜severity Medium／impact —／已確認需修復（A）
  - 判斷依據：人工複核發現（不在 VULNERABILITY_CATALOG.md 原始漏洞地圖中，為分類複核時的新發現）：業務邏輯缺陷，需修復並補進漏洞地圖。
- **VLV-08｜calls-loop** — src/VulnerableVault.sol:117-121｜severity Low／impact Low／已確認需修復（A）
  - 判斷依據：與 #5 同一根因（見 VULNERABILITY_CATALOG.md V7），同一批修復。
- **VLV-09｜reentrancy-benign** — src/VulnerableVault.sol:48-56｜severity Low／impact Low／已確認需修復（A）
  - 判斷依據：與 #2 同一根因（V1 的重複偵測），一併修復即可解決。
- **VLV-10｜reentrancy-events** — src/VulnerableVault.sol:90-100｜severity Low／impact Low／已確認需修復（A）
  - 判斷依據：pickWinner() 已因 #1（weak-prng）被判定為真實漏洞函式，此處事件順序問題一併留待修復時處理。
- **VLV-12｜reentrancy-events** — src/VulnerableVault.sol:48-56｜severity Low／impact Low／已確認需修復（A）
  - 判斷依據：與 #2 同一根因（V1 的重複偵測）。
- **VLV-06｜events-maths** — src/VulnerableVault.sol:110-114｜severity Low／impact Low／已知風險但可接受（B）
  - 判斷依據：只影響鏈下可觀測性，不影響資金安全；僅 onlyOwner 可呼叫，屬已知可接受風險，非本次測試刻意植入的漏洞項目。
- **VLV-07｜missing-zero-check** — src/VulnerableVault.sol:72｜severity Low／impact Low／待確認（D）
  - 判斷依據：涉及資金流向（轉帳目標地址），依規則歸類 D：雖非本次刻意植入的漏洞編號，但屬真實可改進項目，需人工確認是否修復。
- **VLV-11｜reentrancy-events** — src/VulnerableVault.sol:60-68｜severity Low／impact Low／誤報（C）
  - 判斷依據：已確認為誤報：safeWithdraw() 採用正確的 checks-effects-interactions 順序（balances 在外部呼叫前歸零），reentrancy-events 只檢查事件在外部呼叫之後才 emit，不代表狀態層級可被重入利用。此為本次測試刻意設計的『安全對照組』函式，用來驗證工具是否會誤判安全程式碼——結果：沒有被 reentrancy-eth/reentrancy-benign 誤判，僅這個最低權重的事件排序 detector 命中，判定為誤報。
- **VLV-13｜low-level-calls** — src/VulnerableVault.sol:48-56｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：純資訊性提示（單純標註有低階呼叫），不構成獨立風險判斷，實際風險已由 #2 追蹤。
- **VLV-14｜low-level-calls** — src/VulnerableVault.sol:90-100｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：同上，純資訊性提示，實際風險已由 #1 追蹤。
- **VLV-15｜low-level-calls** — src/VulnerableVault.sol:117-121｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：同上，純資訊性提示，實際風險已由 #5/#8 追蹤。
- **VLV-16｜low-level-calls** — src/VulnerableVault.sol:60-68｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：同上，純資訊性提示；safeWithdraw() 本身已確認安全（見 #11）。
- **VLV-17｜naming-convention** — src/VulnerableVault.sol:79｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：純命名風格建議，非安全問題。
- **VLV-18｜reentrancy-unlimited-gas** — src/VulnerableVault.sol:72-76｜severity Informational／impact Informational／誤報（C）
  - 判斷依據：純資訊性提示，onlyOwner 才能呼叫，非本次刻意植入的漏洞項目。
- **VLV-19｜immutable-states** — src/VulnerableVault.sol:15｜severity Informational／impact Optimization／誤報（C）
  - 判斷依據：純 gas 優化建議，非安全問題。
