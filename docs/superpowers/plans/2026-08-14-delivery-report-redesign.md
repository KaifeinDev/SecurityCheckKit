# 交付報告改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `docs/superpowers/specs/2026-08-14-delivery-report-redesign.md` 的 13 項決定，把交付報告從「35 頁、77% 是 B/C/D 明細、三個互相矛盾的 High 筆數」改成「10–12 頁、業界審計報告版面、單一嚴重度呈現」，並把內部工件（全量明細、複核提醒、覆蓋矩陣）分流到 gitignore 的工作底稿。

**Architecture:** `impact`（工具、唯讀、閘門依據）／`severity`（人工、業界五級、報告呈現）／`status`（處置進度）三個正交欄位取代現行的四套並行尺規；整案等級 Tier 1–4 從報告本文移除，僅驅動 exit code 與內部版浮水印。報告輸入從「`--before` + `--after` 兩份掃描結果對照」改成「單一當次掃描結果」，新增 `scope.json`（範圍）與 `--overview`（協定理解摘要）兩個輸入。`build_report.py` 的輸出層實質重寫，驗證層（reconcile / exit code）刻意保留不動。

**Tech Stack:** Python 3 標準庫 + `fpdf2>=2.8.8` + `matplotlib`（皆為現有相依，不新增套件）。無測試框架——本 repo 沒有 test suite，回歸驗證一律以 `test-fixtures/` 兩組樣本的完整重跑 + 輸出 diff 作為 gate（這是 `README.md` 既有的驗證約定）。

## Global Constraints

- **工作目錄**：`/Users/kai/BSOS/SecurityCheckKit`（獨立 repo，不是任何專案的 submodule checkout）。
- **文件語言**：繁體中文，與既有 `SKILL.md`／`references/*.md`／報告輸出一致。程式碼註解沿用既有英文風格（見 `build_report.py` 現行註解）。
- **commit 訊息風格**：祈使句開頭、不加 `feat:`／`docs:` 等 conventional-commit 前綴。每則 commit 結尾加 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。
- **不得修改**：`references/logic_scan.md`、`references/domain_incidents/`（含底下全部檔案）、`references/pitfalls.md`、`.claude/skills/domain-library-refresh/`、`docs/benchmarks/`。這次改版是文件工程，不動審計方法。
- **必須保留不動的行為**（迴歸紅線，每個 Task 的驗證都要確認）：
  - `build_report.py` 的 reconcile 邏輯：掃描有、分類檔沒有的發現視同未分類；分類檔有、掃描沒有的視為 stale error。
  - **`impact` 必須逐字等於掃描輸出，不符 exit 2**——這道驗證不拆。
  - exit code 語意：`0` = Tier 1/2、`2` = 驗證失敗且不產報告、`3` = Tier 3 或無法評級、`4` = Tier 4。
  - Tier 判定演算法本身（`compute_grade`）不改，只改「它的結果印在哪裡」。
- **嚴重度模型的三條硬規則**：
  1. 閘門算在 `impact`，**不算在 `severity`**。
  2. `severity` 只影響報告呈現，不影響 exit code。
  3. 報告必須並列印出兩欄，讓人工降級可見。
- **禁止的作法**：不要為了讓 fixture 通過而放寬驗證；不要把 `severity` 預設成 `impact` 之後就不管（必填代表缺了要 exit 2）；不要在 `build_report.py` 內做網路存取或呼叫 LLM。

## File Structure

| 檔案 | 職責 | 變更程度 |
|---|---|---|
| `scripts/build_report.py` | 報告產生。驗證層保留，輸出層重寫 | 大 |
| `scripts/scan.py` | 新增 `scope.json` 產出；skeleton 加新欄位 | 中 |
| `scripts/review.py` | **新增**：`classification.json` 的機械品質檢查 | 新檔 |
| `scripts/cli.py` | 新增 `review` 子指令 | 小 |
| `scripts/report.py` | 新增封面／範圍／overview 參數與工作底稿輸出 | 中 |
| `scripts/md_to_pdf.py` | 封面頁、目錄、章節強制分頁 | 中 |
| `references/severity_grading.md` | 整案等級降格為內部閘門；三欄位模型 | 中 |
| `SKILL.md` | 四步變三步；Step 2 新欄位要求；overview 產出要求 | 中 |
| `README.md` | 撤回非 Claude 承諾；流程表；兩份文件說明 | 中 |
| `test-fixtures/*/security-scan-report/` | 兩組樣本的 classification 遷移與報告重產 | 中 |

Task 順序理由：先建立回歸基準（Task 1，因為 repo 沒有 test suite，之後每一步都要有東西可 diff）→ 再改 schema 與驗證層（Task 2，這是所有下游的資料契約）→ 補齊新資料來源（Task 3 review、Task 4 scope）→ 才動輸出層（Task 5 最大、依賴前四者）→ PDF 版面（Task 6）→ CLI 接線（Task 7）→ 文件（Task 8）→ fixture 重產與收尾（Task 9）。

---

### Task 1: 建立回歸基準

**Files:**
- Create: `scripts/regen_fixtures.sh`
- Create: `test-fixtures/GOLDEN_NOTES.md`

**Interfaces:**
- Consumes: 無（第一個 Task）
- Produces: `scripts/regen_fixtures.sh`（後續每個 Task 的驗證步驟都呼叫它）、`/tmp/sck-baseline/` 底下的基準輸出。腳本的參數與輸出路徑約定不可改動。

- [ ] **Step 1: 確認兩組 fixture 可以離線重產報告**

fixture 目錄已含 `results_before.json`／`results_after.json`／`classification.json`／`scan_env.json`，因此不需要安裝 slither 或跑 forge 就能重跑 Step 4。先確認：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in timelock-vault vulnerable-vault; do
  ls test-fixtures/$f/security-scan-report/{results_before.json,results_after.json,classification.json,scan_env.json}
done
```

四個檔案都存在才能繼續。`vulnerable-vault` 若缺 `results_after.json`（該樣本 Step 3 未執行），記下這件事——Task 5 移除 before/after 對照後它就不再需要。

- [ ] **Step 2: 寫 `scripts/regen_fixtures.sh`**

```bash
#!/usr/bin/env bash
# Regenerate both regression fixtures' reports into a throwaway directory so a
# change to the report layer can be diffed against a known-good baseline.
# Usage: scripts/regen_fixtures.sh <out-root>
#   e.g. scripts/regen_fixtures.sh /tmp/sck-baseline
set -uo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?usage: regen_fixtures.sh <out-root>}"
rm -rf "$OUT"; mkdir -p "$OUT"
for f in timelock-vault vulnerable-vault; do
  SRC="$KIT/test-fixtures/$f/security-scan-report"
  AFTER="$SRC/results_after.json"; [ -f "$AFTER" ] || AFTER="$SRC/results_before.json"
  mkdir -p "$OUT/$f"
  python3 "$KIT/scripts/cli.py" report \
    --before "$SRC/results_before.json" \
    --after "$AFTER" \
    --classification "$SRC/classification.json" \
    --env "$SRC/scan_env.json" \
    --out-dir "$OUT/$f" --skip-pdf > "$OUT/$f/stdout.txt" 2> "$OUT/$f/stderr.txt"
  echo "$f exit=$?" >> "$OUT/exit_codes.txt"
