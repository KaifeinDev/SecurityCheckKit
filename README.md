# security-scan

在交付前，使用此工具做靜態分析並生成簡易自檢報告，確保交付的品質穩定性。

此工具拆成兩層設計：

1. **第一層：語言/工具無關的 CLI**（`scripts/cli.py`）—— 環境健檢、跑掃描、產報告，純 Python + 標準 Cli。
2. **第二層：人工確認的分類與加註解流程**（`SKILL.md`）—— 「這個發現算不算數」需要工程判斷，刻意設計成必須有人確認才能繼續，不管有沒有 Claude Code 輔助都一樣。目前這層是透過 Claude Code 的 skill 對話完成；不用 Claude Code 的同仁可以照 `SKILL.md` 的分類標準手動填 `classification.json`，一樣能走完整個流程。

## 架構

```
security-scan/
├── README.md              
├── SKILL.md                ← Claude Code skill：把 CLI + AI 分類/加註解串成完整流程
├── references/
│   └── pitfalls.md         ← 一些開發時遇過的問題（foundry.toml 陷阱、OZ 版本判斷、
│                              slither-disable-next-line 失效、PDF 中文字型）
└── scripts/
    ├── cli.py              ← 統一入口：check / scan / report 三個子指令
    ├── env_check.py        ← Step 0：環境健檢（cli.py check 的實作）
    ├── scan.py             ← Step 1：跑 slither + 過濾 + 蒐集環境資訊（cli.py scan 的實作）
    ├── filter_results.py   ← 依 src 路徑過濾 slither JSON（被 scan.py 呼叫，也可獨立用）
    ├── report.py           ← Step 4：串 build_report.py + md_to_pdf.py（cli.py report 的實作）
    ├── build_report.py     ← 產生 report.md + severity_chart.png
    └── md_to_pdf.py        ← 把 report.md 轉成 report.pdf（含 CJK 字型處理）
```

流程對照表：

| Step | 內容 | 誰負責 | 對應指令 |
|---|---|---|---|
| 0 | 環境健檢 | 自動 | `cli.py check` |
| 1 | 跑 Slither + 過濾 | 自動 | `cli.py scan` |
| 2 | 分類 A/B/C/D + 記錄人工發現 | **人工確認** | 無 CLI 子指令：把 Step 1 產出的 `classification_skeleton.json` 複製成 `classification.json` 填空（Claude 輔助分類或手動填都可） |
| 3 | 加抑制註解 | **人工確認** | 無 CLI 子指令（Claude 依 SKILL.md 規則加註解，或工程師手動加） |
| 4 | 產出 report.md + report.pdf | 自動 | `cli.py report` |

Step 2/3 仍需由工程師個人或與 AI 一起判斷，避免漏報或誤報發生。

## 使用方式

### 有 Claude Code：跑 `/security-scan`

在專案根目錄的 Claude Code 對話裡輸入 `/security-scan`（要含依賴套件本身的發現則用 `/security-scan --full-audit`）。Claude 會照 `SKILL.md` 的步驟走：自動跑 Step 0/1（呼叫下面的 CLI），把發現列給你看並等你確認分類（Step 2），確認後才加註解（Step 3），最後自動產出報告（Step 4）。

### 不用 Claude Code：直接跑 CLI

環境需求：Foundry（`forge`）、Slither（`slither`，可以裝在 venv）、系統 python 需要 `fpdf2` + `matplotlib`（見下方「環境安裝」）。

```bash
# Step 0：環境健檢，exit code 0 才代表可以往下走
python3 .claude/skills/security-scan/scripts/cli.py check --src-prefix src/

# Step 1：跑掃描，輸出到指定目錄
python3 .claude/skills/security-scan/scripts/cli.py scan \
  --out-dir /tmp/security-scan \
  --src-prefix src/
# --full-audit 則連 lib/ 依賴套件的發現也一併保留

# Step 2：把 Step 1 產出的 classification_skeleton.json 複製成 classification.json，
# 依 SKILL.md「Step 2」的分類標準，逐筆填入 category（A 已確認需修復 / B 可接受風險 /
# C 誤報 / D 待確認）與 dev_note；預填的 check/impact/file/lines 不要動（Step 4 會核對）。
# 讀合約時發現的工具外問題（壞掉的權限檢查、缺漏的保護等）寫進 manual_findings[]
# （格式範例見 SKILL.md）

# Step 3：對 B/C 類項目手動加上區塊式抑制註解
#   // slither-disable-start <check>
#   // Dev Note: <理由>
#   <程式碼>
#   // slither-disable-end <check>
# 改完後重新跑一次 Step 1（存到不同 --out-dir，例如 /tmp/security-scan/after），
# 確認 A 類（待修復）與 D 類（待確認）項目仍然原封不動出現在新的掃描結果裡

# Step 4：產出報告
python3 .claude/skills/security-scan/scripts/cli.py report \
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
- 印出摘要表（check / impact / 位置 / 描述）方便直接看

**`cli.py report`**（`report.py`）
- 先驗證 `classification.json`：逐筆與 `--before` 的掃描結果核對（比對鍵：check + file + 起始行號），對不上的過期項目、無效的 `category`/`impact` 值、`impact` 與掃描結果不符、B/C 類缺 `dev_note`，一律列出錯誤並以 exit code `2` 結束、**不產出報告**；掃描有但分類檔漏掉的發現則視同「未分類」（判級時當 D 算，未分類的 High 直接第四級）
- 呼叫 `build_report.py` 產生 `report.md` + `severity_chart.png`（含 Executive Summary 資安等級、檢測方法與範圍限制聲明、人工複核發現章節）
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

## Future Work

- **尚未支援跨次掃描的增量分類**：每次重跑 Step 2 都要把所有發現重新分類一次，即使跟上次掃描完全相同。`classification_skeleton.json` 已經把「預填欄位」這一半做掉了，且報告端的比對鍵（check + file + 起始行號）可以直接沿用；剩下的是讓 skeleton 產生時自動比對上一份 `classification.json`，同指紋的發現沿用舊分類，只把新出現的拿出來問人。
- **已修復漏洞要不要留痕待決**：目前修復後重掃產出的最終報告不會提到「曾發現並已修復」的項目（交付報告只描述交付物現狀，開發過程中修掉的問題不列入）。若之後決定要在交付文件展示修復歷程，或做成 `--include-resolved-history` 選項，需另外設計跨掃描的紀錄保存。
- **目前只服務單一 repo**：`scripts/` 目前放在這個 repo 的 `.claude/skills/security-scan/` 底下。要在多個甲方專案間重複使用，需要再抽成獨立 repo 或內部套件，讓每個專案用 submodule/複製的方式帶入，並統一維護 `pitfalls.md` 累積的踩坑知識。
- **`cli.py check` 的 OZ 版本偵測是特徵比對，不是語意分析**：只認得目前記錄在 `pitfalls.md` 裡的幾個 v4/v5 API 特徵，換一種完全不同的相依套件（例如非 OpenZeppelin 的合約庫）不會被偵測到，遇到會直接跳過、不會誤判。
