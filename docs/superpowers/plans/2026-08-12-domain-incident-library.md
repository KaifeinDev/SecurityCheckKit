# 跨領域事故模式庫（domain_incidents）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `references/logic_scan.md` Rule 1 的領域事故調查，從每個專案臨時重跑的一次性網路搜尋，改造成 SecurityCheckKit 內可跨專案共用、由 repo 側定期維護的領域事故模式庫。

**Architecture:** 新增 `references/domain_incidents/` 目錄，每個業務領域一個 Markdown 檔案，檔頭帶 `last_reviewed` 日期與條目索引。專案端執行 Rule 1 時，領域檔存在就只套用其中的「標準查證問題」而不做網路搜尋；公開資料的新鮮度由 repo 側一個獨立維護 skill 負責。專案讀碼發現的新領域層級缺口，以去識別化候選區塊寫在專案自己的 `DOMAIN_RESEARCH.md`，另行 PR 回庫，完全不在 submodule 內 commit。

**Tech Stack:** 純 Markdown 文件與 Claude Code skill 定義（`SKILL.md` + YAML frontmatter）。無程式碼、無建置步驟、無套件相依。

## Global Constraints

- **本計畫產出全部是文件，沒有可執行程式碼。** 標準 TDD 的「先寫失敗測試」不適用；每個 Task 的驗證步驟改為可實際執行的結構檢查（`grep` / `ls` / 交叉引用比對），這些檢查就是該 Task 的 gate，不要自行發明單元測試框架。
- **工作目錄**：`/Users/kai/BSOS/SecurityCheckKit`（獨立 repo，不是任何專案的 submodule 路徑）。
- **文件語言**：繁體中文，與 repo 內既有 `SKILL.md`／`references/*.md` 一致。
- **commit 訊息風格**：比照既有 git log，祈使句開頭、不加 `feat:`／`docs:` 等 conventional-commit 前綴（既有範例：`Add branded A4 cover page from designer's Untitled.svg`）。每則 commit 結尾加上 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。
- **新鮮度門檻**：3 個月。維護觸發同時支援「依 `last_reviewed` 掃描」與「人工強制指定領域」兩種。
- **去識別化規則只約束「實戰命中摘要」欄位**：`描述` 與 `來源` 欄位中的公開事故金額、受害協議名稱、審計公司名稱是必要佐證，**不得刪除**。禁止出現的是**我方客戶專案**的識別資訊。
- **條目編號格式**：`D-<領域縮寫大寫>-<兩位數編號>`，例如 `D-RWA-01`。
- **不得修改**：根目錄 `SKILL.md`、`references/severity_grading.md`、`references/pitfalls.md`、`scripts/` 下任何檔案。

## File Structure

| 檔案 | 職責 |
|---|---|
| `references/domain_incidents/README.md` | 庫的使用與維護契約：檔案結構、條目模板、去識別化規則、兩種更新來源、回饋四階段、PR review 檢查清單 |
| `references/domain_incidents/rwa.md` | RWA 領域的事故模式條目（本次回填 5 條，作為模板的實際範例） |
| `references/logic_scan.md` | 既有檔案。改寫 Rule 1 使其先查庫；新增「領域事故庫的維護規則」小節說明與 L1-L13 的分工 |
| `.claude/skills/domain-library-refresh/SKILL.md` | repo 維護者專用 skill：執行來源 A 的公開資料刷新 |

Task 順序理由：README 先定義格式契約 → rwa.md 依契約產出真實範例並驗證契約可用 → logic_scan.md 指向前兩者 → 維護 skill 操作前三者。

---

### Task 1: 庫的格式與流程契約（README）

**Files:**
- Create: `references/domain_incidents/README.md`

**Interfaces:**
- Consumes: 無（第一個 Task）
- Produces: 條目模板的欄位名稱與順序（`描述` / `來源` / `標準查證問題` / `對照 L1-L13` / `實戰命中摘要`）、檔頭欄位 `last_reviewed`、編號格式 `D-<領域縮寫>-<NN>`。Task 2 的 `rwa.md`、Task 3 的 logic_scan.md 引用文字、Task 4 的維護 skill 全部依賴這些名稱，不可改動拼法。

- [ ] **Step 1: 建立目錄與 README**

建立 `references/domain_incidents/README.md`，內容如下（完整寫入，不要摘要）：

````markdown
# 領域事故模式庫（domain_incidents）

這個目錄是 `../logic_scan.md` Rule 1（領域事故模式調查）的共用知識庫。每個業務領域一個
Markdown 檔案，記錄該領域**公開已知**的事故模式，以及把每條模式轉成「在程式碼裡要查什麼」
的標準查證問題。

## 這個庫解決什麼問題