done
cat "$OUT/exit_codes.txt"
```

`chmod +x scripts/regen_fixtures.sh`。

**注意**：Task 5 之後 `--after` 參數會被移除，屆時本腳本要同步改（Task 5 Step 8 會處理）。`--skip-pdf` 是刻意的——回歸比對只需要 markdown，PDF 另由 Task 6 目視驗證。

- [ ] **Step 3: 產出基準並存檔**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
scripts/regen_fixtures.sh /tmp/sck-baseline
cp -r /tmp/sck-baseline /tmp/sck-baseline-frozen
```

預期輸出：`timelock-vault exit=0`、`vulnerable-vault exit=4`。**這兩個 exit code 是整個計畫的迴歸紅線**——第 9 個 Task 結束時必須仍然是 0 與 4。若這一步就對不上，停下來查環境（很可能是 `fpdf2`／`matplotlib` 沒裝在 `cli.py report` 探測到的 python 上），不要繼續。

- [ ] **Step 4: 寫 `test-fixtures/GOLDEN_NOTES.md`**

記錄基準的三個不變量，之後每個 Task 都對照這份：

```markdown
# 回歸基準（golden）

`scripts/regen_fixtures.sh <out-root>` 會離線重產兩組樣本的 `report.md`（不需 slither／forge）。

## 不變量（改版全程不得改變）

| 樣本 | exit code | Tier | 理由 |
|---|---|---|---|
| timelock-vault | 0 | 第二級 | 有 B 類、無 A/D、無非誤報 High |
| vulnerable-vault | 4 | 第四級 | 有非誤報 High + Critical 人工發現 |

## 會改變的（改版預期差異）

- `report.md` 的章節結構、標題、頁數、findings 編號格式。
- 「工具原始輸出 vs 交付版掃描結果」對照表與圖表會消失。
- 整案等級那句話會從本文消失（浮水印保留）。

## 使用方式

改動 `scripts/` 底下任何檔案後：

```bash
scripts/regen_fixtures.sh /tmp/sck-check
diff <(grep '^exit=' -r /tmp/sck-check/exit_codes.txt) <(grep '^exit=' -r /tmp/sck-baseline-frozen/exit_codes.txt)
```

exit code 有差異就是 regression，除非該 Task 明確說要改。
```

- [ ] **Step 5: 驗證腳本可重複執行**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
scripts/regen_fixtures.sh /tmp/sck-check
diff -r /tmp/sck-check /tmp/sck-baseline-frozen && echo "IDEMPOTENT OK"
```

若 diff 出現差異，檢查是不是 `scan_env.json` 裡的 timestamp 被寫進報告造成的——是的話沒關係（報告本來就印掃描時間），但要在 `GOLDEN_NOTES.md` 註明「diff 時忽略含時間戳的那幾行」，並改用 `diff -r -I '^\(掃描時間\||\s*掃描時間\)'`。

- [ ] **Step 6: Commit**

```bash
git add scripts/regen_fixtures.sh test-fixtures/GOLDEN_NOTES.md
git commit -m "$(cat <<'EOF'
Add an offline fixture regeneration harness as the report redesign baseline

The repo has no test suite; the two regression fixtures are the only gate on
report-layer changes. Both carry their full Step 1/2 artifacts, so reports can
be rebuilt without slither or forge. Freeze the current output and the two
exit codes (0 / 4) as the invariant the redesign must preserve.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: schema 擴充與驗證層

**Files:**
- Modify: `scripts/build_report.py`
- Modify: `test-fixtures/timelock-vault/security-scan-report/classification.json`
- Modify: `test-fixtures/vulnerable-vault/security-scan-report/classification.json`

**Interfaces:**
- Consumes: Task 1 的 `regen_fixtures.sh`
- Produces: 下游全部依賴的資料契約——欄位名 `id`／`scan_id`／`source`／`severity`／`severity_rationale`／`remediation`／`confirm_what`／`confirm_who`／`confirm_branches`，頂層鍵 `scenario_coverage`／`scope_exclusion_reasons`，以及常數 `INDUSTRY_SEVERITIES`。**拼法不可改動**，Task 3/4/5/7 全部引用。

- [ ] **Step 1: 在 `build_report.py` 新增常數與 schema 定義**

在既有 `VALID_CATEGORIES` 附近加入：

```python
# The industry-standard severity scale the delivery report presents. Distinct
# from `impact`, which stays verbatim-equal to Slither's own output and is the
# ONLY field the delivery gate reads — a human downgrade must never be able to
# make a Slither High disappear from the gate's view.
INDUSTRY_SEVERITIES = ["Critical", "High", "Medium", "Low", "Informational"]
INDUSTRY_SEVERITY_RANK = {s: i for i, s in enumerate(INDUSTRY_SEVERITIES)}
# Findings carry one unified id across both sources (see decision 6 in the
# spec); `scan_id` keeps the original scan-order index for rescan matching and
# is deliberately never rendered.
VALID_SOURCES = {"tool", "manual"}
# Which severity the report groups a finding under when rendering: `severity`
# always, falling back is NOT allowed — a missing severity is a hard error.
```

- [ ] **Step 2: 擴充驗證函式**

在既有的 classification 驗證流程（產生 exit 2 錯誤清單的那一段）新增以下每一條，錯誤訊息格式沿用既有風格（`f"[{ident}] ..."`）：

| 檢查 | 條件 | 錯誤訊息要點 |
|---|---|---|
| `severity` 必填且合法 | 不在 `INDUSTRY_SEVERITIES` 內 | 列出允許值 |
| `severity_rationale` | `INDUSTRY_SEVERITY_RANK[severity] > IMPACT_RANK[impact]`（即人工判得比工具輕）時必填非空 | 明說「降級必須附理由」 |
| `remediation` | `category == "A"` 時必填非空 | |
| D 類三格 | `category == "D"` 時 `confirm_what`／`confirm_who`／`confirm_branches` 皆必填非空 | 逐格列出缺哪一格 |
| `id` 格式 | 必須 match `^[A-Z]{2,6}-\d{2,}$` | 給出範例 `BGT-01` |
| `id` 唯一 | 跨 `findings[]` + `manual_findings[]` 不得重複 | 列出重複的 id |
| `source` | 必須在 `VALID_SOURCES`；`findings[]` 恆為 `tool`，`manual_findings[]` 恆為 `manual` | |

**IMPACT_RANK 的定義**：`impact` 用 `IMPACT_ORDER` 的索引，但兩套尺規要能比較——`Optimization`/`Informational` 對應 industry 的 `Informational`。寫一個明確的映射表而不是靠索引硬算：

```python
# Slither impact -> the industry severity it is considered equivalent to, for
# the sole purpose of detecting a human DOWNGRADE (which requires a rationale).
# An upgrade (e.g. Slither Low -> our High) needs no rationale: raising the
# stakes is never the direction abuse comes from.
IMPACT_AS_INDUSTRY = {
    "High": "High", "Medium": "Medium", "Low": "Low",
    "Informational": "Informational", "Optimization": "Informational",
}
```

