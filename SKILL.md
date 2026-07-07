---
name: security-scan
description: Use this skill when the user asks to run a smart contract security scan, Slither audit, vulnerability scan, or wants a security report for a Solidity/Foundry project — e.g. "跑一次安全掃描", "用 slither 掃這個專案", "產出安全檢測報告", "run a slither scan", "security audit this contract". Drives the full Slither scan → AI triage (A/B/C) → inline suppression comments → PDF report pipeline for Foundry + OpenZeppelin upgradeable-contract projects.
argument-hint: "[--full-audit]"
---

# Slither + AI 協作安全掃描流程

這個 skill 把「Slither 掃描 → AI 分類 → 加抑制註解 → 產出完整 PDF 報告」固定成一個可重複執行的流程，用在 Foundry 專案（特別是使用 OpenZeppelin upgradeable 合約的專案）。

Step 0/1/4（環境健檢、掃描、產報告）背後都是呼叫 `scripts/cli.py`（`check` / `scan` / `report` 三個子指令）—— 這套 CLI 不依賴 Claude Code，同仁就算不用 Claude 也能直接在終端機跑同一套流程。完整的架構說明、CLI 用法、輸出格式見 `README.md`。Step 2（AI 分類）與 Step 3（加註解）仍然是本 skill 獨有、需要人在 Claude Code 對話中確認的部分，不對應任何 CLI 子指令。

**在開始前務必先讀 `references/pitfalls.md`** —— 裡面記錄了這個流程實測踩過的坑（`foundry.toml` 的 `src` 設定陷阱、OpenZeppelin 版本判斷、`slither-disable-next-line` 失效問題、PDF 中文字型問題），每一條都要遵守，不要重新踩雷。

## 前提與限制（不可協商）

1. 只能新增「註解」，絕對不能修改任何程式碼的商業邏輯、變數名稱、函式參數或執行流程。
2. 如果不確定某個發現是否可以忽略，一律歸類為 C 類（待人工確認），絕不自行加 disable 標籤。
3. Step 2（分類）與 Step 3（加註解）是**人工確認關卡** —— 執行前必須先把內容列給使用者看，明確等待使用者回覆確認才能繼續。其餘步驟（環境健檢、掃描、產報告）可以自動執行，但一旦遇到「換依賴版本也解決不了、必須改動合約呼叫方式」的情況，一律停下來問使用者，不准自己動手改商業邏輯。
4. `--full-audit` 參數：預設只掃描並報告專案自己的原始碼（排除 `lib/` 等相依套件）；帶這個參數才把相依套件本身的發現也納入報告。

## Step 0：環境健檢（自動，能跳過就跳過）

先跑：

```bash
python3 .claude/skills/security-scan/scripts/cli.py check --src-prefix src/
```

這個指令會自動做：檢查 `foundry.toml` 的 `src` 設定、跑一次 `forge build`、掃描合約原始碼判斷是 OpenZeppelin v4 還是 v5 API 特徵（衝突時直接列出衝突點，不會自己猜版本）、蒐集 solc/slither/forge 版本。**exit code 0 代表環境已就緒，直接跳到 Step 1**；非 0 代表以下某項需要處理，對照輸出訊息排除：

1. `[foundry.toml] not found`：專案還沒有 Foundry 骨架：
   - `forge init --no-git --force .`
   - 刪除預設範例檔（`src/Counter.sol`、`test/Counter.t.sol`、`script/Counter.s.sol`、`README.md`）
   - 確認 `foundry.toml` 的 `src = "src"`（**絕對不能是 `"."`**，見 `pitfalls.md` #1）
   - 若專案合約原本不在 `src/` 底下，跟使用者確認要「複製一份到 `src/`」還是「改變 `foundry.toml` 指向」—— 複製優先於改動既有檔案位置
2. `[forge build] FAILED`：檢查 import 的相依套件（`openzeppelin-contracts-upgradeable`、`@openzeppelin/contracts` 等）是否已安裝在 `lib/`：
   - 未安裝 → 讀 `[oz-version]` 那行的偵測結果（或直接讀合約特徵，見 `pitfalls.md` #2 的表格）判斷該裝 v4.x 還是 v5.x，用 `forge install <repo>@<tag>` 釘住明確版本，不要裝 latest
   - `forge remappings > remappings.txt`
   - 根據錯誤訊息判斷是依賴問題還是合約本身問題
3. `[oz-version] CONFLICTING`：代表合約混用了兩個大版本互斥的 API，這不是換依賴版本能解決的 → 停下來，具體列出衝突的呼叫點，問使用者要怎麼處理，不自行修改。
4. `[versions] slither=unknown`：`slither` 未安裝，用 `pip install slither-analyzer` 並用 `solc-select` 裝對應 solc 版本。
5. 排除以上問題後，重跑 `cli.py check` 直到 exit code 0。

## Step 1：Slither 掃描（自動）

```bash
python3 .claude/skills/security-scan/scripts/cli.py scan \
  --out-dir /tmp/security-scan \
  --src-prefix src/
```

（帶 `--full-audit` 則連 `lib/` 底下相依套件的發現也一併保留，不過濾。）