Rule 1 原本每個專案都要重跑一次網路搜尋。真正貴的不是搜尋本身，而是把「這個領域出過什麼事」
轉成「那我要在程式碼裡查什麼」這一步——這一步慢、容易做歪，而且每次結果的深度取決於當次搜尋
的運氣。庫快取的正是這一步，附帶三個好處：

1. **一致性下限**：同領域的不同專案，Rule 1 的覆蓋深度不再靠手氣。
2. **自有實戰案例**：「這條模式在我們自己的專案上真的命中過」是搜尋拿不到的資產。
3. **與 L1-L13 的對照關係**：這是 kit 專屬判斷，不必每次重做。

效率是副產品，不是主要理由。

## 檔案結構

每個領域一個檔案：`rwa.md`、`lending.md`、`amm.md`、`bridge.md`、`stablecoin.md`、`nft.md`、
`dao.md`……。**新領域出現時才新建檔案，不預先窮舉。**

每個領域檔案的檔頭必須包含：

- `last_reviewed: YYYY-MM-DD` — 上次完成**公開資料刷新**的日期。這個欄位驅動維護排程，語意
  嚴格限定為來源 A（見下方），與實戰案例累積無關。
- **條目索引表** — 各條目的編號與一句話標題，讓讀者（含 AI）快速判斷要展開哪幾條，不必整份讀完。

## 條目模板

```markdown
## D-<領域縮寫>-<編號> <事故模式一句話標題>

- **描述**：事故模式的具體內容
- **來源**：<可點擊連結>（審計部落格／CertiK・QuillAudits・Chainlink 等資安公司文章／已知事件報導）
- **標準查證問題**：這在本專案存不存在？（1-3 條可直接照著查的具體問題）
- **對照 L1-L13**：命中 L5 / 或標「不在 L1-L13 涵蓋範圍（機制缺失類）」
- **實戰命中摘要**：2-4 句話描述「什麼類型的機制＋什麼問題＋什麼後果」，附命中日期
- （若尚無命中案例，`實戰命中摘要` 欄留空，不寫佔位假案例）
```

編號格式為 `D-<領域縮寫大寫>-<兩位數編號>`（如 `D-RWA-01`），在該領域檔案內連號，不跨檔案共用。

## 去識別化規則

**這組規則只約束「實戰命中摘要」欄位。** `描述` 與 `來源` 欄位裡的公開事故金額、受害協議名稱、
審計公司名稱是必要的佐證，**不得刪除**——要防的是洩漏**我方客戶專案**，不是隱藏公開資訊。

「實戰命中摘要」不得讓跨專案讀者反推出來源專案：

- 不寫專案名稱、公司名稱、合約或公司地址。
- 不貼合約原始碼片段，不寫函式名／變數名／檔名。
- 不寫我方專案的具體金額或量級（TVL、發行量等），後果用抽象說法（如「可能導致重複兌付」）。
- 只保留「什麼類型的機制＋什麼問題＋什麼後果＋命中日期」。

**驗收標準**：在完全不知道來源專案的前提下，這段摘要仍然讀得懂、學得到東西。

## 兩種更新來源（機制必須分開）

### 來源 A：公開資料刷新 —— repo 的維護責任

公開事故資料與任何專案無關，不該由專案觸發。由 `.claude/skills/domain-library-refresh/`
這個維護 skill 執行，兩種觸發並存：

- **依新鮮度**：掃出 `last_reviewed` 超過 **3 個月**的領域檔案。
- **人工強制**：維護者指定任一領域檔案立即刷新，不論日期（該領域剛爆重大事故、或即將接該領域的案子）。

維護範圍天然有界：領域檔案存在代表曾有專案需要它，不會去養沒人接案的領域。

### 來源 B：專案發現回饋 —— 去識別化，不卡審計關鍵路徑

見下方「回饋流程」。

### 與 L1-L13 的分工（不可混淆）

`../logic_scan.md` 末尾的「情境庫的維護規則」已經在處理「專案發現 → 歸納成通用情境 → 寫回
L1-L13」，L11／L12／L13 都是這樣長出來的。

- **程式碼層級的通用模式** → 一律走 L1-L13 那條既有路徑，**不進本庫**。
- **本庫只收**「這個領域**應該要有但沒寫**的機制」這類靠逐行讀碼看不出來的缺口。

## 回饋流程（來源 B）

審計過程**完全不碰 submodule**。專案裡的 `.claude/skills/security-scan` 是 detached HEAD 的
submodule checkout，在裡面 commit 既麻煩又容易掉；friction 高到會讓人乾脆不寫，庫於是永遠不更新。

### 階段 1：審計當下（在專案 repo，AI 執行，在關鍵路徑上）

AI 在專案自己的 `DOMAIN_RESEARCH.md` 末尾寫一個候選區塊：

```markdown
## 待回饋至共用庫

> 狀態：未回饋 | 目標領域檔：references/domain_incidents/rwa.md

### 候選 1
<完整的、已去識別化、已套好條目模板的內容，編號欄留 D-RWA-?? 待回饋時指定>
```