- [ ] **Step 3: 新增頂層鍵的驗證（皆為選填，但格式錯要擋）**

- `scenario_coverage`：若存在，必須是 `{"contracts": [{"file": str, "checked": [str], "not_applicable": [str], "hits": [str]}]}`。`hits` 內的每個值必須是存在的 finding `id`（對不上就是 error）。
- `scope_exclusion_reasons`：若存在，必須是 `{prefix: reason}` 的字串對字串 dict。

- [ ] **Step 4: 遷移兩組 fixture 的 classification.json**

用一支一次性腳本遷移，不要手改（timelock 5 筆、vulnerable 19 筆 + manual）：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
python3 - <<'PY'
import json, pathlib
PREFIX = {"timelock-vault": "TLV", "vulnerable-vault": "VLV"}
IMPACT_AS_INDUSTRY = {"High":"High","Medium":"Medium","Low":"Low",
                      "Informational":"Informational","Optimization":"Informational"}
for name, pfx in PREFIX.items():
    p = pathlib.Path(f"test-fixtures/{name}/security-scan-report/classification.json")
    c = json.loads(p.read_text())
    n = 0
    for f in c.get("findings", []):
        n += 1
        f["scan_id"] = f["id"]; f["id"] = f"{pfx}-{n:02d}"; f["source"] = "tool"
        # Straight carry-over: no judgement is being made during migration, so
        # severity starts equal to the tool's impact and no rationale is needed.
        f["severity"] = IMPACT_AS_INDUSTRY[f["impact"]]
        if f["category"] == "A" and not f.get("remediation"):
            f["remediation"] = "（遷移佔位：需補修復建議）"
        if f["category"] == "D":
            f.setdefault("confirm_what", "（遷移佔位）")
            f.setdefault("confirm_who", "（遷移佔位）")
            f.setdefault("confirm_branches", "（遷移佔位）")
    for m in c.get("manual_findings", []):
        n += 1
        m["scan_id"] = None; m["id"] = f"{pfx}-{n:02d}"; m["source"] = "manual"
        m["severity"] = m.pop("severity", None) or "Medium"
        if m["category"] == "A" and not m.get("remediation"):
            m["remediation"] = "（遷移佔位：需補修復建議）"
        if m["category"] == "D":
            m.setdefault("confirm_what", "（遷移佔位）")
            m.setdefault("confirm_who", "（遷移佔位）")
            m.setdefault("confirm_branches", "（遷移佔位）")
    p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n")
    print(name, "migrated", n, "findings")
PY
```

**注意 `manual_findings` 的 `severity`**：原 schema 已有 `severity` 欄位（Critical–Informational），遷移時原值直接留用，不要覆寫。上面的 `pop`/`or` 寫法保留原值，只在缺值時給 `Medium`——遷移後要人工檢查 `vulnerable-vault` 的 M1/M2 是否仍是 `Critical`。

遷移完把佔位字串列出來，這是 Task 9 的待清項目：

```bash
grep -rn "遷移佔位" test-fixtures/*/security-scan-report/classification.json
```

- [ ] **Step 5: 驗證 exit code 未變**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
scripts/regen_fixtures.sh /tmp/sck-check
cat /tmp/sck-check/exit_codes.txt
```

必須仍是 `timelock-vault exit=0` / `vulnerable-vault exit=4`。若變成 2，讀 stderr 逐條修——這一步的意義就是證明新驗證規則不會誤擋合法輸入。

- [ ] **Step 6: 驗證新驗證規則真的會擋**

刻意做壞再確認擋得住（測完還原）：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
cp test-fixtures/timelock-vault/security-scan-report/classification.json /tmp/tlv.bak
python3 - <<'PY'
import json
p="test-fixtures/timelock-vault/security-scan-report/classification.json"
c=json.load(open(p)); c["findings"][0]["severity"]="Informational"  # downgrade, no rationale
c["findings"][0].pop("severity_rationale",None)
json.dump(c,open(p,"w"),ensure_ascii=False,indent=2)
PY
python3 scripts/cli.py report --before test-fixtures/timelock-vault/security-scan-report/results_before.json \
  --after test-fixtures/timelock-vault/security-scan-report/results_after.json \
  --classification test-fixtures/timelock-vault/security-scan-report/classification.json \
  --env test-fixtures/timelock-vault/security-scan-report/scan_env.json \
  --out-dir /tmp/sck-negative --skip-pdf; echo "exit=$?"
cp /tmp/tlv.bak test-fixtures/timelock-vault/security-scan-report/classification.json
```

預期 `exit=2`，stderr 明確指出缺 `severity_rationale`。**若得到 0，驗證規則沒接上，不要繼續。**

- [ ] **Step 7: Commit**

```bash
git add scripts/build_report.py test-fixtures/*/security-scan-report/classification.json
git commit -m "$(cat <<'EOF'
Add severity/remediation/id fields to the classification schema

impact stays verbatim-equal to the scan output and remains the only field the
delivery gate reads, so a human downgrade can change presentation but never
the gate. severity (industry five-level) is now required, a downgrade requires
severity_rationale, A needs remediation, and D needs the three confirmation
fields. Findings get one unified id across both sources.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `cli.py review` 子指令

**Files:**
- Create: `scripts/review.py`
- Modify: `scripts/cli.py`

**Interfaces:**
- Consumes: Task 2 的 schema 欄位名
- Produces: `cli.py review` 子指令（Task 8 的 `SKILL.md`／`README.md` 會引用它）。exit code 語意：`0` = 無待抽查項目、`1` = 有待抽查項目（**警告，非錯誤**）、`2` = 檔案讀不到或 JSON 壞掉。

- [ ] **Step 1: 寫 `scripts/review.py`**

檢查項目（全部是規則式判定，不做任何語意判斷）：

| 檢查 | 條件 | 分級 |
|---|---|---|
| 重複理由 | 2 筆以上共用完全相同的 `dev_note`（strip 後比對），按 detector 分組列出成員 id | 警告 |
| `dev_note` 過短 | strip 後長度 < 40 字元 | 警告 |
| 缺 `remediation` | `category == "A"` 且缺 | 警告（`build_report` 會 exit 2，這裡提前告知） |
| D 類缺三格 | 同上 | 警告 |
| 降級未附理由 | severity 低於 impact 對應等級且缺 `severity_rationale` | 警告 |
| **High 降級** | `impact == "High"` 且 `severity` 不是 `High`/`Critical` | 警告，且**單獨一節列出**（這是決定三「曝光即控制」的落實點） |
| **High 判 C** | `impact == "High"` 且 `category == "C"` | 警告，且單獨一節——附一行提示：這是甲方最可能挑戰的判斷，確認 `dev_note` 不是共用理由 |
| 未分類 | `category` 為空 | 警告 |

輸出格式：純文字，每節一個標題 + 條列，結尾一行總計。`--json` 旗標改輸出結構化結果供工作底稿引用。

**重複理由那一節的文案，從 `build_report.py` 現行的第 8 章原文搬過來**（「共用本身不代表分類錯誤……但這也是模板化理由最容易藏身的地方，請針對每一組抽查至少一筆」），Task 5 會把它從報告移除，文案本身不要重寫。

