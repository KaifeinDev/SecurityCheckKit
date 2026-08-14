# 交付報告改版設計

**日期**：2026-08-14
**背景**：以 `bot-gold-token/security-scan-report/report.pdf`（本工具產出，35 頁）與 HashCloak 為 Dyson Finance 出的第三方審計報告（`Dyson Finance Audit Report_2023.pdf`，12 頁）逐頁比對後，重新設計交付報告的版面、欄位與嚴重度模型。

## 設計前提：落差在文件工程，不在審計深度

比對的第一個結論是反直覺的，但它決定了改版方向——**不要照抄外部報告的目錄，因為會一起抄進它的缺點。**

Dyson 那份報告的 findings 品質低於我們：

- DF-3「owner 私鑰可能外洩」是所有具 owner 的合約都成立的通則，無任何專案特定查證。
- DF-6「註解不一致」、DF-8「應使用 immutable 省 gas」是靜態工具直接可報的項目。
- DF-7 建議**移除 zero address 檢查**（理由是「前端可能已驗過」），這是錯誤建議。
- 唯一的 Medium（DF-1）是一個 divide-by-zero。

而 bot-gold-token 那份的 M1（部署腳本會把不驗簽的 MockPermit2 接進正式合約，等同繞過整個 Permit2 授權模型）、M2（pause 未覆蓋四條會動資金的路徑）、M3（報價寬限期內兩筆報價同時有效可選擇性套利），每一條的深度都超過 Dyson 全部 8 條，且都附逐行查證與行號。

**因此本次改版全部是版面、欄位與呈現的重構，不涉及審計方法。** 唯一新增的內容產出是「協定理解摘要」與「特權角色權限表」，而這兩者的原始素材（`AUDIT_NOTES.md`）現行流程已經強制產出，只是從未進報告。

## 現況的量化問題

| 指標 | 現況 | Dyson |
|---|---|---|
| 總頁數 | 35 | 12 |
| B/C/D 明細佔頁 | **27 頁（77%）** | 0 |
| 可讀可決策內容 | 6 頁 | 11 頁 |
| findings 數 | 110 + 3 | 8 |
| 範圍檔案清單 | **無** | 逐一列出 15 檔 |
| 協定理解／架構 | **無** | 2 頁（含架構圖） |
| Methodology | 3 條 bullet，其中 2 條是免責聲明 | 6 個編號步驟 |
| 每筆 finding 是否有修復建議 | **無 Suggestion 欄位** | 每筆都有 |

三個具體缺陷：

1. **「High 有幾筆」在同一份報告裡有三個互相矛盾的答案**：摘要統計寫 15、摘要結論寫 7（非誤報的）、待決策總表寫 3（A 類的）。
2. **76 筆共用 6 段理由**（第 8 章自行揭露：6+30+11+16+6+7）。27 頁明細的 69% 是同一段話被複製數十次。
3. **內部 QA 工件外洩到交付文件**：第 8 章正文寫著「請針對每一組，抽查至少一筆」，這是給複核者的指令，出現在要給甲方的 PDF 裡。

### C 類不能全砍的理由

按「分類 × 嚴重度」重新統計 110 筆後：

| | High | Medium | Low | Info | Opt |
|---|---|---|---|---|---|
| A | 3 | 1 | 0 | 0 | 0 |
| B | 4 | 6 | 33 | 23 | 0 |
| C | **8** | 4 | 16 | 11 | 1 |

**8 筆 High 被判為誤報，佔全部 High 的 53%。** 依 `severity_grading.md`，判 C 是 High 唯一的脫身路徑，這 8 筆是整份報告權重最高、最該被外部檢視的判斷。查 `results_before.json` 的 confidence 欄位後確認：這 8 筆中 7 筆是 Slither **High confidence**，無任何一筆是 Low confidence——判定確實是人讀出來的，不是抄工具的第二欄。

但其中 6 筆（`uninitialized-state`）共用同一段複製貼上的 `dev_note`，且被放在第 24 頁，字級與 `unindexed-event-address` 相同。