內容必須已去識別化、已套好模板、可直接複製貼上——回饋者不需重新編輯，只需貼上與指定編號。
工程師的審計工作到此結束，這份檔案照常 commit 在專案自己的 repo。

### 階段 2：回饋（在 SecurityCheckKit 的一般 clone，不在關鍵路徑上）

預設由跑該次審計的工程師本人執行（有上下文才答得出 review 問題），也可累積數次後批次處理：

```bash
cd <你自己的 SecurityCheckKit clone>      # 不是專案裡的 submodule 路徑
git checkout main && git pull
git checkout -b domain-incidents/<domain>-<yyyymm>
```

1. 領域檔**已存在**：把候選內容貼到檔案末尾，指定下一個未使用的編號，並在檔頭索引補上該行。
2. 領域檔**不存在**（新領域）：以模板建檔，`last_reviewed` 填該專案做完整公開調查的日期——
   依 Rule 1，領域檔不存在時該專案確實做了一次地毯式搜尋，這個日期有效。
3. **不要因為新增案例而改動既有的 `last_reviewed`**：該欄位只反映來源 A 的時點。混用會讓
   維護排程誤判。
4. commit、push、開 PR。

### 階段 3：PR review（去識別化把關）

PR review 在此不是官僚流程，而是去識別化的第二雙眼睛。Reviewer 逐項確認：

- [ ] 無專案名稱、公司名稱、合約或公司地址
- [ ] 無合約原始碼片段，無函式名／變數名／檔名
- [ ] 無我方專案的具體金額或量級數字
- [ ] 在完全不知道來源專案的前提下，這段摘要仍然讀得懂、學得到東西
- [ ] 條目編號未與現有條目衝突，檔頭索引已同步更新
- [ ] 「對照 L1-L13」欄位已填，且確認這條確實屬於領域層級（該有但沒寫的機制），而不是應該
      改走 L1-L13 維護規則的程式碼層級通用模式
- [ ] 未夾帶對**既有**領域檔 `last_reviewed` 的變更（新建領域檔則必須有此欄位）

任一項不過 → 退回修改，不合併。

### 階段 4：合併後回標（冪等性所需）

PR 合併後回到專案 repo，把 `DOMAIN_RESEARCH.md` 該區塊的狀態行改為：

```markdown
> 狀態：已回饋（D-RWA-03，PR #12） | 目標領域檔：references/domain_incidents/rwa.md
```

沒有回標的話，同專案下次重掃時 AI 會再產出一次同樣的候選，回饋者也無從判斷是否處理過。

## 並行衝突

風險低：不同領域是不同檔案，只有兩人同時改到同一領域檔才會衝突，且是純 Markdown 的末尾追加，
解法就是各自佔一個編號。
````

- [ ] **Step 2: 驗證 README 結構完整**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
for s in "## 檔案結構" "## 條目模板" "## 去識別化規則" "## 兩種更新來源" "## 回饋流程" "### 階段 1" "### 階段 2" "### 階段 3" "### 階段 4"; do
  grep -qF "$s" references/domain_incidents/README.md && echo "OK  $s" || echo "MISSING  $s"
done
grep -c "last_reviewed" references/domain_incidents/README.md
```
Expected: 九行全部 `OK`，`last_reviewed` 出現次數 ≥ 4。

- [ ] **Step 3: 驗證五個條目欄位名稱齊備（後續 Task 依賴這些拼法）**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in "描述" "來源" "標準查證問題" "對照 L1-L13" "實戰命中摘要"; do
  grep -qF "**$f**" references/domain_incidents/README.md && echo "OK  $f" || echo "MISSING  $f"
done
```
Expected: 五行全部 `OK`。

- [ ] **Step 4: Commit**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
git add references/domain_incidents/README.md
git commit -m "$(cat <<'EOF'
Add domain incident library format and contribution contract

Defines the per-domain file layout, the five-field entry template, the
de-identification rules that apply to real-world hit summaries, and the
four-stage path for contributing project findings back without ever
committing inside the submodule.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 回填 RWA 領域檔案（模板的實際範例）

**Files:**
- Create: `references/domain_incidents/rwa.md`

**Interfaces:**
- Consumes: Task 1 定義的條目模板欄位名、`last_reviewed` 檔頭欄位、`D-<領域縮寫>-<NN>` 編號格式。
- Produces: `D-RWA-01` ～ `D-RWA-05` 五個條目編號；`rwa.md` 這個路徑會被 Task 3 的 logic_scan.md 與 Task 4 的維護 skill 當作範例引用。

