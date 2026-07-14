# SecurityCheckKit

在交付前，使用此工具做靜態分析並生成簡易自檢報告，確保交付的品質穩定性。

此工具拆成兩層設計：

1. **第一層：語言/工具無關的 CLI**（`scripts/cli.py`）—— 環境健檢、跑掃描、產報告，純 Python + 標準 Cli。
2. **第二層：人工確認的分類與加註解流程**（`SKILL.md`）—— 「這個發現算不算數」需要工程判斷，刻意設計成必須有人確認才能繼續，不管有沒有 Claude Code 輔助都一樣。目前這層是透過 Claude Code 的 skill 對話完成；不用 Claude Code 的同仁可以照 `SKILL.md` 的分類標準手動填 `classification.json`，一樣能走完整個流程。

## 架構

```
SecurityCheckKit/
├── README.md              
├── SKILL.md                ← Claude Code skill：把 CLI + AI 分類/加註解串成完整流程
├── references/
│   ├── pitfalls.md         ← 一些開發時遇過的問題（foundry.toml 陷阱、OZ 版本判斷、
│   │                          slither-disable-next-line 失效、PDF 中文字型）
│   ├── severity_grading.md ← 資安等級（第一～四級）判定標準與交付閘門行為（草稿）
│   └── logic_scan.md       ← GPT-Scan 式邏輯漏洞情境庫（L1～L10），補 Slither 抓不到的
│                              業務邏輯層級漏洞，Step 2 必跑
├── scripts/
│   ├── cli.py              ← 統一入口：check / scan / report 三個子指令
│   ├── env_check.py        ← Step 0：環境健檢（cli.py check 的實作）
│   ├── scan.py             ← Step 1：跑 slither + 過濾 + 蒐集環境資訊 + 產分類 skeleton
│   │                          （cli.py scan 的實作；--prev-classification 沿用上次分類）
│   ├── filter_results.py   ← 依 src 路徑過濾 slither JSON（被 scan.py 呼叫，也可獨立用）
│   ├── report.py           ← Step 4：串 build_report.py + md_to_pdf.py（cli.py report 的實作）
│   ├── build_report.py     ← 驗證 classification + 判級 + 產生 report.md / severity_chart.png
│   └── md_to_pdf.py        ← 把 report.md 轉成 report.pdf（含 CJK 字型處理）
└── test-fixtures/
    ├── vulnerable-vault/   ← 第四級 ground truth：9+1 個已知漏洞（含 Slither 漏報對照）
    └── timelock-vault/     ← 第二級 ground truth：可交付案例，含抑制註解與 before/after
```

流程對照表：

| Step | 內容 | 誰負責 | 對應指令 |
|---|---|---|---|
| 0 | 環境健檢 | 自動 | `cli.py check` |
| 1 | 跑 Slither + 過濾 | 自動 | `cli.py scan`（重掃帶 `--prev-classification` 沿用上次分類） |
| 2 | 分類 A/B/C/D + 情境式邏輯掃描 + 記錄人工發現 | **人工確認** | 無 CLI 子指令：把 Step 1 產出的 `classification_skeleton.json` 複製成 `classification.json` 填空（Claude 輔助分類或手動填都可），並依 `references/logic_scan.md` 對每份合約跑一輪邏輯漏洞檢查 |
| 3 | 加抑制註解 | **人工確認** | 無 CLI 子指令（Claude 依 SKILL.md 規則加註解，或工程師手動加） |
| 4 | 產出 report.md + report.pdf | 自動 | `cli.py report` |

Step 2/3 仍需由工程師個人或與 AI 一起判斷，避免漏報或誤報發生。

`test-fixtures/` 底下是**已知答案的迴歸測試樣本**（測試夾具）：合約與漏洞都是刻意設計、事先寫死答案的，用來測「這套 kit 本身」準不準——不是要交付的產品合約，規則與流程文件也不依賴它們。每個樣本附一份解答卷（如 `vulnerable-vault/VULNERABILITY_CATALOG.md`，記錄植入了哪些漏洞、Slither 抓到/漏掉哪些）；改動判級邏輯或情境庫後，重跑這兩個樣本驗證等級與漏報對照沒被改壞。

## 安裝與部署

這個 kit 是獨立的工具 repo（`scripts/` 就在根目錄），有兩種用法：