- [ ] **Step 2: 接進 `cli.py`**

比照既有 `check`／`scan`／`report` 的 subparser 寫法新增：

```
cli.py review --classification <path> [--json]
```

`cli.py --help` 要能列出四個子指令。

- [ ] **Step 3: 驗證能抓出已知的重複理由**

`vulnerable-vault` 的樣本量小，改用 bot-gold-token 的真實分類檔（唯讀，不修改）：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
python3 scripts/cli.py review --classification /tmp/security-scan/classification.json; echo "exit=$?"
```

預期：`exit=1`，且輸出必須包含以下已知事實（用來確認檢查真的跑對）——

- 重複理由 6 組，成員數分別為 6 / 30 / 11 / 16 / 6 / 7。
- 「High 判 C」一節列出 **8 筆**，其中 6 筆是 `uninitialized-state`。

若 `/tmp/security-scan/classification.json` 已不存在，改用 `/Users/kai/BSOS/bot-gold-token/` 底下的副本；兩處都沒有就跳過本步驟並在 commit 訊息註明未實測。

- [ ] **Step 4: 驗證乾淨輸入回 0**

```bash
python3 scripts/cli.py review --classification test-fixtures/timelock-vault/security-scan-report/classification.json; echo "exit=$?"
```

timelock-vault 有 4 筆 `low-level-calls`/`reentrancy-events` 的理由不同、無 A/D 類，預期 `exit=0`。若因為 Task 2 的「遷移佔位」字串而報警，那是正確行為——記進 Task 9 待清清單。

- [ ] **Step 5: Commit**

```bash
git add scripts/review.py scripts/cli.py
git commit -m "$(cat <<'EOF'
Add cli.py review to lint classification.json before the report is built

Moves the shared-dev_note check out of the delivered report, where it fired
after the fact, and into Step 2 where it can still change the outcome. Also
surfaces High findings that were downgraded or dismissed as false positives —
the judgements a client is most likely to challenge.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 掃描範圍產出（`scope.json`）

**Files:**
- Modify: `scripts/scan.py`

**Interfaces:**
- Consumes: Task 2 的頂層鍵 `scope_exclusion_reasons`
- Produces: `<out-dir>/scope.json`，schema 如下。Task 5 的範圍章節與 Task 7 的 `--scope` 參數依賴它。

```jsonc
{
  "src_prefix": "src/",
  "exclude_paths": ["contracts/fake/"],
  "files": [
    {"path": "src/Token.sol", "lines": 214, "sha256": "ab12..."}
  ],
  "totals": {"files": 12, "lines": 3480}
}
```

- [ ] **Step 1: 在 `scan.py` 加 `collect_scope()`**

走訪 `--src-prefix` 底下所有 `.sol`（排除落在 `--exclude-path` 前綴內的），對每檔記 relative path、行數、`sha256`。排序以 path 遞增，確保輸出穩定可 diff。

**邊界情況**：`--full-audit` 時 `src_prefix` 的過濾不套用於發現，但 `scope.json` 仍只記專案自己的檔案——範圍章節要回答的是「我們掃了你的哪些檔案」，不是「slither 解析了幾百個 lib 檔」。這一點在 `collect_scope` 的 docstring 寫清楚。

- [ ] **Step 2: 寫入 `scope.json` 並列進 scan 的輸出清單**

`scan.py` 終端摘要的「寫入檔案」列表要加上 `scope.json`，與既有四個檔案並列。

- [ ] **Step 3: skeleton 加新欄位**

`classification_skeleton.json` 每筆預填加上 `id`（用 `--id-prefix` 參數，預設由 out-dir 或專案目錄名推導出的三字母大寫縮寫）、`scan_id`、`source: "tool"`，並把 `severity` 預填為 `IMPACT_AS_INDUSTRY[impact]`、`severity_rationale` 留空。`remediation`／`confirm_*` 留空字串。

skeleton 頂層加上空的 `scenario_coverage: {"contracts": []}` 與 `scope_exclusion_reasons: {}`，讓 Step 2 的人知道有這兩個欄位要填。

- [ ] **Step 4: 驗證**

```bash
cd /Users/kai/BSOS/SecurityCheckKit/test-fixtures/timelock-vault
python3 ../../scripts/cli.py scan --out-dir /tmp/sck-scope --src-prefix src/ 2>&1 | tail -20
python3 -c "
import json; s=json.load(open('/tmp/sck-scope/scope.json'))
print(s['totals']); print([f['path'] for f in s['files']])
assert all(len(f['sha256'])==64 for f in s['files'])
"
```

預期：`files` 含 `src/TimelockVault.sol`，**不含 `src/TimelockVault.sol.original`**（不是 `.sol` 結尾）。若這個樣本需要 slither 才能跑 scan 而環境沒有，改用直接呼叫 `collect_scope()` 的單元式驗證：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
python3 -c "
import sys; sys.path.insert(0,'scripts')
from scan import collect_scope
s=collect_scope('test-fixtures/timelock-vault','src/',[])
print(s['totals'], [f['path'] for f in s['files']])
"
```

- [ ] **Step 5: 確認 skeleton 新欄位齊備**

```bash
python3 -c "
import json,sys; sys.path.insert(0,'scripts')
k=json.load(open('/tmp/sck-scope/classification_skeleton.json'))
f=k['findings'][0]
for key in ('id','scan_id','source','severity','severity_rationale','remediation'):
    assert key in f, key
assert 'scenario_coverage' in k and 'scope_exclusion_reasons' in k
print('skeleton OK', f['id'], f['severity'])
"
```

- [ ] **Step 6: Commit**

```bash
git add scripts/scan.py
git commit -m "$(cat <<'EOF'
Emit scope.json so the report can state what was actually scanned

A self-check proof with no defined boundary proves nothing: the report has had
no file list, and --exclude-path removals were invisible to the client. Record
every in-scope .sol with its line count and sha256, plus the exclusions, and
pre-fill the new classification fields in the skeleton.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 報告輸出層重寫

**Files:**
- Modify: `scripts/build_report.py`
- Modify: `scripts/regen_fixtures.sh`

**Interfaces:**
- Consumes: Task 2 的 schema、Task 4 的 `scope.json`、新增的 `--overview` markdown
- Produces: 新的 `report.md` 章節骨架（Task 6 的 PDF 分頁規則依賴章節標題文字）、`worksheet.md`（Task 7 寫入 `audit/`）

這是最大的 Task。**驗證層（reconcile、`compute_grade`、exit code）完全不動**，只改「結果印在哪裡」。

- [ ] **Step 1: 新增輸入參數**

`build_report.py` 新增（全部選填，缺了就在對應章節印「未提供」而不是報錯，比照現行 `--classification`／`--env` 的處理）：

| 參數 | 用途 |
|---|---|
| `--scope <scope.json>` | 範圍章節 |
| `--overview <md>` | 協定理解摘要，內容**逐字內嵌**（由 skill 撰寫，CLI 不生成散文） |
| `--client <name>` | 封面 |
| `--engagement-from` / `--engagement-to` | 封面的期間，取代現行的瞬間 timestamp |
| `--worksheet <path>` | 工作底稿輸出路徑；給了才產 |