**背景**：來源是 `/Users/kai/BSOS/bot-gold-token/audit/DOMAIN_RESEARCH.md`，那是 2026-08 一次真實完成的 Rule 1 調查，含 5 條公開來源的事故模式。5 條全部屬於來源 A（公開研究），因此全部回填，不只 Proof-of-Reserves 一條。其中 4 條在該專案有實戰命中，需依去識別化規則改寫；模式 4 查證後排除，`實戰命中摘要` 留空。

- [ ] **Step 1: 建立 rwa.md**

建立 `references/domain_incidents/rwa.md`，內容如下（完整寫入）：

````markdown
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
- **對照 L1-L13**：命中 L12（鏈上可逆狀態與現實不可逆事實矛盾）。本條可視為 L12 在 RWA 領域
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
- **對照 L1-L13**：不在 L1-L13 涵蓋範圍（權限集中／營運風險）。L1 查的是存取控制**實作錯誤**，
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
- **對照 L1-L13**：命中 L5（價格/匯率來源可操縱）與 L11（特權參數僅單側設界）。
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
- **對照 L1-L13**：命中 L8（未授權轉帳）與 L2（應保護而未保護的狀態變更）。
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
- **對照 L1-L13**：不在 L1-L13 涵蓋範圍（機制缺失類）。這是本庫存在價值的典型案例——純靠
  L1-L13 逐條比對或逐行讀碼都不會發現，只有領域先驗知識查得到。
- **實戰命中摘要**：某實體貴金屬托管代幣專案具備標準的總量查詢函式，但沒有任何機制可讓外部
  獨立驗證流通代幣量是否對應托管方實際持有的實體儲備：無 attestation 函式、未串接任何鏈下
  儲備報告機制、無稽核時點的事件記錄。結果是系統無法提早發現「流通代幣與實體儲備已經對不上」，
  只能等到贖回擠兌時才現形。此發現是該次審計中，前面所有讀碼步驟與通用情境庫都未曾觸及的
  全新缺口。（命中日期：2026-08）
````

- [ ] **Step 2: 驗證條目編號與索引一致**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
echo "--- 條目標題:"; grep -c "^## D-RWA-" references/domain_incidents/rwa.md
echo "--- 索引列:"; grep -c "^| D-RWA-" references/domain_incidents/rwa.md
echo "--- last_reviewed:"; grep "^last_reviewed:" references/domain_incidents/rwa.md
```
Expected: 條目標題 `5`、索引列 `5`、`last_reviewed: 2026-08-12`。

- [ ] **Step 3: 驗證每條的五個欄位都在**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in "描述" "來源" "標準查證問題" "對照 L1-L13" "實戰命中摘要"; do
  printf "%-14s %s\n" "$f" "$(grep -cF "**$f**" references/domain_incidents/rwa.md)"
done
```
Expected: 五個欄位各出現 `5` 次。

- [ ] **Step 4: 去識別化把關（Task 1 階段 3 檢查清單的機器可檢部分）**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
grep -niE "botgold|gold ?token|GoldOracle|GoldRedemption|GoldMarket|_submitQuote|revokeDelivered|applyRedemption|confirmDelivery|\.sol|0x[0-9a-fA-F]{6}" references/domain_incidents/rwa.md
```
Expected: **無任何輸出**（exit code 1）。有任何一行輸出就是洩漏了客戶專案的識別資訊，必須改寫該行後重跑。

接著人工確認一項機器檢不出來的：逐條讀 `實戰命中摘要`，確認在完全不知道來源專案的前提下仍然
讀得懂、學得到東西。

- [ ] **Step 5: Commit**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
git add references/domain_incidents/rwa.md
git commit -m "$(cat <<'EOF'
Backfill RWA domain incident entries from the first Rule 1 run

Five publicly-sourced incident patterns, each with the standard
verification questions that turn the pattern into something checkable
against contract code. Four carry de-identified summaries of real hits;
the unauthorised-redemption entry was verified absent and is recorded
with an empty hit summary so the check is not repeated from scratch.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 改寫 logic_scan.md 的 Rule 1 與維護規則

**Files:**
- Modify: `references/logic_scan.md:14-29`（Rule 1 全段）
- Modify: `references/logic_scan.md:77-83`（「情境庫的維護規則」小節，於其後新增一節）

**Interfaces:**
- Consumes: Task 1 的 `references/domain_incidents/README.md` 路徑與 `last_reviewed` 欄位語意；Task 2 的 `rwa.md` 作為範例引用。
- Produces: 「`## 待回饋至共用庫`」這個區塊標題字串——Task 4 的維護 skill 會提到它。