結論：**切線不畫在「C 要不要留」，畫在嚴重度上。**

## 決定一：按讀者拆成兩份文件

原先考慮的切線是「開發期內部文件 vs 修訂後產出報告」，否決——那是時間軸，而問題是讀者。修訂完成前甲方一樣可能要看進度，修訂完成後我們一樣需要工作底稿。

| | **交付報告** | **工作底稿** |
|---|---|---|
| 檔案 | `security-scan-report/report.pdf`（+ `report.md`） | `audit/worksheet.md` + `audit/classification.json` |
| 格式 | 排版 PDF，約 10–12 頁 | Markdown / JSON，**不轉 PDF** |
| 讀者 | 甲方 | 我方複核者、下次重掃的人 |
| git | 隨交付物 | **gitignore**（與 `AUDIT_NOTES.md`、`DOMAIN_RESEARCH.md` 同層同待遇） |

工作底稿必須 gitignore：它含內部語氣的句子（現行第 8 章就印著「先前誤稱全部限 operator」「可信重新分類為 B」），放在客戶專案 repo 內會隨程式碼被 clone。

## 決定二：交付報告版面骨架

章節標題**不編號**，以大標題與強制分頁切分（比照 Dyson）。findings **必須**編號，見決定六。

| # | 章節 | 內容 | 來源 |
|---|---|---|---|
| — | 封面 | 客戶名、報告標題、交付日期、engagement 期間（起訖，非瞬間 timestamp）、執行單位。**不放具名簽名欄位**（見決定七） | 新增，需參數 |
| — | 目錄 | 含每一筆 finding 的標題（比照 Dyson TOC） | 自動生成 |
| 1 | 摘要 | 專案一句話定位、engagement 期間、repo + commit、severity 計數表（業界五級）、findings 總數 | 改寫 |
| 2 | 掃描範圍 | **納入檔案清單（含行數）＋ 排除清單與逐條理由**；檔案 hash 以小字放章節末尾 | 新增 |
| 3 | 協定理解摘要 | Overview 式：系統在做什麼、合約逐一職責、**特權角色權限表** | 新增，取自 `AUDIT_NOTES.md` |
| 4 | 檢測方法 | Dyson 式編號步驟，明寫 Slither + L1–L19 情境庫 + 領域事故庫；範圍限制聲明移到本章末尾 | 改寫 |
| 5 | 情境庫覆蓋 | **壓縮版覆蓋矩陣**（合約 × 命中數，不展開 19 欄）。完整矩陣留工作底稿 | 新增 |
| 6 | 待處理項目總表 | 需決策／行動的項目，統一編號、Severity × Status | 改寫 |
| 7 | Findings | A 類 + 全部人工發現 + **High/Medium 的 B 與 C**，每筆固定三段：說明 / 影響 / **建議** | 改寫 |
| 8 | 已評估項目摘要 | Low/Info 的 B 與 C，**一頁 detector 摘要表**（detector × 筆數 × 分類 × 一句理由） | 新增（取代 27 頁明細） |
| — | 附錄 | 發現處置分類定義（Severity × Status）。**整案等級定義整段移除** | 縮編 |

移除的章節：

- **「工具原始輸出 vs 交付版掃描結果」對照表**與其長條圖。報告只呈現當次掃描的當前結果。（bot-gold-token 那張圖畫了兩根等高的柱子，佔掉整整一頁。）
- **「複核提醒：重複使用的判斷理由」**——移出交付報告，改由 `cli.py review` 在 Step 2 產出（見決定八）。
- **「完整分類明細」27 頁**——High/Medium 的部分升入 Findings，Low/Info 的部分降為一頁摘要表，全量留工作底稿。
- **附錄一「待人工確認清單」**——D 類項目併入待處理項目總表，不另立附錄。

### 決定二的推導：篇幅不生產信任

保留 27 頁明細的原始理由是「若甲方用別的工具掃出相同輸出，要證明我們已經知道」。這個顧慮成立，但選錯了載體：