**移除** `--after`。相關的 `results_after` 讀取、差異計算、`severity_chart.png` 的雙欄長條圖一併刪除。

- [ ] **Step 2: 章節骨架重寫**

新 `report.md` 的章節順序與標題（**標題不帶編號**，Task 6 依這些字串做分頁）：

```
# <客戶名> 智能合約安全檢測報告      ← 封面資訊塊
## 目錄
## 摘要
## 掃描範圍
## 協定理解摘要
## 檢測方法
## 情境庫覆蓋
## 待處理項目
## 發現明細
## 已評估項目摘要
## 附錄：發現處置分類
```

刪除的章節：摘要統計的 before/after 表、掃描結果對照圖表、複核提醒、完整分類明細（四個 A/B/C/D 小節）、附錄一待人工確認清單、附錄二的整案等級定義段落。

- [ ] **Step 3: 各章節的渲染規則**

**摘要**：專案一句話定位（取 `--overview` 的第一段，或無則省略）、engagement 期間、repo + commit、findings 總數、**severity 計數表（業界五級，用 `severity` 欄位統計）**。整案等級那句話刪除。

**掃描範圍**：檔案清單表（path / 行數）＋ 排除清單表（prefix / 理由，理由取自 `scope_exclusion_reasons`，缺理由印「未註明」）。檔案 sha256 以**小字放章節末尾**——markdown 沒有字級，用 `<sub>` 或縮排的 code block 呈現，PDF 端由 Task 6 用較小字級渲染。

**協定理解摘要**：`--overview` 的內容逐字內嵌。缺則印「未提供（本次未產出協定理解摘要）」。

**檢測方法**：改寫成編號步驟，明寫三層：Slither 靜態掃描 → L1–L19 情境庫逐合約比對 → 領域事故庫比對。範圍限制聲明（現行第 3 章那三條）移到本章末尾。

**情境庫覆蓋**：壓縮版矩陣，一列一合約：

| 合約 | 已查證情境 | 不適用 | 命中 |
|---|---|---|---|
| contracts/GoldMarket.sol | 14 | 5 | BGT-05, BGT-07 |

資料取自 `scenario_coverage`；缺則印「未提供」，並在該節加一行：本報告的檢測方法宣稱執行了情境庫比對，但未附覆蓋紀錄。（**這行刻意刺眼**——宣稱了卻無證據比不宣稱更糟，見 spec。）

**待處理項目**：`category` 為 A 或 D 的全部 findings（含 manual），單一編號、按 `severity` 排序。欄位：編號 / 標題 / Severity / 工具 impact / Status。

**發現明細**：收錄 `category == "A"`、全部 `source == "manual"`、以及 **`severity` 為 High/Critical/Medium 的 B 與 C**。每筆固定三段：

```markdown
### <id>｜<標題>

| | |
|---|---|
| Severity | Medium（工具 impact：High） |
| Status | 待處理 |
| 位置 | contracts/GoldMarket.sol:123-140 |
| 處置 | 已知風險但可接受（B） |

**說明**：<description>

**影響**：<dev_note 中的影響段，或 description 的後半>

**建議**：<remediation；D 類改印「待確認事項」三格>
```

Severity 那一格**必須並列印出兩個值**（決定三第 3 條），若有 `severity_rationale` 接在後面一行。

**已評估項目摘要**：`severity` 為 Low/Informational 的 B 與 C，一張 detector 摘要表：

| Detector | 筆數 | 處置 | 理由摘要 |
|---|---|---|---|
| naming-convention | 207 | C（誤報） | 純風格檢查，無安全含義 |

同 detector 同處置的合併成一列，理由取該組第一筆的 `dev_note` 首句。表下加一行：完整逐筆明細見工作底稿。

**附錄：發現處置分類**：只留 A/B/C/D 的定義（現行附錄二的前半），整案等級那半段刪除。

- [ ] **Step 4: 自動預分類與沿用的揭露**

`auto_classified == "style"` 與 `carried_from_previous` 的項目，在「已評估項目摘要」的表格加一欄或在理由摘要後加標記，並在摘要章的 severity 計數表下方加一行總計：

> 本次 N 筆由風格預分類自動判定（非人工逐筆判讀）、M 筆沿用前次分類（判定日期 YYYY-MM-DD）。

這是 spec 開頭列的三個洞之一（「逐筆人工判讀的宣稱有水分」），別漏掉。

- [ ] **Step 5: 浮水印保留、等級文字移除**

`render_internal_banner` 保留，但文案中的「本報告資安等級為：第X級」改成不提級數的版本：

> **【內部工作版本 — 不可作為交付文件】**
> 本報告尚有未完成處理或待確認之項目，僅供工程團隊追蹤使用；請於完成處理後重新產出報告，方可交付。

`compute_grade` 的結果只用於決定「要不要印浮水印」與 exit code，不再印出級數。

- [ ] **Step 6: 工作底稿產出**

`--worksheet <path>` 給定時，寫一份 `worksheet.md` 含：全量 110 筆逐筆明細（現行第 9 章的四個小節原樣）、`cli.py review` 的完整輸出、完整版覆蓋矩陣（合約 × L1–L19 全欄）、自動預分類與沿用的逐筆標記。

**不轉 PDF**，也不寫進 `--out-dir`（那是交付目錄）。

- [ ] **Step 7: 圖表處理**

`severity_chart.png` 從「before/after 雙欄長條圖」改成「按 severity 分佈的單欄圖」，或直接移除。**建議移除**——本案那張圖畫了兩根等高的柱子佔掉一整頁，改成單欄後資訊量等同摘要那張表，重複。移除時 `matplotlib` 相依也可以從 Task 8 的文件裡拿掉。

若決定保留，圖表章節併入摘要章，不單獨成節。

- [ ] **Step 8: 更新 `regen_fixtures.sh`**

移除 `--after` 參數；加上 `--scope`（fixture 沒有 `scope.json`，先不傳，驗證「缺了印未提供」的路徑）。

- [ ] **Step 9: 驗證 exit code 未變**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
scripts/regen_fixtures.sh /tmp/sck-check
cat /tmp/sck-check/exit_codes.txt
```

必須是 `0` 與 `4`。這是整個 Task 最重要的一步——輸出層重寫不得影響閘門。

- [ ] **Step 10: 驗證新章節齊備、舊章節消失**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in timelock-vault vulnerable-vault; do
  echo "=== $f"
  grep '^## ' /tmp/sck-check/$f/report.md
done
```

預期出現：目錄／摘要／掃描範圍／協定理解摘要／檢測方法／情境庫覆蓋／待處理項目／發現明細／已評估項目摘要／附錄。
預期**不出現**：`複核提醒`、`完整分類明細`、`附錄一`、`掃描結果對照圖表`。

```bash
grep -c '第[一二三四]級' /tmp/sck-check/vulnerable-vault/report.md
```

預期 `0`（等級文字已從本文移除），但浮水印那塊仍在：

```bash
grep -c '內部工作版本' /tmp/sck-check/vulnerable-vault/report.md   # 預期 >= 1
```

- [ ] **Step 11: 驗證頁數目標**

```bash
python3 -c "
t=open('/tmp/sck-check/vulnerable-vault/report.md').read()
print('chars', len(t))
"
```

