---
name: security-scan
description: Use this skill when the user asks to run a smart contract security scan, Slither audit, vulnerability scan, or wants a security report for a Solidity/Foundry project — e.g. "跑一次安全掃描", "用 slither 掃這個專案", "產出安全檢測報告", "run a slither scan", "security audit this contract". Drives the full Slither scan → AI triage (A/B/C/D) → inline suppression comments → PDF report pipeline for Foundry + OpenZeppelin upgradeable-contract projects.
argument-hint: "[--full-audit]"
---

# Slither + AI 協作安全掃描流程

這個 skill 把「Slither 掃描 → AI 分類 → 加抑制註解 → 產出完整 PDF 報告」固定成一個可重複執行的流程，用在 Foundry 專案（特別是使用 OpenZeppelin upgradeable 合約的專案）。

Step 0/1/3（環境健檢、掃描、產報告）背後都是呼叫 `veros`（`doctor` / `scan` / `report`）—— 這幾個步驟是純確定性的，可以獨立於 Claude 執行、也可以接進 CI。Step 2（分類）需要工程判斷與 LLM 輔助，其中**機械性可檢查的部分**由 `veros review` 負責。加抑制註解已不再是編號步驟，改為選配的收尾動作（見本文件最後一節）。完整的架構說明、CLI 用法、輸出格式見 `README.md`。

**在開始前務必先讀 `references/pitfalls.md`** —— 裡面記錄了這個流程實測踩過的坑（`foundry.toml` 的 `src` 設定陷阱、OpenZeppelin 版本判斷、`slither-disable-next-line` 失效問題、PDF 中文字型問題），每一條都要遵守，不要重新踩雷。

## 前提與限制（不可協商）

1. 只能新增「註解」，絕對不能修改任何程式碼的商業邏輯、變數名稱、函式參數或執行流程。
2. 如果不確定某個發現是否可以忽略，一律歸類為 D 類（待人工確認），絕不自行加 disable 標籤。
3. Step 2（分類）是**人工確認關卡** —— 執行前必須先把內容列給使用者看，明確等待使用者回覆確認才能繼續。其餘步驟（環境健檢、掃描、產報告）可以自動執行，但一旦遇到「換依賴版本也解決不了、必須改動合約呼叫方式」的情況，一律停下來問使用者，不准自己動手改商業邏輯。
4. `--full-audit` 參數：預設只掃描並報告專案自己的原始碼（排除 `lib/` 等相依套件）；帶這個參數才把相依套件本身的發現也納入報告。

## Step 0：環境健檢（自動，能跳過就跳過）

先跑：

```bash
veros doctor --src-prefix src/
```

這個指令會自動做：**偵測建置系統（Foundry 或 Hardhat）**、確認專案編譯得起來、掃描合約原始碼判斷是 OpenZeppelin v4 還是 v5 API 特徵（衝突時直接列出衝突點，不會自己猜版本）、蒐集 solc/slither/forge 版本。**exit code 0 代表環境已就緒，直接跳到 Step 1**；非 0 代表以下某項需要處理，對照輸出訊息排除：

**關於建置系統**：`[build-system]` 那行會印出 `foundry`、`hardhat` 或 `none detected`。兩者皆可掃描——slither 的 crytic-compile 會自行驅動建置，Step 1 完全不管專案用哪一套。差別只在這個 Step 0 怎麼驗證「編譯得起來」：Foundry 走 `forge build`，Hardhat 走 `npx hardhat compile`。**外部專案（審計標的、回測樣本）多半是 Hardhat，這是正常情況，不需要改建成 Foundry。** Hardhat 專案常見兩個卡點，check 會直接給出對應提示：config 從環境變數讀部署金鑰而拒絕載入（編譯不需要真金鑰，用 dummy 值即可），以及 peer dependency 衝突（`npm install --legacy-peer-deps`）。Hardhat 專案的 `--src-prefix` 通常是 `contracts/` 而非 `src/`。