- **別的工具不會有相同輸出。** Mythril / Aderyn / 4naly3er 的 finding 切分、命名、行號歸屬與 Slither 完全不同，這 27 頁對不上任何一份。唯一能對帳的對象是同版本同參數的 Slither。
- **真正的證明載體是原始碼裡的 `// Dev Note:`**，甲方 `grep -r "slither-disable"` 一秒看完，理由就在出問題的那一行旁邊。
- **反效果**：27 頁「我們認為沒問題」的清單，等於製造 106 個可被質疑的判斷點。篇幅生產攻擊面，不生產信任。

## 決定三：嚴重度模型改為三個正交欄位

現行有四套並行尺規（Slither impact / manual findings 的 Critical–Info / Tier 1–4 整案等級 / A–D 分類），甲方要同時記住「第四級」「High」「A 類」三套詞彙。

改為：

| 欄位 | 值域 | 誰決定 | 用途 |
|---|---|---|---|
| `impact` | Slither 原生（High/Medium/Low/Informational/Optimization） | **工具，唯讀** | 稽核軌跡、**交付閘門的計算依據** |
| `severity` | Critical / High / Medium / Low / Informational | 人工，必填 | 報告呈現 |
| `status` | 需修復 / 已接受風險 / 已修復 / 待確認 | 人工 | 處置進度 |

三個關鍵約束：

1. **`impact` 維持唯讀**，`build_report.py` 現行的「classification 的 impact 必須逐字等於掃描輸出，不符 exit 2」驗證**不拆**。新增 `severity` 而非覆寫 `impact`，人工降級因此變成可見資訊，不是看不見的覆寫。
2. **交付閘門算在 `impact` 上，不算在 `severity` 上。** 這讓判斷與關卡互不汙染：人工判斷再寬鬆，都不會讓一個 Slither High 悄悄消失。若閘門改算 `severity`，繞過閘門的成本就從「修好程式碼」降為「寫一段理由」，而想讓報告過關的人跟判定嚴重度的人是同一個人。
3. **報告並列印出兩欄**，甲方直接看得到「工具說 High、我方判 Medium」的落差。這使得原先考慮的降級管制機制（幅度限制、第二人複核、強制引用緩解措施行號）暫時不需要——曝光本身就是控制。若日後發現降級被濫用，再回頭加。

**A/B/C/D 的定位釐清**：它不是嚴重度尺規，是**處置決定**（業界對應 Status：Fixed / Acknowledged / Won't fix）。而在這個模型下 **C 類從 findings 列表消失**——誤報不是「嚴重度很低的發現」，是**不成立的發現**。Dyson 報告裡沒有 C 類，不是因為 Slither 沒噴誤報給他們，是因為誤報不會被寫成 finding。C 類保留在工作底稿與決定二的第 8 章摘要表，不進 Findings 章。

## 決定四：整案等級從報告移除，浮水印保留

業界審計報告**沒有「整案等級」這個東西**。Dyson 那份沒有 Tier、沒有 Pass/Fail、沒有總評，只有一張 severity 計數表，讓讀者自己判斷。

因此：

- **報告本文**：只有 severity 計數表。Tier 1–4 那句話、附錄二整案等級的定義段落，全部移除。
- **`cli.py report` 的 exit code**：維持不變（`0`/`3`/`4`/`2`），續作 CI 與交付 checklist 的內部閘門，**不印在報告上**。
- **「【內部工作版本 — 不可作為交付文件】」浮水印：留下。** 它不是評級，是**處理標示**，防的是有人把未修完的草稿直接寄給甲方——整份報告防呆價值最高的元件。與「報告不談整案等級」不衝突：報告不告訴甲方我們內部怎麼分級，但這份草稿本身不該流出去。

`references/severity_grading.md` 需相應改寫：整案等級從「報告最前面的結論」降格為「僅驅動 exit code 與浮水印的內部閘門」。

## 決定五：Step 3（抑制註解）移出編號流程