vulnerable-vault 現行 report.md 產出 34 頁 PDF。fixture 樣本小（19 筆），改版後應該明顯更短。真正的頁數驗證要等 Task 6 產 PDF，這裡只記錄字元數當基準。

- [ ] **Step 12: Commit**

```bash
git add scripts/build_report.py scripts/regen_fixtures.sh
git commit -m "$(cat <<'EOF'
Rewrite the report output layer around the reader, not the pipeline

Delivered reports were 77% B/C/D dump and stated three contradicting High
counts. Restructure to an industry audit layout: scope with a file list,
protocol overview, numbered methodology, scenario coverage, findings with a
required remediation, and a one-page detector summary for the Low/Info tail.
Full detail moves to the worksheet. The gate, reconciliation and exit codes
are untouched; the tier now only decides whether the watermark prints.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: PDF 封面、目錄與分頁

**Files:**
- Modify: `scripts/md_to_pdf.py`

**Interfaces:**
- Consumes: Task 5 的章節標題字串
- Produces: 交付版 PDF 版面

- [ ] **Step 1: 封面頁**

第一頁只放：客戶名、報告標題、engagement 期間、執行單位、（若為內部版）浮水印區塊。**不放具名簽名欄位**（決定七）。之後 `pdf.add_page()` 開始正文。

**踩過的雷要遵守**：`references/pitfalls.md` #6 記載 `fpdf2` 2.8.7 會把封面短 ASCII 文字靜默畫成亂碼。實作後**務必實際打開 PDF 目視確認封面**，並確認執行環境的 `fpdf2` >= 2.8.8：

```bash
python3 -c "import fpdf; print(fpdf.__version__)"
```

- [ ] **Step 2: 目錄頁**

掃描 `report.md` 的 `## ` 與 `### ` 標題產生目錄。`### ` 層級只收「發現明細」底下的 finding 標題（比照 Dyson 的 TOC 列出每筆 finding）。頁碼：fpdf2 無法在單次 pass 得知頁碼，用兩段式——先渲染一次收集標題落在哪一頁，再重新渲染並填入頁碼。若實作成本過高，**第一版可以不放頁碼**，只列標題順序，並在 `GOLDEN_NOTES.md` 記為已知簡化。

- [ ] **Step 3: 章節強制分頁**

每個 `## ` 標題前插入 `pdf.add_page()`（第一個除外）。

**踩過的雷**：`pitfalls.md` #5——畫完表格接著寫段落前必須 `pdf.set_x(pdf.l_margin)`。分頁邏輯改動後要重新確認這個修法沒被繞過。

- [ ] **Step 4: 範圍章節末尾的 sha256 小字**

用比正文小一級的字級渲染該區塊（例如正文 10pt → 7pt）。

- [ ] **Step 5: 驗證**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
scripts/regen_fixtures.sh /tmp/sck-pdf   # 先把 --skip-pdf 拿掉再跑，或手動跑一次 report
python3 scripts/md_to_pdf.py /tmp/sck-check/vulnerable-vault/report.md /tmp/sck-check/vulnerable-vault/report.pdf
pdftotext -layout /tmp/sck-check/vulnerable-vault/report.pdf /tmp/ours-new.txt
grep -c $'\f' /tmp/ours-new.txt   # 頁數
head -20 /tmp/ours-new.txt        # 封面內容
```

三個確認點：頁數應明顯少於原本的 34；封面文字正確無亂碼（**目視打開 PDF，不要只信 pdftotext**，2.8.7 的 bug 是 glyph 錯而底層文字對）；每個 `## ` 章節都從新頁開始。

- [ ] **Step 6: Commit**

```bash
git add scripts/md_to_pdf.py
git commit -m "$(cat <<'EOF'
Add a cover page, table of contents and per-section page breaks

Matches the layout of the third-party audit reports this tool is compared
against. The cover carries the client, engagement window and executing party —
deliberately no named signature field, since nobody reviews the generated
prose page by page.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: CLI 接線與工作底稿路徑

**Files:**
- Modify: `scripts/report.py`
- Modify: `scripts/cli.py`

**Interfaces:**
- Consumes: Task 5 的 `build_report.py` 參數、Task 4 的 `scope.json`
- Produces: `cli.py report` 的最終介面（Task 8 的文件依此寫）

- [ ] **Step 1: 參數透傳**

`report.py` 把 Task 5 新增的參數全部透傳：`--scope`／`--overview`／`--client`／`--engagement-from`／`--engagement-to`／`--worksheet`。移除 `--after`。

- [ ] **Step 2: 工作底稿預設路徑**

`--worksheet` 未給時，預設寫到 `<專案根>/audit/worksheet.md`（與 `AUDIT_NOTES.md`／`DOMAIN_RESEARCH.md` 同層）。專案根從 `--out-dir` 的父目錄推導。目錄不存在時建立。

**加一個 gitignore 提示**：若 `audit/` 未被 gitignore（檢查 `git check-ignore audit/worksheet.md`），在終端機印出警告——工作底稿含內部語氣，不該隨程式碼交付。**只警告，不自動改 `.gitignore`**（那是客戶專案的檔案，不是我們的）。

- [ ] **Step 3: 終端機回報改寫**

`cli.py report` 結束時的回報內容改成：
- `report.pdf` 路徑
- `worksheet.md` 路徑
- **閘門結果**：可交付 / 不可交付（**不印級數**，與報告本文一致）
- 卡住閘門的項目編號清單
- 當次掃描的 findings 總數（不再有 before/after 對比）

- [ ] **Step 4: 驗證完整指令可跑**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
python3 scripts/cli.py report \
  --before test-fixtures/timelock-vault/security-scan-report/results_before.json \
  --classification test-fixtures/timelock-vault/security-scan-report/classification.json \
  --env test-fixtures/timelock-vault/security-scan-report/scan_env.json \
  --client "測試客戶" --engagement-from 2026-08-01 --engagement-to 2026-08-14 \
  --out-dir /tmp/sck-full --worksheet /tmp/sck-full-worksheet.md
echo "exit=$?"
ls -la /tmp/sck-full/ /tmp/sck-full-worksheet.md
head -12 /tmp/sck-full/report.md
```

預期 `exit=0`，`report.md`／`report.pdf`／`worksheet.md` 三個都在，封面塊含「測試客戶」與期間。

- [ ] **Step 5: 驗證 `--after` 已移除**

```bash
python3 scripts/cli.py report --help | grep -c '\-\-after'   # 預期 0
```

- [ ] **Step 6: Commit**

```bash
git add scripts/report.py scripts/cli.py
git commit -m "$(cat <<'EOF'
Wire the cover, scope and worksheet parameters through cli.py report

Drops --after: the report now shows the current scan only, so the pre/post
suppression comparison no longer has a consumer. The worksheet defaults into
audit/ alongside the other internal notes, and the run warns when that path
is not gitignored.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 文件更新

**Files:**
- Modify: `references/severity_grading.md`
- Modify: `SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2–7 的最終介面
- Produces: 對外一致的流程說明

- [ ] **Step 1: `references/severity_grading.md`**

改動範圍：