1. `[foundry.toml] not found`（且未偵測到 Hardhat）：專案還沒有任何建置骨架：
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
5. 排除以上問題後，重跑 `veros doctor` 直到 exit code 0。

## Step 1：Slither 掃描（自動）

```bash
veros scan \
  --out-dir /tmp/security-scan \
  --src-prefix src/
```

（帶 `--full-audit` 則連 `lib/` 底下相依套件的發現也一併保留，不過濾。）

**兩個降噪參數**（實測 443 筆的專案套用後只剩 217 筆需要人工判斷）：

- **`--exclude-path <前綴>`**（可重複）：排除**位於 `--src-prefix` 內部**的 mock／測試樁目錄，例如 `--exclude-path contracts/fake/`。`--src-prefix` 只能框到來源根目錄，框不掉根目錄裡面的假合約；那些合約永遠不會部署，它們的發現卻會跟真合約的發現搶同一份人工注意力。排除優先於納入：只要發現碰到的任何一個檔案落在排除路徑，整筆就會被丟掉。`--full-audit` 也照樣套用此參數。
- **預設開啟的風格預分類**：`naming-convention` 與 `unindexed-event-address` 這兩個純風格檢查會被自動預填 `category: "C"`、附上理由，並標記 `auto_classified: "style"`。它們**仍然留在報告裡**（數字與重掃仍可對帳），只是不必逐筆人工判。要關掉用 `--no-auto-style`。這份名單刻意保守——只收「絕不可能代表安全問題」的檢查器；`solc-version`、`pragma`、`unused-state` 這類有爭議的一律不收，仍交人工判斷。

**重掃時（同一專案之前已做過 Step 2）加上 `--prev-classification <上次的 classification.json>`**：skeleton 會把「跟上次同一筆」的發現（check + file + 起始行號一致；行號位移時退而用 check + file 唯一比對）自動沿用上次的 category/dev_note 並標記 `carried_from_previous`，只有新出現的發現留空待分類；上次的 manual_findings 也會原樣帶入。CLI 會列出「上次有、這次沒有」的已解決清單。

這個指令會自動：跑 `slither . --json`、過濾出專案自己的發現（`is_own_finding`，依 `source_mapping.filename_relative` 是否落在 `--src-prefix` 底下判斷）、蒐集掃描環境資訊寫成 `scan_env.json`，並在終端機印出摘要表（check / impact / 檔案:行號 / 描述）。寫入 `--out-dir`：

- `results_raw.json` — 未過濾的原始 `slither --json` 輸出
- `results_before.json` — 過濾後結果（或 `--full-audit` 時等於 raw）
- `scan_env.json` — 掃描環境資訊（`scan_date`/`project_path`/`git_commit`/`solc_version`/`slither_version`/`forge_version`/`dependencies`），供 Step 4 使用
- `classification_skeleton.json` — Step 2 的起點：每筆發現已預填 `id`/`check`/`impact`/`file`/`lines`/`description`，只留 `category` 與 `dev_note` 空白

把 CLI 印出的摘要表內容列給使用者看。

## Step 2：分類 A/B/C/D 【人工確認關卡】

分類標準（依嚴重性由高到低排列，**A 是最需要處理的項目，不是最無害的**——這跟很多人直覺的「A 類=可以放著不管」相反，務必留意）：

- **A. 已確認漏洞，需修復（Confirmed Vulnerability）**：涉及資金流向（transfer/call/delegatecall）或 access-control 邏輯本身（onlyOwner 判斷的實作邏輯，不是只是被 onlyOwner 保護的一般函式），且已確認是真的問題，不是誤判、也不是可接受的已知風險。**這類項目不能被加抑制註解**——加了等於把真漏洞藏起來不讓外部審計看到。
- **B. 已知風險但業務上可接受（Accepted Risk）**：只有 owner/admin 能呼叫、已有其他層級防護、風險極小且有明確理由。
- **C. 可直接忽略（False Positive）**：工具因靜態分析限制誤判，實際上有安全機制保護（如已有 nonReentrant、已做過 zero-address 檢查、OZ upgradeable 的 `__gap` 慣例等）。
- **D. 待人工確認**：信心不足，還無法判斷屬於 A/B/C 哪一類的項目。**信心不足時一律歸類 D，不要用猜的塞進 A/B/C。**