推導：**專業審計公司不會在客戶程式碼裡加 `slither-disable` 註解**——他們不動客戶的碼，交付物只有報告。工具輸出是內部輸入源之一，與人工讀碼、客戶訪談並列（Dyson 的 Methodology 第 5 步即如此），誤報在內部就被丟掉，不進交付物。

（此推論來自「審計方是外部方、不改客戶碼」的結構，尚未以多份公開報告實證。若要驗證，抓 Trail of Bits / OpenZeppelin / Cyfrin 的公開報告確認有無反例。）

但這推出一個對本工具更重要的結論：**抑制註解不是審計實務，是開發團隊的 CI 衛生實務。** 本工具定位在開發團隊那一側（交付前自我檢查），所以加抑制註解是合理的——只是它跟報告無關。它的價值是「下次跑 CI 時那 106 筆不會淹沒新問題」，而這個價值只在「我們持續擁有並維護這份程式碼」時成立。外部回測標的（MetaMask、Matrixdock）永遠不成立，那些案子跳過它是正確的，不是偷懶。

因此：

- Step 3 從編號流程移出，改為**可選的收尾動作**，定位寫成「降低後續 CI 雜訊」，與報告脫鉤。
- `SKILL.md` 四步變三步；`README.md` 流程對照表同步修改。
- 報告永遠只呈現當次掃描的當前結果（與決定二移除 before/after 對照一致）。

## 決定六：findings 統一編號

現行兩套編號並存（掃描發現 `#4`/`#23`，人工發現 `M1`/`M2`），第 2 章卻把它們混在同一張表按嚴重度排序，讀起來像兩個系統打架。

改為**單一序列、單一前綴**：`<專案縮寫>-01`、`-02`……（如 `BGT-01`），比照 Dyson 的 `DF-1`~`DF-8`。

- 來源（工具／人工）降級為一個欄位，不進編號。
- 原掃描 id 收進 `scan_id` 欄位供重掃比對，**不印在報告上**。

## 決定七：不放具名簽名欄位

原本規劃在封面加「執行者／複核者」具名欄位（比照 Dyson 的 Prepared by）。**否決。**

理由：改版後交付報告的內容幾乎全部是 LLM 產生的散文——協定理解摘要、特權角色權限表、每筆 remediation、每筆 severity 降級理由。改版前那 35 頁大部分是 Slither 原文的機械轉貼，錯了是工具的錯；改版後不是。而確認後**不會有人逐頁讀過再簽名**。

**放一個假的問責機制，比沒有問責機制更糟。** 封面只留客戶名、日期、執行單位。

## 決定八：撤回「不需 Claude 也能走完流程」的承諾，CLI 維持為確定性層

`README.md` 現行承諾「不用 Claude Code 的同仁照 `SKILL.md` 手動填 `classification.json`，一樣能走完整個流程」。經確認**目前沒有這樣的使用者，短期內也不會有**，且這個承諾實際上是假的：Step 2 要求對每份合約跑完 L1–L19、做領域事故比對、產出資產托管圖與特權角色表、逐筆寫出引用行號的理由（本案 110 筆）——沒有 LLM 的人只會全部填 D 或全部填 C。

但**不把整套包成 skill**，兩件事必須是確定性的、不能有 LLM 在迴路裡：

1. **閘門**：`cli.py report` 的 exit code 要接進 CI 與交付 checklist。skill 需要一個人和一個對話，當不了 CI 閘門。
2. **可重現性**：報告向甲方承諾「相同工具版本可重現」。掃描與報告產生必須同輸入同輸出。

需要判斷力的只有 Step 2 的分類本身。因此現行兩層架構是對的，錯的只是 `README.md` 對第二層的承諾寫太滿——改寫成「Step 2 需要 LLM 輔助；Step 1/4 是純確定性 CLI，可獨立於 Claude 執行並接入 CI」。

**新增 `cli.py review` 子指令**：讀 `classification.json`，機械性檢查並輸出待抽查清單——