- 開頭「背景」段：整案等級的定位從「放在報告最前面的 Executive Summary」改成「**僅驅動 exit code 與內部版浮水印，不出現在報告本文**」。
- 新增一節「三個正交欄位」，說明 `impact`（工具、唯讀、閘門依據）／`severity`（人工、業界五級、報告呈現）／`status`（處置進度）的分工，以及**閘門為什麼算在 `impact` 而不是 `severity`**（繞過閘門的成本不能從「修好程式碼」降為「寫一段理由」）。
- 「輸入資料」段的 `impact` 說明保留（唯讀規則不變），加上 `severity` 的說明。
- 「落實方式」段移除「報告本文僅顯示級數」那條，改為「報告本文不顯示級數」。
- 「之後可能調整的方向」加一條：降級管制機制（幅度限制／第二人複核／強制引用緩解措施行號）暫不實作，目前靠「閘門算 impact + 兩欄並列曝光」控制；若發現降級被濫用再加。

**不要改** Tier 1–4 的判定條件表本身。

- [ ] **Step 2: `SKILL.md`**

- **四步變三步**：Step 3（加抑制註解）從編號流程移出，改寫成獨立小節「選配：抑制註解（降低後續 CI 雜訊）」，明說它與報告無關、外部標的不適用、跳過是正常的。原 Step 4 變 Step 3。
- Step 2 新增欄位要求：`severity`（必填）／`severity_rationale`（降級時必填）／`remediation`（A 類必填）／`confirm_what`/`confirm_who`/`confirm_branches`（D 類必填）／統一 `id`。
- Step 2 新增產出要求：`scenario_coverage`（覆蓋矩陣）與 `scope_exclusion_reasons`。
- Step 2 結束前新增一步：跑 `cli.py review`，把輸出列給使用者，**特別是「High 降級」與「High 判 C」兩節**。
- 新增「協定理解摘要」的產出要求：從 `audit/AUDIT_NOTES.md` 的資產托管地圖與特權角色權限表，改寫成對外語氣的 markdown 存成 `audit/overview.md`，用 `--overview` 傳給 report。明說這是唯一需要額外人力的產出。
- Step 4（現 Step 3）的指令範例更新成 Task 7 的完整參數形式。
- 最後的回報清單：移除「工具原始輸出 vs 交付版數量對比」、移除「資安等級」，改為「閘門結果（可交付／不可交付）」。

- [ ] **Step 3: `README.md`**

- **撤回非 Claude 承諾**：第二層的說明從「不用 Claude Code 的同仁可以照 `SKILL.md` 的分類標準手動填 `classification.json`，一樣能走完整個流程」改成明確的分工說明——Step 2 需要 LLM 輔助（逐合約跑完 L1–L19、領域比對、逐筆引用行號的理由，本工具實測案例達 110 筆）；Step 1/4 是純確定性 CLI，可獨立於 Claude 執行並接入 CI。
- 架構圖：加 `scripts/review.py`。
- 流程對照表：四列變三列（Step 3 移到表下的註解）。
- 新增一節「兩份產出物」：交付報告（PDF，`security-scan-report/`）vs 工作底稿（`audit/worksheet.md`，gitignore）。
- CLI 子指令細節：新增 `cli.py review`；`cli.py scan` 加 `scope.json`；`cli.py report` 更新參數與移除 `--after`。
- 若 Task 5 Step 7 移除了圖表，把「環境安裝」裡的 `matplotlib` 拿掉。

- [ ] **Step 4: 交叉引用檢查**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
# 不該再有 --after 的引用
grep -rn '\-\-after' --include='*.md' . | grep -v docs/superpowers
# 不該再有「不用 Claude Code ... 走完整個流程」的承諾
grep -rn '一樣能走完整個流程' README.md
# review 子指令要在三處被提到
grep -c 'cli.py review' SKILL.md README.md
# Step 3 不該再被稱為編號步驟
grep -n 'Step 3' SKILL.md
```

前兩個 grep 應無輸出；`cli.py review` 在 `SKILL.md` 與 `README.md` 各至少一次。

- [ ] **Step 5: Commit**

```bash
git add references/severity_grading.md SKILL.md README.md
git commit -m "$(cat <<'EOF'
Demote the case-level tier to an internal gate and retract the no-Claude claim

The tier now only drives the exit code and the internal-draft watermark; the
report body carries an industry severity count instead. Suppression comments
move out of the numbered flow — they are CI hygiene, not audit practice, and
never applied to third-party targets anyway. Step 2 needs an LLM; saying
otherwise protected a user who does not exist.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: fixture 重產與收尾

**Files:**
- Modify: `test-fixtures/timelock-vault/security-scan-report/*`
- Modify: `test-fixtures/vulnerable-vault/security-scan-report/*`
- Modify: `test-fixtures/*/FIXTURE_NOTES.md`、`test-fixtures/vulnerable-vault/VULNERABILITY_CATALOG.md`（僅若引用了已改的章節名）
- Modify: `test-fixtures/GOLDEN_NOTES.md`

**Interfaces:**
- Consumes: 全部前置 Task
- Produces: 兩份可交付的範例報告（`README.md` 底部連結指向它們）

- [ ] **Step 1: 清掉遷移佔位字串**

Task 2 留下的 `（遷移佔位：需補修復建議）` 與 `（遷移佔位）` 要換成真內容。兩組樣本的漏洞明細已寫在 `VULNERABILITY_CATALOG.md` 與 `FIXTURE_NOTES.md`，據此補：

```bash
cd /Users/kai/BSOS/SecurityCheckKit
grep -rn "遷移佔位" test-fixtures/
```

補完後這個 grep 必須無輸出。

- [ ] **Step 2: 補 fixture 的新資料**

兩組樣本各補：
- `scope_exclusion_reasons`：兩組都沒有 exclude path，填 `{}`。
- `scenario_coverage`：依 `FIXTURE_NOTES.md`／`VULNERABILITY_CATALOG.md` 已記錄的情境對照填寫（`vulnerable-vault` 的 M1–M4 已標了 L1／L2 等情境編號，直接用）。
- 產一份 `scope.json`（用 Task 4 的 `collect_scope`）。
- 各寫一份最小的 `audit/overview.md`——**注意 fixture 是測試夾具不是真專案**，overview 寫兩三句說明這是刻意設計的測試合約即可，不要編造業務背景。

- [ ] **Step 3: 重產兩份報告到 fixture 目錄**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in timelock-vault vulnerable-vault; do
  D=test-fixtures/$f/security-scan-report
  python3 scripts/cli.py report \
    --before $D/results_before.json --classification $D/classification.json \
    --env $D/scan_env.json --scope $D/scope.json \
    --overview test-fixtures/$f/audit/overview.md \
    --client "（測試夾具）" --engagement-from 2026-08-14 --engagement-to 2026-08-14 \
    --out-dir $D --worksheet test-fixtures/$f/audit/worksheet.md
  echo "$f exit=$?"
done
```

預期 `timelock-vault exit=0`、`vulnerable-vault exit=4`。

- [ ] **Step 4: 刪除不再產出的檔案**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
git rm test-fixtures/*/security-scan-report/results_after.json   # 若 Task 5 移除 before/after 後已無消費者
git rm test-fixtures/*/security-scan-report/severity_chart.png   # 若 Task 5 Step 7 移除圖表
```