1. **獨立使用（不需要 Claude Code）**：clone 到任何位置，直接跑 `<kit>/scripts/cli.py`。下方範例中的 `<kit>` 代表你放這個 repo 的路徑。
2. **作為 Claude Code skill**：把 kit 帶進目標專案的 `.claude/skills/security-scan/`，Claude Code 就能以 `/security-scan` 觸發 `SKILL.md` 的完整流程——skill 的發現機制要求檔案放在這個固定位置，`SKILL.md` 內的指令路徑也以此為準。兩種用法跑的是同一套 scripts。

   實際要帶的檔案是 `SKILL.md` + `scripts/` + `references/`（`SKILL.md` 與各 scripts 都會讀 `references/` 底下三份文件，缺一份 Step 2/3/4 會找不到依據或直接報錯）；`test-fixtures/` 是 kit 自己的迴歸測試樣本，掃描流程不會讀它，**不需要**帶進新專案。`README.md` 對執行流程不是必要的，帶不帶都行。

   以 git submodule 帶入（推薦，之後 `git submodule update --remote` 可以拉 kit 更新）：
   ```bash
   cd <新專案根目錄>
   mkdir -p .claude/skills
   git submodule add <SecurityCheckKit 的 repo URL> .claude/skills/security-scan
   ```

   `git submodule add` 一定會把整個 repo（含 `test-fixtures/`）拉下來，沒有「只抓部分路徑」的選項。如果想讓工作目錄乾淨、不帶 `test-fixtures/`，接著設 sparse-checkout（cone mode 下根目錄檔案預設保留，只有你指定的子目錄會被 checkout）：
   ```bash
   cd .claude/skills/security-scan
   git sparse-checkout init --cone
   git sparse-checkout set scripts references
   cd -
   ```
   這個設定存在 submodule 自己的 `.git/info/sparse-checkout`，**不會**隨 `.gitmodules` 同步給其他人——同事 clone 這個專案並跑 `git submodule update --init` 後預設仍會拉出完整內容，得自己重跑上面兩行 `git sparse-checkout` 指令，或把它們包進專案的 setup script（例如 `Makefile` / `scripts/setup.sh`）裡跟 `submodule update --init` 一起執行。

   或直接複製（不需要保留 kit 自己的 git 歷史時）：
   ```bash
   cd <新專案根目錄>
   mkdir -p .claude/skills/security-scan
   cp -r <kit 路徑>/{SKILL.md,scripts,references} .claude/skills/security-scan/
   ```

## 使用方式

### 有 Claude Code：跑 `/security-scan`

在專案根目錄的 Claude Code 對話裡輸入 `/security-scan`（要含依賴套件本身的發現則用 `/security-scan --full-audit`）。Claude 會照 `SKILL.md` 的步驟走：自動跑 Step 0/1（呼叫下面的 CLI），把發現列給你看並等你確認分類（Step 2），確認後才加註解（Step 3），最後自動產出報告（Step 4）。

### 不用 Claude Code：直接跑 CLI

環境需求：Foundry（`forge`）、Slither（`slither`，可以裝在 venv）、系統 python 需要 `fpdf2` + `matplotlib`（見下方「環境安裝」）。

```bash
# Step 0：環境健檢，exit code 0 才代表可以往下走
python3 <kit>/scripts/cli.py check --src-prefix src/

# Step 1：跑掃描，輸出到指定目錄
python3 <kit>/scripts/cli.py scan \
  --out-dir /tmp/security-scan \
  --src-prefix src/
# --full-audit 則連 lib/ 依賴套件的發現也一併保留
# 重掃（同專案之前分類過）加 --prev-classification <上次的 classification.json>：
# 同一筆發現自動沿用上次的 category/dev_note（標記 carried_from_previous），
# 只有新出現的留空待分類；上次的 manual_findings 原樣帶入待重新確認

# Step 2：把 Step 1 產出的 classification_skeleton.json 複製成 classification.json，
# 依 SKILL.md「Step 2」的分類標準，逐筆填入 category（A 已確認需修復 / B 可接受風險 /
# C 誤報 / D 待確認）與 dev_note；預填的 check/impact/file/lines 不要動（Step 4 會核對）。
# 另外依 references/logic_scan.md 的十條情境（權限檢查實作、未保護的狀態變更、
# 旗標未落實、滑點、價格源…）對每份合約跑一輪邏輯漏洞檢查 —— 這是補 Slither
# 抓不到的業務邏輯漏洞的步驟；命中的與其他讀碼發現的工具外問題寫進 manual_findings[]
# （格式範例見 SKILL.md）

# Step 3：對 B/C 類項目手動加上區塊式抑制註解
#   // slither-disable-start <check>
#   // Dev Note: <理由>
#   <程式碼>
#   // slither-disable-end <check>
# 改完後重新跑一次 Step 1（存到不同 --out-dir，例如 /tmp/security-scan/after），
# 確認 A 類（待修復）與 D 類（待確認）項目仍然原封不動出現在新的掃描結果裡

# Step 4：產出報告
python3 <kit>/scripts/cli.py report \
  --before /tmp/security-scan/results_before.json \
  --after  /tmp/security-scan/after/results_before.json \
  --classification /tmp/security-scan/classification.json \
  --env /tmp/security-scan/scan_env.json \
  --out-dir ./security-scan-report
```

`report` 的 `--classification` / `--env` 是選填 —— 沒提供時，報告對應章節會註明「未提供」而不是報錯，方便只想快速看一次掃描結果、還不想走完整分類流程的情境。

### CLI 子指令細節

