# 已知陷阱與正確解法

這些是在 Foundry + OpenZeppelin 升級型合約專案上跑 Slither 掃描時，實測踩過的坑。執行 Step 0～Step 3 時務必遵守這些規則，不要重新踩雷。

## 1. `foundry.toml` 的 `src` 絕對不能設成 `"."`

**症狀**：`forge build` 炸出上百個跟專案完全無關的錯誤，例如 `lib/openzeppelin-contracts/certora/harnesses/*.sol` 找不到相對路徑的檔案。

**原因**：`src = "."` 會讓 Foundry 把整個 repo（包含 `lib/` 底下所有相依套件的內部檔案，如 Certora 形式驗證測試檔）都當成主要編譯目標，而不是只把它們當 import 依賴解析。

**正確做法**：永遠用 `src = "src"`（Foundry 預設），只把專案自己的合約放進 `src/`。`lib/` 只在被 import 時才解析對應檔案。

## 2. 不能盲目安裝最新版 OpenZeppelin

**症狀**：`forge install OpenZeppelin/openzeppelin-contracts-upgradeable`（不指定版本）會抓最新的 v5.x，但合約如果是照 v4 API 寫的，會出現「Undeclared identifier: `__UUPSUpgradeable_init`」之類的錯誤（v5 拿掉了這個函式，因為 v5 的 `UUPSUpgradeable` 沒有任何需要初始化的 storage）。

**正確做法**：安裝依賴前，先讀合約實際呼叫的 API 特徵來判斷版本：

| 特徵 | v4.x | v5.x |
|---|---|---|
| `__UUPSUpgradeable_init()` 呼叫 | 存在，需呼叫 | **已移除**，UUPSUpgradeable 無需初始化 |
| `__Ownable_init(initialOwner)` 帶參數 | 不存在（v4 是 `__Ownable_init()` 無參數，預設用 `msg.sender`） | 存在，需帶 initialOwner |
| ERC721 的 transfer hook | `_beforeTokenTransfer(from, to, tokenId, batchSize)` | `_update(to, tokenId, auth) returns (address)` |

**重要**：如果合約混用了兩個大版本互斥的 API（例如同時出現 `__UUPSUpgradeable_init()` 又出現 `_update` override），代表合約原始碼本身有問題，**不是換依賴版本能解決的**。這種情況要停下來列出具體衝突點，讓使用者決定怎麼修，不要自行改動呼叫方式或商業邏輯。

## 3. `slither-disable-next-line` 只認「緊鄰正上方一行」

**症狀**：加了 `// slither-disable-next-line <check>` + `// Dev Note: ...` 兩行註解，重跑 Slither 後警告數量完全沒變，看起來完全沒生效，也不會報任何錯誤。

**原因**（查過 Slither 原始碼 `slither_core.py::has_ignore_comment`）：Slither 只檢查 `min(lines) - 1`，也就是「發現位置正上方那一行」的文字內容是否符合 `slither-disable-next-line` 的 regex。如果 Dev Note 註解夾在 disable 指令和實際程式碼之間，Slither 看到的「正上方一行」是 Dev Note，不是 disable 指令，完全不會辨識。

**正確做法**：一律使用區塊式：

```solidity
// slither-disable-start <check>
// Dev Note: <說明>
<實際程式碼>
// slither-disable-end <check>
```

`parse_ignore_comments` 的判斷邏輯是 `start_line < finding_line < end_line`（不含頭尾），Dev Note 放在區塊內任何位置都不影響抑制效果。多個 detector 可以用逗號分隔：`// slither-disable-start naming-convention,unused-state`。

**額外提醒**：如果同一個 finding 的多個 element 分散在同一個檔案的不同行號（例如 `pragma` 這種專案級 detector，一個 finding 底下會列出很多檔案的 pragma 行），只要其中任何一個 element 命中 ignore range，Slither 就會把**整個 finding**（所有 element）都判定為已忽略，不是只忽略命中的那個 element。加註解前要意識到這個「一個命中、全部消失」的行為。

## 4. Slither 的 `--exclude-dependencies` 或路徑過濾

掃描結果預設會包含 `lib/` 底下所有相依套件的發現（通常有上百筆，多半跟專案本身無關）。用 `scripts/filter_results.py` 依 `source_mapping.filename_relative` 是否落在專案自己的 `src/` 底下來過濾，不要直接把 `slither --json` 的原始輸出拿去做分類或產報告，否則會被大量無關雜訊淹沒。

## 5. PDF 產生：CJK 字型 + fpdf2 的游標定位 bug

**環境現況**：這個環境沒有 `pandoc`、`wkhtmltopdf`、`weasyprint`，也沒有系統 CJK 字型（`fc-list` 掃不到任何 Noto CJK）。改用 `fpdf2`（純 Python，無系統相依）+ 手動找到的 CJK 字型檔（例如這台機器上 Android Studio 內建的 `NotoSansCJK-Regular.ttc`）可以正常產生中文 PDF。

**症狀**：`fpdf.errors.FPDFException: Not enough horizontal space to render a single character`，且不一定發生在特殊字元上（例如全形句號 `。`），可能發生在任何一行文字，取決於前面的操作。

**原因**：用 `pdf.cell(width, height, text, border=1)` 畫完表格的最後一個儲存格後，游標 x 座標會停在該儲存格右緣，不會自動歸零。如果表格後面接著呼叫 `pdf.multi_cell(0, ...)` 寫一般段落文字，`multi_cell` 會從目前的 x 座標開始算可用寬度，若 x 已經接近右邊界，可用寬度可能小到連一個字都放不下，直接丟例外。

**正確做法**：畫完表格、要開始寫下一段落文字之前，先 `pdf.set_x(pdf.l_margin)` 把游標歸位到左邊界，再呼叫 `multi_cell`。`scripts/md_to_pdf.py` 已經內建這個修法。

## 6. PDF 產生：fpdf2 2.8.7 的字型子集化亂碼 bug（封面頁曾踩到）

**症狀**：封面頁的 `檢測工具`／`檢測日期` 短 ASCII 文字（例如 `Slither`）渲染成亂碼（例如 `6B`），但 `pdf.get_text()` 讀出來的底層文字內容是對的——純粹是繪出來的字形（glyph）錯了。且只在完整的多頁報告（30+ 頁）才會發生，單頁的封面獨立測試重現不出來；跟哪個 CJK 字型檔、`cell()` 還是 `multi_cell()`、要不要先 `pdf.image()` 都無關，換字型或改呼叫方式都修不好，甚至用 fpdf2 內建的 Helvetica core font 硬繞開，還會把「其他每一頁」的 CJK 也一起繪錯。

**原因**：確認是 `fpdf2==2.8.7` 本身的字型子集化 bug，升級到 `2.8.8` 後同一份報告、同一支字型、同樣的程式碼即可穩定重現正確結果（多次重新產生皆正常）。不是這個 repo 程式碼的問題。

**正確做法**：`pip install --break-system-packages "fpdf2>=2.8.8"`（或更新版本）。若在某個環境仍只能用到 2.8.7 或更早版本，且報告有超過一頁的量體，**產出後務必實際打開 PDF 目視確認**（尤其封面頁），不要只信任指令有沒有噴錯——這個 bug 不會拋例外，是靜默把字畫錯。

**另外**：emoji（例如 🎉）在多數 CJK 字型裡沒有字型，`multi_cell` 遇到會直接崩潰而不是跳過。`md_to_pdf.py` 會先用正規表示式把常見 emoji range 過濾掉。