- [ ] **Step 1: 讀取現況確認行號未偏移**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
sed -n '13,30p' references/logic_scan.md
```
Expected: 第 14 行為 `1. **領域事故模式調查（在規則 2 之前，同樣必須產出成實體文件）**：`，第 29 行為該段最後一行（`     這份清單與規則 2 的三份產出物、下表的通用情境庫，三者是互補關係，不能互相取代。`）。若不符，以內容比對定位，不要硬套行號。

- [ ] **Step 2: 用以下內容整段取代第 14-29 行**

```markdown
1. **領域事故模式調查（在規則 2 之前，同樣必須產出成實體文件）**：
   - **判定專案所屬業務領域**：RWA 代幣化、借貸協議、AMM/DEX、穩定幣、跨鏈橋、NFT、DAO 治理
     等，可能不只一種。
   - **先查共用庫，不要直接開始搜尋**：檢查 `references/domain_incidents/<領域>.md` 是否存在。
     - **存在** → 逐條套用該檔的「標準查證問題」查證回專案程式碼，逐條寫出「這在本專案存不
       存在」的結果。**此時不做網路搜尋**——公開資料的新鮮度是 repo 的維護責任（由
       `domain-library-refresh` 維護 skill 依 `last_reviewed` 負責），不該落在專案的關鍵路
       徑上。專案端重複搜尋既拖慢交付，又讓同領域不同專案的覆蓋深度取決於當次搜尋的手氣。
     - **不存在** → 對該領域做一次真正的外部調查：使用網路搜尋工具查詢該領域公開的事故案例、
       審計公司部落格、資安公司的領域風險分析（如 CertiK／QuillAudits／Chainlink 這類文章）。
       **不能只依賴模型訓練資料的記憶**——訓練資料可能過時、不完整，也無法讓使用者追溯查證來
       源；每條歸納出的事故模式都要附可點擊的來源連結。第一個進入該領域的專案必付這個成本。
   - **整理成「領域事故模式清單」，比對回專案程式碼**：針對每條模式，明確寫出「這在本專案存
     不存在」的查證結果，而不是只列出模式本身。這份清單寫成專案自己的 `DOMAIN_RESEARCH.md`。
   - **回饋共用庫**：若本次調查產生了庫裡沒有的領域層級模式（新建領域檔的情況是全部，既有領
     域檔的情況是讀碼時發現的新缺口），在 `DOMAIN_RESEARCH.md` 末尾額外寫一個
     `## 待回饋至共用庫` 區塊，內容是**已去識別化、已套好條目模板、可直接複製貼上**的候選。
     **不要嘗試在 submodule 裡 commit**——完整的四階段回饋流程與去識別化規則見
     `references/domain_incidents/README.md`。
   - **為什麼這是強制的，不是選讀背景**：規則 2 的三份產出物完全從程式碼本身推導，不需要外部
     知識，因此只能發現「讀完全部程式碼才會注意到」的問題（成本較高、較慢）。領域事故模式調查
     提供的是「已知這個產業容易在哪裡出事」的**先驗知識**，讓後續讀碼可以優先往高風險的地方
     看，而不是均勻地讀完全部才發現問題；也可能找到規則 2／L1-L13 通用檢查完全不會觸及的缺口
     類型（例如某類系統的透明度／可稽核性機制缺失，這類問題往往不是程式碼「寫錯」，而是「沒
     有寫」，逐行讀碼看不出「沒有寫的東西」，只有先知道「這個領域通常應該要有什麼」才查得到）。
     這份清單與規則 2 的三份產出物、下表的通用情境庫，三者是互補關係，不能互相取代。
```

- [ ] **Step 3: 在「情境庫的維護規則」小節之後新增一節**

在 `references/logic_scan.md` 中，找到「**規則 1 的案例對照（botgoldtoken，2026-08）**」那段
的結尾（檔案目前的最後一行），在其後追加：

```markdown

## 領域事故庫的維護規則

規則 1 使用的 `references/domain_incidents/` 是一個**跨專案共用**的領域知識庫，與本文件上方
的 L1-L13 通用情境庫分工如下，兩者不可互相取代、也不可混寫：

| | L1-L13 通用情境庫（本文件） | 領域事故庫（`domain_incidents/`） |
|---|---|---|
| 收什麼 | 程式碼層級的通用漏洞模式，跨領域適用 | 特定業務領域「應該要有但沒寫」的機制缺口 |
| 怎麼發現 | 讀碼、比對情境、狀態機圖 | 領域先驗知識；逐行讀碼看不出「沒有寫的東西」 |
| 更新來源 | 專案事後證實的漏報（見上方「情境庫的維護規則」） | 公開事故研究為主，專案發現的領域層級缺口為輔 |
| 更新流程 | 直接修改本文件 | 依 `domain_incidents/README.md` 的四階段回饋流程 |

**分流判準**：一條新歸納出的問題，若換到別的業務領域仍然成立 → 進 L1-L13；若它的成立前提是
「這個領域的系統通常應該具備某機制」 → 進領域事故庫。判不出來時優先進 L1-L13，因為那條路徑
沒有跨專案的機密外洩風險。