**Step 2 的必填欄位**（`veros report` 會逐條驗證，缺了直接 exit 2、不產報告）：

- `severity`：業界五級（Critical／High／Medium／Low／Informational），**必填**。skeleton 已預填為工具 impact 的對應值，維持原值永遠不需要理由。
- `severity_rationale`：只有**降級**（判得比工具輕）時必填。閘門讀的是唯讀的 `impact`，所以降級不會繞過閘門，但報告會並列印出兩個等級與這段理由，讓甲方能檢視這個判斷。
- `remediation`：`category = A` 必填，寫「怎麼修」。報告以「建議修法」呈現，內容給 diff 或改後的程式碼片段，並分短期修復與長期架構建議。
- `confirm_what` / `confirm_who` / `confirm_branches`：`category = D` 必填三格——要確認什麼、問誰、兩種答案各自怎麼做。**D 類不得停在問句。**
- `id`：統一編號（`<專案縮寫大寫>-<兩位數>`，如 `BGT-01`），掃描發現與人工發現共用同一序列、不得重複；原掃描序號留在 `scan_id`，不印進報告。

**確認成立的發現要寫的四個欄位**（`category = A`／`D` 與全部 `manual_findings`）。報告依 Cyfrin 格式排版成 `[S-#] 標題` → 說明 → 影響 → PoC → 建議修法；缺的欄位會在報告中顯示「待補」並在 `veros report` 的 stdout 列出，不擋產出：

- `title`：一句話標題，寫「根因 + 影響」而不是 detector 名稱。`reentrancy-eth` 是檢查器名稱，不是標題；「repayLoan 缺少 nonReentrant，重入期間份額價格虛高」才是。
- `explanation`：哪個函式、正常應該怎麼運作、為什麼出錯。掃描工具的原始描述會另外獨立呈現，不要照抄。
- `impact_detail`：具體危害，把技術問題轉成業務損失（誰的錢、多少、什麼條件下）。欄位名不叫 `impact`，因為 `impact` 已經是工具自己的嚴重度且閘門讀它。
- `proof_of_concept`：攻擊邏輯的步驟，或可重現的測試碼／指令。

