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
   養一份沒人用的資料是純浪費。新領域檔只透過來源 B（專案發現回饋）的階段 2 建立——由跑過該
   領域首次調查的工程師在自己的一般 clone 裡建檔、開 PR，本 skill 不建立領域檔。
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
| 程式碼層級的通用漏洞模式 | **不進本庫**，改提報到 `references/logic_scan.md` 的 L1-L19（見該檔「領域事故庫的維護規則」的分流判準） |

新增條目時嚴格套用 `README.md` 的五欄模板，且：

- `標準查證問題` 必須是**可以直接照著查的具體問題**，不是模式的複述。這一欄是庫的核心價值，
  寫成空話等於這次刷新沒有產值。
- `對照通用情境` 必填。若判定為「不在 L1-L19 涵蓋範圍」，要寫出屬於哪一類（如「機制缺失類」、
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
for f in "描述" "來源" "標準查證問題" "對照通用情境" "實戰命中摘要"; do
  printf "%-14s %s\n" "$f" "$(grep -cF "**$f**" references/domain_incidents/$DOMAIN.md)"
done
echo "--- 既有實戰命中摘要未被動到（tripwire，不是證明——見下方說明）:"
git diff HEAD references/domain_incidents/$DOMAIN.md | grep "^-" | grep "實戰命中摘要"
echo "--- last_reviewed:"
grep "^last_reviewed:" references/domain_incidents/$DOMAIN.md
```

任一項不符就修正後重跑，不要帶著結構錯誤開 PR。

**「既有實戰命中摘要未被動到」這項 grep 只是 tripwire，不是證明**：`實戰命中摘要` 這個標籤只
出現在每個摘要的第一行，但摘要本文通常再往下延伸 3-4 行；改動延伸行、不改第一行，這條 grep
抓不到。`git diff HEAD` 已經涵蓋 staged 的變更，但多行的條目區塊沒有可靠的 grep 邊界能自動比對
「整段摘要是否原封不動」。因此**維護者必須另外手動看過本次刷新觸碰到的每一條目的完整 diff**，
逐眼確認沒有任何既有 `實戰命中摘要` 的內容被改動（包含摘要延伸的每一行），才能視為 Step 4 通過。
grep 沒輸出不代表安全，只代表沒踩到最明顯的那種修改。

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