**公開資料的新鮮度不由專案負責**：領域檔的 `last_reviewed` 欄位由 repo 維護者透過
`.claude/skills/domain-library-refresh/` 維護 skill 更新，門檻 3 個月，另支援人工強制觸發。
專案端執行規則 1 時，領域檔存在就直接套用，不要為了「怕過期」而重跑搜尋。
```

- [ ] **Step 4: 驗證改寫結果**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
echo "--- 應該存在:"
for s in "先查共用庫，不要直接開始搜尋" "此時不做網路搜尋" "待回饋至共用庫" "## 領域事故庫的維護規則" "domain-library-refresh"; do
  grep -qF "$s" references/logic_scan.md && echo "OK  $s" || echo "MISSING  $s"
done
echo "--- L1-L13 表格應完好未動:"
grep -c "^| L" references/logic_scan.md
```
Expected: 五行全部 `OK`；`^| L` 計數為 `13`（L1-L13 十三條情境的表格列未被破壞）。

- [ ] **Step 5: 驗證既有內容沒有被誤刪**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
for s in "## 執行規則（不可跳過）" "## 情境庫" "## 情境庫的維護規則" "資產與托管地圖" "特權角色權限表" "狀態機圖" "兩段式判定"; do
  grep -qF "$s" references/logic_scan.md && echo "OK  $s" || echo "LOST  $s"