**先確認沒有其他檔案引用它們**：

```bash
grep -rn 'results_after\|severity_chart' --include='*.md' --include='*.py' . | grep -v docs/superpowers
```

`timelock-vault` 的 `src/TimelockVault.sol.original` 與抑制註解版本**保留**——Step 3 雖然移出編號流程，這組樣本仍是它的唯一範例。`FIXTURE_NOTES.md` 要加一句說明 Step 3 現在是選配。

- [ ] **Step 5: 頁數與內容驗收**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
for f in timelock-vault vulnerable-vault; do
  echo "=== $f"
  pdftotext -layout test-fixtures/$f/security-scan-report/report.pdf /tmp/$f.txt
  echo "pages: $(grep -c $'\f' /tmp/$f.txt)"
  grep '^## ' test-fixtures/$f/security-scan-report/report.md
done
```

驗收條件：
- 章節齊備、舊章節消失（同 Task 5 Step 10）。
- `vulnerable-vault` 頁數明顯少於改版前的 34 頁。
- **目視打開兩份 PDF**確認封面無亂碼（`pitfalls.md` #6）。

- [ ] **Step 6: 更新 `GOLDEN_NOTES.md`**

把「會改變的」那一節改成已完成的事實記錄，並記下已知簡化（例如目錄若未放頁碼）。新的 golden 就是這次重產的兩份報告。

- [ ] **Step 7: 全計畫交叉引用檢查**

```bash
cd /Users/kai/BSOS/SecurityCheckKit
# spec 的 13 項決定是否都能在程式碼或文件裡找到落點
grep -rn 'severity_rationale' scripts/ | head -3
grep -rn 'scope_exclusion_reasons' scripts/ | head -3
grep -rn 'scenario_coverage' scripts/ | head -3
grep -c '內部工作版本' scripts/build_report.py          # 浮水印保留
grep -c '第[一二三四]級' test-fixtures/*/security-scan-report/report.md   # 預期 0
python3 scripts/cli.py --help                            # 四個子指令
scripts/regen_fixtures.sh /tmp/sck-final && cat /tmp/sck-final/exit_codes.txt
```

最後一行必須是 `0` 與 `4`。

- [ ] **Step 8: Commit**

```bash
git add -A test-fixtures/
git commit -m "$(cat <<'EOF'
Regenerate both regression fixtures against the redesigned report

Both keep their invariant exit codes (0 and 4) while dropping from 34 pages to
the new layout. Migration placeholders are filled in from each fixture's own
catalog, and the pre/post suppression artifacts are removed now that nothing
consumes them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage** — 逐項比對 `docs/superpowers/specs/2026-08-14-delivery-report-redesign.md` 的 13 項決定：

| Spec 決定 | 對應 Task |
|---|---|
| 決定一：按讀者拆兩份文件 | Task 5 Step 6（worksheet 內容）、Task 7 Step 2（路徑與 gitignore 警告） |
| 決定二：交付報告版面骨架 | Task 5 Step 2/3，Task 6（PDF 呈現） |
| 決定二：範圍檔案清單（Q23） | Task 4 全部、Task 5 Step 3「掃描範圍」 |
| 決定二：壓縮版覆蓋矩陣（Q23） | Task 2 Step 3（schema）、Task 5 Step 3「情境庫覆蓋」 |
| 決定三：impact/severity/status 三欄位 | Task 2 Step 1/2 |
| 決定三：閘門算 impact | Task 2 Global Constraints + Step 5/6 負面測試 |
| 決定三：兩欄並列曝光 | Task 5 Step 3「發現明細」的 Severity 格 |
| 決定三：C 類不進 findings | Task 5 Step 3（C 類只進「已評估項目摘要」） |
| 決定四：整案等級移除、浮水印保留 | Task 5 Step 5，Task 8 Step 1 |
| 決定五：Step 3 移出編號流程 | Task 8 Step 2 |
| 決定六：統一編號 | Task 2 Step 1/2（`id` 格式與唯一性）、Task 4 Step 3（skeleton 預填） |
| 決定七：不放簽名欄位 | Task 6 Step 1（明列「不放」） |
| 決定八：撤回非 Claude 承諾 | Task 8 Step 3 |
| 決定八：`cli.py review` | Task 3 全部 |
| schema 變更表 | Task 2 Step 1/2/3、Task 4 Step 3 |
| 「自動預分類揭露」（spec 現況問題 #3） | Task 5 Step 4 |
| 遺留待辦（bot-gold-token 6 筆） | **不在本計畫範圍**，見下方 |

無缺口。

**2. Placeholder scan** — 無 TBD／TODO。每個 Task 的驗證步驟都是可直接執行的具體命令並附預期輸出。三處刻意的條件分支（Task 5 Step 7 圖表去留、Task 6 Step 2 目錄頁碼、Task 9 Step 4 檔案刪除）都寫明了判準與建議選項，不是留白。

**3. Type consistency** — 跨 Task 一致性：
- 欄位名 `severity`／`severity_rationale`／`remediation`／`confirm_what`／`confirm_who`／`confirm_branches`／`scan_id`／`source` 在 Task 2 定義、Task 3 檢查、Task 4 預填、Task 5 渲染，拼法一致。
- 頂層鍵 `scenario_coverage`／`scope_exclusion_reasons` 在 Task 2 驗證、Task 4 預填、Task 5 消費、Task 9 填值，拼法一致。
- `IMPACT_AS_INDUSTRY` 映射表在 Task 2 Step 2 定義、Task 2 Step 4 遷移腳本與 Task 4 Step 3 skeleton 共用同一份語意（`Optimization` → `Informational`）。
- exit code 語意：`build_report` 的 0/2/3/4 與 `review` 的 0/1/2 是**不同的兩套**，Task 3 Interfaces 已明說，避免誤以為 review 的 1 是錯誤。
- `regen_fixtures.sh` 在 Task 1 建立、Task 5 Step 8 更新（移除 `--after`），兩處一致。

**與 spec 的一處刻意偏離**：spec 的「影響檔案」表列 `scripts/cli.py`「小」變更，本計畫把 `review` 子指令的實作拆成獨立檔 `scripts/review.py` 而非塞進 `cli.py`。理由是 `cli.py` 現行只有 43 行、純粹是 subparser 分派層，其餘三個子指令都各有實作檔（`env_check.py`／`scan.py`／`report.py`），新增檔案才符合既有結構。

**本計畫刻意不做的事**：

- **bot-gold-token 那 6 筆 `uninitialized-state` 的重新判定**。它是內容債不是模板債，新模板只會讓它更醒目。它需要一個人重讀那 6 處程式碼，屬於另一次 scan 執行，不是本計畫的 Task。
- **降級管制機制**（幅度限制／第二人複核）。spec 已列入「不在本次範圍」，靠 Task 2 的閘門隔離 + Task 5 的兩欄曝光 + Task 3 的 review 曝光三層控制。
- **審計能力層**（多引擎、`slither-check-upgradeability`、動態測試訊號、依賴 advisory、diff 模式、SARIF）。與本次文件工程改版正交。