**報告中的 `[S-#] 編號**：由嚴重度代碼（C 危急／H 高／M 中／L 低／I 資訊）加該嚴重度內的序號組成，**產報告時即時推導、不寫進 classification.json**——它編碼了嚴重度，而嚴重度是可以改的，存起來會在重新分級後無聲過期。只指派給經判定確實成立的發現；誤報（C）與已接受風險（B）沿用掃描編號。**交叉引用一律寫穩定的掃描編號**（如「同 BGT-02」），報告會自動替換成當下的 `[S-#]`。

**另外兩個頂層鍵**：`scenario_coverage`（情境庫逐合約覆蓋紀錄，進報告的「情境庫覆蓋」章節——`hits` 內的編號必須對得上實際存在的 finding）與 `scope_exclusion_reasons`（`--exclude-path` 每個前綴的排除理由，進報告的「掃描範圍」章節）。

**從 skeleton 開始，不要手打**：把 Step 1 產出的 `classification_skeleton.json` 複製成 `/tmp/security-scan/classification.json`，只填每筆的 `category` 與 `dev_note`，**不要改動預填的 `check`/`impact`/`file`/`lines`**（Step 4 會逐筆核對這些欄位跟掃描結果是否一致，不一致直接拒絕產報告；`impact` 打錯以前會讓資安等級虛高，現在會被擋下）：

```json
{
  "findings": [
    {
      "id": 1,
      "check": "shadowing-local",
      "impact": "Low",
      "file": "src/Token.sol",
      "lines": [38],
      "description": "<skeleton 預填的 slither 描述>",
      "category": "C",
      "dev_note": "<具體理由，禁止空泛字眼如「沒問題」；B/C 類必填>",
      "title": "",
      "explanation": "",
      "impact_detail": "",
      "proof_of_concept": "",
      "remediation": ""
    }
  ],
  "manual_findings": []
}
```

**情境式邏輯掃描（GPT-Scan 式，必做）**：Slither 抓不到業務邏輯層級的漏洞，這一段就是補這個缺口的。分類過程中，對掃描範圍內的**每一份合約**跑完 `references/logic_scan.md` 情境庫的**全部**情境（目前 L1～L19：權限檢查實作錯誤、未保護的狀態變更、旗標未落實、缺滑點保護、可操縱價格源、首存者操縱、可搶跑初始化、未授權轉帳、記帳順序、權重複用、特權參數僅單側設界、鏈上可逆狀態與現實不可逆事實矛盾、可替換的信任地址、特權管制動作可被搶跑規避、跨鏈狀態在錯誤的一側被驗證。**情境會持續增補，一律以該檔實際內容為準，不要以此處列舉為準**），採兩段式判定：先比對合約是否具備該情境的前置條件，有才逐行讀關鍵語句確認。命中的候選寫進 `manual_findings[]` 並在 `scenario` 欄位標注情境編號；**信心不足填 D，不硬判**。

**人工複核發現（manual_findings）**：除了上述情境庫，讀碼過程看到任何 Slither 沒報的問題（不限於情境庫涵蓋範圍）也寫進 `manual_findings[]`，一樣列給使用者確認：

```json
{
  "id": "M1",
  "title": "<一句話標題：根因 + 影響>",
  "severity": "Critical|High|Medium|Low|Informational",
  "file": "src/Vault.sol",
  "lines": [32, 35],
  "description": "<哪個函式、正常該怎麼運作、為什麼出錯>",
  "impact_detail": "<具體危害與業務損失>",
  "proof_of_concept": "<攻擊步驟或可重現的測試碼>",
  "remediation": "<diff 或改後的程式碼；短期修復與長期建議>",
  "category": "A|B|D",
  "scenario": "<可選：命中 references/logic_scan.md 的情境編號，如 L3>",
  "dev_note": "<判斷依據，必須引用關鍵語句位置（檔案:行號）；人工發現不存在 C 誤報，確認不是問題就直接移除>"
}
```

人工發現會進報告的「人工複核發現」章節並參與資安等級計算（Critical/High 直接判第四級）。**特別留意**：凡是分類理由想寫「僅 owner/admin 可呼叫所以可接受」，必須先實際檢查該 modifier / require 的實作邏輯是不是真的有效，並把檢查結果寫進 dev_note —— 權限檢查本身壞掉是 Slither 抓不到的典型漏報。

**選填的 `status` 欄位（修復進度追蹤，跟 `category` 是兩件事）**：`findings[]`／`manual_findings[]` 的每一筆都可以額外加一個 `status` 欄位，記錄目前的修復／處置進度（例如 `"待處理"`、`"已修復"`、`"已確認接受風險"`），跟 `category`（這是不是問題、算哪一類）是正交的兩個維度——`category` 定案後通常不會再變，`status` 會隨著專案團隊的修復進度持續更新。此欄位為選填、不驗證固定字典，缺省時報告顯示「待處理」。只有 `category=A` 的掃描發現與**全部** `manual_findings`（依規則永遠不是 C 類，見上方 category 限制）才會進入報告新增的「待決策／待處理項目總表」（B/C 類是永久性判定，沒有「修復進度」這個概念，不適用 `status`）。等專案開始修復後，重跑報告時把對應項目的 `status` 更新掉，總表跟逐筆明細會一起反映最新進度，不需要另外開新文件追蹤。

掃描結果裡的**每一筆**發現都要分類：Step 4 會把 classification.json 跟掃描結果逐筆核對，漏掉的一律視同 D（待確認），未分類的 High 直接把等級打成第四級。

**風格預分類（`auto_classified: "style"`）的複核義務**：skeleton 裡標了這個欄位的項目已由 scan 預填為 C，可視為已分類，但列給使用者時要**明講有幾筆被自動判為 C、是哪些檢查器**，不能默默略過——使用者有權知道哪些發現不是人判的。若使用者認為某筆有安全含義，清空 `category` 與 `auto_classified` 後重新判定。

**重掃沿用（`--prev-classification`）的複核義務**：skeleton 裡標 `carried_from_previous: "exact"` 的項目可視為已分類，但列給使用者時要註明是沿用；標 `"fallback"` 的（行號位移、用 check+file 對上的）必須逐筆重讀確認沒對錯行；帶入的 manual_findings（標 `"manual"`）不隨掃描結果失效，要逐筆重新確認仍然成立，已修復的直接刪除。

**分類填完後先跑機械檢查**：

```bash
veros review \
  --classification /tmp/security-scan/classification.json
```

它會列出：共用同一段 dev_note 的群組、dev_note 過短、必填欄位缺漏、降級未附理由，以及兩個單獨成節的重點——**「工具判 High、我方判誤報（C）」**與**「工具判 High、我方降級」**。這兩節是整份分類裡權重最高、甲方最可能逐條挑戰的判斷，必須逐筆確認 dev_note 是針對該筆自己的程式碼寫的，不是共用的模板理由。exit code 1 代表有待抽查項目（提醒，不是錯誤）。

**還要另外產出協定理解摘要**：把 `audit/AUDIT_NOTES.md` 的資產與托管地圖、特權角色權限表改寫成對外語氣的 markdown，存成 `audit/overview.md`，用 `--overview` 傳給 report。這會成為報告的「協定理解摘要」章節——甲方最想知道的一件事是「誰能動我的錢」，而這是全部產出裡唯一真正需要額外人力的一項。缺這份時報告該章節會印出明顯的「未提供」警語。

把 A/B/C/D 四類清單與 manual_findings 列給使用者看（含每筆的具體理由），**明確等待使用者確認**（例如回覆「確認」或「ok」）才能進入 Step 3。使用者若要求把某筆從一類移到另一類，更新 `classification.json` 後重新給使用者看一次。

## Step 3：產出完整報告（自動）

```bash
veros report \
  --before /tmp/security-scan/results_before.json \
  --classification /tmp/security-scan/classification.json \
  --env /tmp/security-scan/scan_env.json \
  --scope /tmp/security-scan/scope.json \
  --overview <專案根目錄>/audit/overview.md \
  --client "<甲方名稱>" \
  --engagement-from <YYYY-MM-DD> --engagement-to <YYYY-MM-DD> \
  --out-dir <專案根目錄>/security-scan-report
```

**會產出兩份文件**：

- `<out-dir>/report.md` + `report.pdf` —— **交付報告**，給甲方。
- `<專案根>/audit/worksheet.md` —— **工作底稿**，內部用（全量逐筆分類、複核提醒、完整覆蓋矩陣）。刻意寫在交付目錄之外、不轉 PDF。**這個路徑必須被 gitignore**，否則會隨程式碼交付給甲方；沒被忽略時 CLI 會警告。用 `--worksheet` 可改路徑。

這個指令依序呼叫 `build_report.py`（產生 `report.md`）與 `md_to_pdf.py`（轉成 `report.pdf`，需要 `fpdf2`）。`fpdf2` 要裝在系統 python（不是 slither 用的 venv，venv 的 pip 曾經壞掉過，見 `pitfalls.md`）：

```bash
python3 -m pip install --user --break-system-packages "fpdf2>=2.8.8"
```

`fpdf2` 版本**建議 2.8.8 以上**：2.8.7 有一個字型子集化的靜默亂碼 bug，會把封面頁的短 ASCII 文字（`檢測工具`／`檢測日期`）畫錯但不拋例外，見 `pitfalls.md` #6。若環境的 python 只支援到 2.8.4（例如 macOS 內建的 Python 3.9），實測未重現該 bug，但**每次產出後仍要把封面頁轉成圖片目視確認**（`pdftoppm -png -f 1 -l 1 report.pdf /tmp/cover`）——這個 bug 不拋例外，`pdftotext` 也讀不出來。

`veros report` 會自動探測「哪個 python 真的裝了 fpdf2」，就算目前在 slither 的 venv 底下執行也能找到系統 python；找不到時會清楚報錯並提示設定 `SECURITY_SCAN_REPORT_PYTHON` 環境變數指向正確的 python。

`md_to_pdf.py` 會自動找系統上的 CJK 字型（含優先嘗試將可變字重字型切出 Regular/Bold 兩個靜態字重，快取於 `~/.cache/security-check-kit/fonts/`，讓標題真正以粗體呈現而非只放大字級）；如果找不到，會清楚報錯並提示設定 `SECURITY_SCAN_CJK_FONT`（可選搭配 `SECURITY_SCAN_CJK_FONT_BOLD`）環境變數指向涵蓋中文字的字型檔（`.ttc`/`.ttf`），也可以用 `veros report --font <path> [--font-bold <path>]` 直接傳入。

**`veros report` 的 exit code 就是交付閘門**（詳見 `references/severity_grading.md`）：

- `0` = 可交付
- `3` / `4` = 不可交付 —— 報告照常產出，但開頭帶「內部工作版本 — 不可作為交付文件」標記，只能用於內部追蹤，**不可交給甲方**
- `2` = classification.json 驗證失敗（缺漏對不上掃描結果、category/impact/severity 值錯誤、B/C 缺 dev_note、A 缺 remediation、D 缺三格、降級缺理由等），不會產出報告，逐筆錯誤在 stderr —— 修正後重跑

**等級（第一～四級）不出現在報告本文**，它只驅動 exit code 與浮水印，見 `references/severity_grading.md`。

最後跟使用者回報：
- `report.pdf` 與 `worksheet.md` 的路徑
- **閘門結果**：可交付／不可交付。不可交付時明確告知「這份是內部工作版本，不能交付」，並列出卡住閘門的項目編號（CLI 會印出）
- 本次發現總數與嚴重度分布
- 若有自動預分類或沿用前次分類的項目，明講筆數（報告本身也會揭露）

## 選配：抑制註解（降低後續 CI 雜訊，不是編號步驟）

**這一段與報告無關。** 專業審計公司不會改客戶的程式碼，誤報在內部就被丟掉、不進交付物；抑制註解是**開發團隊的 CI 衛生實務**——它的價值是「下次跑掃描時那些已判定的發現不會淹沒新問題」，而這個價值只在「我們持續擁有並維護這份程式碼」時成立。外部標的（審計對象、回測樣本）一律跳過，那是正確的做法，不是偷懶。報告永遠只呈現當次掃描的當前結果，不做加註解前後的對照。

只處理 `classification.json` 裡 `category` 為 `B` 或 `C` 的項目——這兩類是「不是真的需要修的東西」，才適合抑制。`A`（已確認需修復）與 `D`（待確認）絕對不能加抑制註解，加了會讓真正的漏洞或還沒判斷清楚的項目從掃描結果裡消失。

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
   veros scan \
     --out-dir /tmp/security-scan/after --src-prefix src/
   ```
   比對加註解前後的發現數量，並明確確認 `category` 為 A（已確認需修復）與 D（待確認）的項目仍然原封不動出現在新的掃描結果裡 —— 代表沒有被誤蓋掉。**報告不呈現這個前後對照**（報告只呈現當次掃描結果），這是純內部的驗證動作。
   注意區塊式抑制是**永久生效**的：未來在 `slither-disable-start`/`end` 之間新增的程式碼也會被靜默忽略，所以區塊範圍要盡量貼近實際需要抑制的那幾行。