done
git diff --stat references/logic_scan.md
```
Expected: 七行全部 `OK`。diff 的刪除行數應遠小於新增行數（只該動到 Rule 1 那段）。

- [ ] **Step 6: Commit**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
git add references/logic_scan.md
git commit -m "$(cat <<'EOF'
Make Rule 1 consult the shared domain library before searching

An existing domain file is now applied as-is with no web search, since
public-data freshness belongs to the repo's maintenance skill rather
than a project's critical path. Only an absent domain file triggers the
full investigation. Adds a maintenance section drawing the line between
this library and the L1-L13 scenario list.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 維護 skill（來源 A 的公開資料刷新）

**Files:**
- Create: `.claude/skills/domain-library-refresh/SKILL.md`

**Interfaces:**
- Consumes: Task 1 的條目模板與欄位名、Task 2 的 `rwa.md` 作為既有檔案範例、Task 3 定義的 3 個月門檻語意。
- Produces: 無下游依賴（最後一個 Task）。

**定位**：這個 skill 只在 SecurityCheckKit 這個 repo 自己被當作工作目錄時才會被發現。使用端專案把本 repo 掛載成 `.claude/skills/security-scan` 時，此路徑是巢狀的不會被載入——正確反映「這是給 kit 維護者、不是給接案工程師」。

- [ ] **Step 1: 建立 skill**

建立 `.claude/skills/domain-library-refresh/SKILL.md`，內容如下（完整寫入）：

````markdown
---
name: domain-library-refresh
description: Use this skill when refreshing SecurityCheckKit's shared domain incident library (references/domain_incidents/) with newly published public incident research — e.g. "刷新領域事故庫", "更新 domain_incidents", "檢查哪些領域檔過期了", "refresh the domain incident library". Handles both the staleness sweep (last_reviewed older than 3 months) and a forced refresh of a specific domain.
argument-hint: "[領域名稱，如 rwa；省略則掃描所有過期領域]"
---

# 領域事故庫刷新（來源 A：公開資料）

這個 skill 是 SecurityCheckKit **維護者**專用，不是接案工程師在跑審計時用的。它負責
`references/domain_incidents/` 的公開資料新鮮度——把這份責任從專案的關鍵路徑上移開，
讓專案端執行 `references/logic_scan.md` 規則 1 時可以直接套用庫的內容而不必重跑搜尋。

**背景與完整規則見 `references/domain_incidents/README.md`**，特別是「兩種更新來源」一節。
本 skill 只處理**來源 A（公開資料刷新）**；來源 B（專案發現回饋）走的是 README 的四階段
PR 流程，不由本 skill 執行。

## 前提與限制（不可協商）

1. **只寫 `references/domain_incidents/` 底下的檔案**，不動 `logic_scan.md`、`SKILL.md`
   或任何其他檔案。
2. **不得新建領域檔案**。領域檔的存在代表「曾有專案需要它」；沒有專案接觸過的領域不該被維護，
   養一份沒人用的資料是純浪費。新領域檔只在專案跑規則 1 時建立。
3. **不得修改任何 `實戰命中摘要` 欄位**。那是來源 B 的資料，含去識別化判斷，不在本 skill
   職權內。
4. **產出一律走 PR，不直接 commit 到 main**，理由同 README：知識庫需要第二雙眼睛。

## Step 1：決定要刷新哪些領域檔

**帶參數**（如 `rwa`）→ 人工強制刷新該領域，**不論 `last_reviewed` 日期**。適用於該領域剛
爆出重大事故、或即將接一個該領域的案子。

**未帶參數** → 依新鮮度掃描，門檻 **3 個月**：

```bash
cd <SecurityCheckKit repo 根目錄>
TODAY=$(date +%Y-%m-%d)
CUTOFF=$(date -v-3m +%Y-%m-%d 2>/dev/null || date -d '3 months ago' +%Y-%m-%d)
echo "今天 $TODAY／門檻 $CUTOFF：last_reviewed 早於門檻者需要刷新"
grep -H "^last_reviewed:" references/domain_incidents/*.md | sort -t: -k3
```

把每個檔案的 `last_reviewed` 與 `$CUTOFF` 比較，列出需要刷新的清單給使用者看。**若清單為空，
直接回報「全部領域檔都在 3 個月內刷新過，無需處理」並結束**——不要為了有事做而硬刷。

## Step 2：對每個選中的領域檔做公開資料調查

逐一處理，一次一個領域檔。對該領域執行真正的網路搜尋，**不能只依賴模型訓練資料的記憶**——
訓練資料可能過時，也無法讓人追溯查證。搜尋方向：

- 該領域近期的公開事故與事後分析報導
- 審計公司的領域風險文章（CertiK、QuillAudits、Chainlink、Trail of Bits 等）
- 該領域新出現的攻擊手法或機制缺口類型

對搜尋到的每一條，判斷它屬於哪一種：

| 情況 | 動作 |
|---|---|
| 已被現有條目涵蓋 | 不動。若新來源比既有來源更權威或更具體，可補進該條的 `來源` 欄 |
| 現有條目的補強（新增了一種查法） | 在該條的 `標準查證問題` 補一條，不新增條目 |
| 全新的領域層級模式 | 新增條目，編號接續該檔最大號碼 |
| 程式碼層級的通用漏洞模式 | **不進本庫**，改提報到 `references/logic_scan.md` 的 L1-L13（見該檔「領域事故庫的維護規則」的分流判準） |

新增條目時嚴格套用 `README.md` 的五欄模板，且：

- `標準查證問題` 必須是**可以直接照著查的具體問題**，不是模式的複述。這一欄是庫的核心價值，
  寫成空話等於這次刷新沒有產值。
- `對照 L1-L13` 必填。若判定為「不在 L1-L13 涵蓋範圍」，要寫出屬於哪一類（如「機制缺失類」、
  「權限集中／營運風險」）。
- `實戰命中摘要` 對新條目一律留空 `（尚無命中案例）`，不要臆造。

## Step 3：更新檔頭

- 把該檔的 `last_reviewed` 改為今天的日期。
- 若有新增條目，同步更新檔頭的**條目索引表**。

## Step 4：驗證

```bash
cd <SecurityCheckKit repo 根目錄>
DOMAIN=<剛才刷新的領域，如 rwa>
echo "--- 條目數 vs 索引列數（兩者必須相等）:"
grep -c "^## D-" references/domain_incidents/$DOMAIN.md
grep -c "^| D-" references/domain_incidents/$DOMAIN.md
echo "--- 五欄齊備（各欄次數應等於條目數）:"
for f in "描述" "來源" "標準查證問題" "對照 L1-L13" "實戰命中摘要"; do
  printf "%-14s %s\n" "$f" "$(grep -cF "**$f**" references/domain_incidents/$DOMAIN.md)"
done
echo "--- 既有實戰命中摘要未被動到（應無輸出）:"
git diff references/domain_incidents/$DOMAIN.md | grep "^-" | grep "實戰命中摘要"
echo "--- last_reviewed:"
grep "^last_reviewed:" references/domain_incidents/$DOMAIN.md
```

任一項不符就修正後重跑，不要帶著結構錯誤開 PR。

## Step 5：開 PR

```bash
cd <SecurityCheckKit repo 根目錄>
git checkout -b domain-refresh/<領域>-$(date +%Y%m)
git add references/domain_incidents/<領域>.md
git commit -m "Refresh <領域> domain incidents (public research, <YYYY-MM>)"
git push -u origin HEAD
```

PR 描述要列出：新增了哪些條目、補強了哪些既有條目、`last_reviewed` 從哪天更新到哪天，以及
本次搜尋涵蓋的來源清單。最後把 PR 連結回報給使用者。
````

- [ ] **Step 2: 驗證 skill frontmatter 與結構**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
head -5 .claude/skills/domain-library-refresh/SKILL.md
echo "--- 應存在:"
for s in "## 前提與限制（不可協商）" "## Step 1" "## Step 2" "## Step 3" "## Step 4" "## Step 5" "3 個月" "不得新建領域檔案" "不得修改任何"; do
  grep -qF "$s" .claude/skills/domain-library-refresh/SKILL.md && echo "OK  $s" || echo "MISSING  $s"
done
```
Expected: 前 5 行顯示合法 YAML frontmatter（`---`、`name: domain-library-refresh`、`description:`、`argument-hint:`、`---`）；其後九行全部 `OK`。

- [ ] **Step 3: 驗證 skill 的 bash 片段在本機可執行**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
CUTOFF=$(date -v-3m +%Y-%m-%d 2>/dev/null || date -d '3 months ago' +%Y-%m-%d)
echo "cutoff=$CUTOFF"
grep -H "^last_reviewed:" references/domain_incidents/*.md
```
Expected: `cutoff` 印出約三個月前的日期（darwin 走 `date -v-3m` 那條分支）；`grep` 印出 `references/domain_incidents/rwa.md:last_reviewed: 2026-08-12`。這確認 Step 1 的掃描指令在 macOS 上真的能跑。

- [ ] **Step 4: 交叉引用檢查（全計畫收尾）**

Run:
```bash
cd /Users/kai/BSOS/SecurityCheckKit
echo "--- 被引用的路徑是否都真的存在:"
for p in references/domain_incidents/README.md references/domain_incidents/rwa.md .claude/skills/domain-library-refresh/SKILL.md references/logic_scan.md; do
  [ -f "$p" ] && echo "OK  $p" || echo "MISSING  $p"
done
echo "--- logic_scan 指向庫、庫指回 logic_scan:"
grep -c "domain_incidents" references/logic_scan.md
grep -c "logic_scan" references/domain_incidents/README.md
```
Expected: 四個路徑全部 `OK`；兩個計數皆 ≥ 1。

- [ ] **Step 5: Commit**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
git add .claude/skills/domain-library-refresh/SKILL.md
git commit -m "$(cat <<'EOF'
Add maintainer skill for refreshing the domain incident library

Runs the public-research half of library upkeep: a staleness sweep at a
three-month threshold plus a forced refresh of a named domain. Refuses
to create domain files nobody has needed and to touch the de-identified
hit summaries, which belong to the project-feedback path instead.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage** — 逐節比對 `docs/superpowers/specs/2026-08-12-domain-incident-library-design.md`：

| Spec 章節 | 對應 Task |
|---|---|
| 存放位置（SecurityCheckKit 內、每領域一檔） | Task 1 Step 1（README「檔案結構」）、Task 2 |
| 檔案結構（`last_reviewed` + 索引） | Task 1、Task 2 Step 1，Task 2 Step 2 驗證 |
| 事故模式條目模板（五欄） | Task 1 Step 1／Step 3 驗證欄位名，Task 2 Step 3 驗證每條齊備 |
| 隱私與去識別化規則 | Task 1 README「去識別化規則」，Task 2 Step 4 機器把關 |
| 執行流程（改寫 Rule 1，領域檔存在則不搜尋） | Task 3 Step 2 |
| 來源 A（維護 skill、3 個月、人工強制） | Task 4 全部 |
| 來源 B（四階段回饋流程 + review 清單） | Task 1 README「回饋流程」，Task 3 Step 2 產出 `## 待回饋至共用庫` 要求 |
| 與 L1-L13 維護規則的分工 | Task 3 Step 3 新增小節（含分流判準表） |
| 範圍邊界（不改 SKILL.md／severity_grading.md） | Global Constraints 明列禁改清單 |
| 實作產出清單 4 項 | Task 1／2／3／4 一一對應 |

無缺口。

**2. Placeholder scan** — 全計畫無 TBD／TODO／「類似 Task N」／「補上適當的錯誤處理」。所有
檔案內容都是可直接寫入的完整文字，所有驗證指令都是可直接執行的具體命令並附預期輸出。

**3. Type consistency** — 跨 Task 一致性檢查：
- 五個欄位名 `描述`／`來源`／`標準查證問題`／`對照 L1-L13`／`實戰命中摘要` 在 Task 1 定義、
  Task 2 使用、Task 4 驗證，拼法完全一致（含 `對照 L1-L13` 中間的半形空格）。
- 檔頭欄位 `last_reviewed:` 在四個 Task 中拼法一致，且 grep 樣式 `^last_reviewed:` 與 Task 2
  寫入的格式（行首、無縮排）相符。
- 編號格式 `D-RWA-01` 與驗證用的 `^## D-RWA-`、`^| D-RWA-` 樣式相符。
- Task 3 產出的 `## 待回饋至共用庫` 字串與 Task 1 README 內同一區塊標題一致。
- skill 名稱 `domain-library-refresh` 在 Task 3 引用文字、Task 4 目錄名與 frontmatter `name`
  三處一致。

**與 spec 的一處刻意偏離**：spec 的實作產出清單第 4 項只要求回填 C-04 一條，本計畫回填 5 條。
理由是來源檔 `DOMAIN_RESEARCH.md` 的 5 條模式全部出自公開研究、全部附來源連結，依 spec 的
「來源 A」定義都屬於庫的內容；只收 1 條會平白丟掉 4 條已經做完的研究成果，且單條範例不足以
展示模板在「有命中／無命中」兩種情況下的寫法。