**`cli.py check`**（`env_check.py`）
- 檢查 `foundry.toml` 存在且 `src` 不是危險的 `"."`
- 跑 `forge build`
- 掃描 `--src-prefix` 底下的 `.sol` 檔，比對 OpenZeppelin v4/v5 API 特徵（`__UUPSUpgradeable_init`、`_beforeTokenTransfer` vs `_update`、`__Ownable_init` 有無參數），同一檔案內出現互斥版本特徵會被標成 `CONFLICTING` 並要求人工處理，**不會自動選版本**
- 蒐集 solc / slither / forge 版本與 `lib/` 底下每個相依套件的版本（git tag 或 `package.json`）
- exit code：0 = 全部通過；1 = 有項目需要人工處理

**`cli.py scan`**（`scan.py`）
- 跑 `slither . --json`
- 用 `filter_results.is_own_finding` 過濾（`--full-audit` 跳過過濾）
- 寫 `results_raw.json` / `results_before.json` / `scan_env.json` / `classification_skeleton.json` 到 `--out-dir`（skeleton 已預填每筆發現的所有欄位，Step 2 只需填 `category` / `dev_note`，杜絕手抄造成的分類檔與掃描結果脫鉤）
- `--prev-classification <path>`：跨次掃描的增量分類 —— 與上次分類檔比對（先 check + file + 起始行號完全比對；行號位移時退用 check + file、且兩邊都唯一才配對，避免張冠李戴），對上的沿用 category/dev_note 並標記 `carried_from_previous`（`exact`/`fallback`），新發現留空，上次的 manual_findings 原樣帶入（標 `manual`）；「上次有、這次沒有」的項目列在終端機供確認已修復。沿用結果只可能把等級拉低不可能拉高（未分類視同 D），fallback 與 manual 標記的項目 Step 2 須逐筆複核
- 印出摘要表（check / impact / 位置 / 描述）方便直接看

**`cli.py report`**（`report.py`）
- 先驗證 `classification.json`：逐筆與 `--before` 的掃描結果核對（比對鍵：check + file + 起始行號），對不上的過期項目、無效的 `category`/`impact` 值、`impact` 與掃描結果不符、B/C 類缺 `dev_note`，一律列出錯誤並以 exit code `2` 結束、**不產出報告**；掃描有但分類檔漏掉的發現則視同「未分類」（判級時當 D 算，未分類的 High 直接第四級）
- 呼叫 `build_report.py` 產生 `report.md` + `severity_chart.png`（含摘要結論資安等級、檢測方法與範圍限制聲明、人工複核發現章節、評定標準附錄）
- 呼叫 `md_to_pdf.py` 轉成 `report.pdf`（`--skip-pdf` 可跳過這步，只留 markdown）
- **exit code 即交付閘門**（見 `references/severity_grading.md`）：`0` = 第一/二級可交付；`3`/`4` = 第三/四級（報告照常產出但帶「內部工作版本」標記，僅供內部追蹤）；`2` = 驗證失敗
- 自動探測系統上哪個 python 裝有 `fpdf2` + `matplotlib`（即使目前在 Slither 的 venv 底下執行也一樣能找到系統 python），找不到就用 `SECURITY_SCAN_REPORT_PYTHON` 環境變數指定
- `--font` 可指定 CJK 字型路徑（對應 `md_to_pdf.py` 的 `SECURITY_SCAN_CJK_FONT`）

### 環境安裝

```bash
# Slither（建議裝在 venv，避免污染系統 python）
python3 -m venv venv && source venv/bin/activate
pip install slither-analyzer
solc-select install <version> && solc-select use <version>

# 報告產生需要的套件，裝在系統 python（不是上面的 venv）
python3 -m pip install --user --break-system-packages fpdf2 matplotlib
```

## 測試 Fixtures

`test-fixtures/` 底下是兩組已知答案的迴歸測試樣本，合約與掃描結果都是刻意設計、事先寫死的，
用來驗證這套 kit 本身的判級邏輯有沒有被改壞，不是要交付的產品合約。兩組合起來覆蓋交付閘門
的兩側，各自附一份完整跑完 Step 1～4 產出的報告：

- **vulnerable-vault** — 第四級（不通過）的 ground truth，未加抑制註解（Step 3 未執行）。
  合約與已知漏洞明細見 `test-fixtures/vulnerable-vault/VULNERABILITY_CATALOG.md`。
- **timelock-vault** — 第二級（可交付，需揭露已知風險）的 ground truth，實際執行了 Step 3：
  `src/TimelockVault.sol.original` 是加抑制註解前的最原始版本，`src/TimelockVault.sol`
  是加上抑制註解後、實際交付的版本，兩份都保留在 repo 裡方便直接比對。設計細節見
  `test-fixtures/timelock-vault/FIXTURE_NOTES.md`。

完整報告：

- [第二級｜timelock-vault 報告](test-fixtures/timelock-vault/security-scan-report/report.md)
- [第四級｜vulnerable-vault 報告](test-fixtures/vulnerable-vault/security-scan-report/report.md)