- 多筆共用完全相同的 `dev_note`（現行第 8 章的功能，時機從「報告產出後」提前到「Step 2 結束、給人確認的那一刻」）
- `dev_note` 過短
- A 類缺 `remediation`、D 類缺三格
- `severity` 相對 `impact` 降級但未附 `severity_rationale`

這些全是規則式判定，不需要判斷力——正是不該交給 LLM 的部分（LLM 會忘記檢查，正規表示式不會）。

## `classification.json` schema 變更

```jsonc
{
  "findings": [
    {
      "id": "BGT-01",              // 新增：統一編號
      "scan_id": 4,                // 新增：原掃描 id，不印出
      "source": "tool",            // 新增：tool | manual
      "check": "unchecked-transfer",
      "impact": "High",            // 維持唯讀，恆等於掃描輸出，閘門依據
      "severity": "Medium",        // 新增：業界五級，人工必填，報告呈現
      "severity_rationale": "...", // 新增：降級時必填
      "file": "contracts/GoldMarket.sol",
      "lines": [123],
      "description": "...",
      "category": "A",
      "status": "待處理",
      "dev_note": "...",
      "remediation": "...",        // 新增：A 類必填
      "confirm_what": "...",       // 新增：D 類必填三格
      "confirm_who": "...",
      "confirm_branches": "..."
    }
  ],
  "manual_findings": [ /* 同一 schema，source: "manual"，併入同一編號序列 */ ]
}
```

`manual_findings[]` 與 `findings[]` 的欄位收斂為同一 schema（差異只在 `source` 與有無 `scan_id`），因為報告端已不再區分兩者的呈現方式。

## 影響檔案

| 檔案 | 變更 |
|---|---|
| `scripts/build_report.py` | 主要工作量：章節骨架重寫、severity 模型、統一編號、範圍章節、覆蓋矩陣、detector 摘要表、移除 before/after 與整案等級 |
| `scripts/md_to_pdf.py` | 封面、目錄、章節強制分頁 |
| `scripts/scan.py` | 產出範圍檔案清單（含行數與 hash）、skeleton 加新欄位 |
| `scripts/cli.py` | 新增 `review` 子指令 |
| `scripts/report.py` | 新增 `--client` / `--engagement-from` / `--engagement-to` 等封面參數；工作底稿輸出路徑 |
| `references/severity_grading.md` | 整案等級降格為內部閘門；impact/severity/status 三欄位模型 |
| `SKILL.md` | 四步變三步；Step 2 新增欄位要求；協定理解摘要與特權角色權限表的產出要求 |
| `README.md` | 撤回非 Claude 承諾；流程表；兩份文件的產出說明 |
| `test-fixtures/*/security-scan-report/` | 兩組 fixture 報告需重新產生 |

## 不在本次範圍

- **降級管制機制**（幅度限制、第二人複核、強制引用緩解措施行號）：暫不實作，靠「閘門算 impact + 兩欄並列曝光」擋住。若日後發現降級被濫用再加。
- **Slither confidence 欄位的運用**：本次確認 confidence 與人工判斷無明顯相關（8 筆 High 判誤報中 7 筆是 High confidence），暫不納入判級或呈現。
- **多引擎**（Aderyn / Mythril / `slither-check-upgradeability`）、**動態測試訊號**（forge coverage / invariant）、**依賴 advisory 比對**、**diff 模式**、**SARIF 輸出**、**領域事故庫擴充**：屬審計能力層，與本次文件工程改版正交，另案處理。

## 遺留待辦（模板改版不會解決）

**bot-gold-token 的 6 筆 `uninitialized-state`**（High impact / High confidence / 判 C / 共用同一段複製貼上的 `dev_note`）必須有人逐筆重新讀過、寫出各自的理由，那份報告才可能交付。

新模板會把這 6 筆從第 24 頁搬到 Findings 章前段、單獨成節、用大字級呈現——**只會讓問題更醒目，不會讓它消失**。記在此處，避免改完模板後產生「已經處理好了」的錯覺。