這個指令會自動：跑 `slither . --json`、過濾出專案自己的發現（`is_own_finding`，依 `source_mapping.filename_relative` 是否落在 `--src-prefix` 底下判斷）、蒐集掃描環境資訊寫成 `scan_env.json`，並在終端機印出摘要表（check / impact / 檔案:行號 / 描述）。寫入 `--out-dir`：

- `results_raw.json` — 未過濾的原始 `slither --json` 輸出
- `results_before.json` — 過濾後結果（或 `--full-audit` 時等於 raw）
- `scan_env.json` — 掃描環境資訊（`scan_date`/`project_path`/`git_commit`/`solc_version`/`slither_version`/`forge_version`/`dependencies`），供 Step 4 使用

把 CLI 印出的摘要表內容列給使用者看。

## Step 2：分類 A/B/C 【人工確認關卡】

分類標準：

- **A. 可直接忽略（False Positive）**：工具因靜態分析限制誤判，實際上有安全機制保護（如已有 nonReentrant、已做過 zero-address 檢查、OZ upgradeable 的 `__gap` 慣例等）。
- **B. 已知風險但業務上可接受（Accepted Risk）**：只有 owner/admin 能呼叫、已有其他層級防護、風險極小且有明確理由。
- **C. 待人工確認**：涉及資金流向（transfer/call/delegatecall）、access-control 邏輯本身（onlyOwner 判斷的實作邏輯，不是只是被 onlyOwner 保護的一般函式）、或信心不足的項目。**信心不足時一律歸類 C，不要猜。**

把每一筆分類寫進 `/tmp/security-scan/classification.json`：

```json
{
  "findings": [
    {
      "id": 1,
      "check": "shadowing-local",
      "impact": "Low",
      "file": "src/Token.sol",
      "lines": [38],
      "description": "<原始 slither 描述>",
      "category": "A",
      "dev_note": "<具體理由，禁止空泛字眼如「沒問題」>"
    }
  ]
}
```

把 A/B/C 三類清單列給使用者看（含每筆的具體理由），**明確等待使用者確認**（例如回覆「確認」或「ok」）才能進入 Step 3。使用者若要求把某筆從 A/B 移到 C，或反過來，更新 `classification.json` 後重新給使用者看一次。

## Step 3：加抑制註解 【人工確認關卡】

只處理 `classification.json` 裡 `category` 為 `A` 或 `B` 的項目。

1. 先列出打算修改的檔案與行號、每處要用的 detector 名稱、Dev Note 內容，等使用者明確回覆確認後才動手。
2. 格式**必須**用區塊式，理由見 `pitfalls.md` #3：

   ```solidity
   // slither-disable-start <check1>,<check2>
   // Dev Note: <說明>
   <實際程式碼>
   // slither-disable-end <check1>,<check2>
   ```

3. 若專案存在「原始碼位置」與「另一份編譯用副本」的狀況（例如合約不在 `src/` 而是複製過去的），要跟使用者確認同步範圍；並在報告裡提醒這種雙檔案結構長期會增加維護負擔，建議之後統一到單一位置。
4. 改完後驗證：
   ```bash
   forge build
   slither . --json /tmp/security-scan/results_raw_after.json
   python3 .claude/skills/security-scan/scripts/filter_results.py \
     /tmp/security-scan/results_raw_after.json \
     /tmp/security-scan/results_after.json \
     --src-prefix src/
   ```
   回報忽略前後的數量對比，並明確確認 C 類項目（不該被動到的那些）仍然原封不動出現在 `results_after.json` 裡 —— 代表沒有被誤蓋掉。

## Step 4：產出完整報告（自動）

```bash
python3 .claude/skills/security-scan/scripts/cli.py report \
  --before /tmp/security-scan/results_before.json \
  --after /tmp/security-scan/results_after.json \
  --classification /tmp/security-scan/classification.json \
  --env /tmp/security-scan/scan_env.json \
  --out-dir <專案根目錄>/security-scan-report
```

這個指令依序呼叫 `build_report.py`（產生 `report.md` + `severity_chart.png`，需要 `matplotlib`）與 `md_to_pdf.py`（轉成 `report.pdf`，需要 `fpdf2`）。這兩個套件要裝在系統 python（不是 slither 用的 venv，venv 的 pip 曾經壞掉過，見 `pitfalls.md`）：

```bash
python3 -m pip install --user --break-system-packages fpdf2 matplotlib
```

`cli.py report` 會自動探測「哪個 python 真的裝了 fpdf2/matplotlib」，就算目前在 slither 的 venv 底下執行也能找到系統 python；找不到時會清楚報錯並提示設定 `SECURITY_SCAN_REPORT_PYTHON` 環境變數指向正確的 python。

`md_to_pdf.py` 會自動找系統上的 CJK 字型；如果找不到，會清楚報錯並提示設定 `SECURITY_SCAN_CJK_FONT` 環境變數指向一個涵蓋中文字的字型檔（`.ttc`/`.ttf`），也可以用 `cli.py report --font <path>` 直接傳入。

最後跟使用者回報：
- `report.pdf` 的路徑
- 忽略前後的數量對比
- 提醒 C 類清單已經包含在報告附錄裡，不用再額外用文字轉達
