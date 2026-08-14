# 回歸基準（golden）

這個 repo 沒有 test suite，`test-fixtures/` 底下兩組樣本是報告層改動的唯一 gate。兩組都帶著完整的
Step 1／Step 2 產物（`results_*.json`、`classification.json`、`scan_env.json`），所以
`scripts/regen_fixtures.sh <out-root>` 可以**完全離線**重產 `report.md`，不需要 slither，也不需要 forge。

## 不變量（改版全程不得改變）

| 樣本 | exit code | Tier | 理由 |
|---|---|---|---|
| timelock-vault | **0** | 第二級 | 有 B 類、無 A/D、無非誤報 High |
| vulnerable-vault | **4** | 第四級 | 有非誤報 High + Critical 人工發現 |

exit code 出現變化就是 regression，除非當下執行的 Task 明確說要改。

## 使用方式

```bash
scripts/regen_fixtures.sh /tmp/sck-check
diff /tmp/sck-check/exit_codes.txt /tmp/sck-baseline-frozen/exit_codes.txt
```

`report.md` 的輸出是**位元穩定**的（同一份輸入重跑得到同一份輸出），可以直接 diff：

```bash
diff /tmp/sck-check/timelock-vault/report.md /tmp/sck-baseline-frozen/timelock-vault/report.md
```

**`stdout.txt` 不要拿來 diff** —— 它含 `--out-dir` 的絕對路徑，換目錄就會不同，這不是 regression。

## 環境現況（2026-08-14 實測）

- 本機只有一個 python3：`/usr/bin/python3`（Apple CommandLineTools，**Python 3.9**）。
- `fpdf2` 停在 **2.8.4** —— 這是 PyPI 上支援 Python 3.9 的最後一版，`pip install "fpdf2>=2.8.8"`
  在此環境**無解**（需要先裝 Python 3.10+）。
- `references/pitfalls.md` #6 要求 >= 2.8.8，理由是 2.8.7 及更早有字型子集化的靜默亂碼 bug。
  **實測 2.8.4 在本機未重現該 bug**：把 `bot-gold-token` 的 `report.pdf` 第 1 頁轉成圖片目視檢查，
  封面的「Slither」與日期字串渲染正確。
- 因此的處理方式：繼續用 2.8.4，但**每次改動 PDF 版面後必須把封面頁轉圖目視確認**，不能只看
  `pdftotext` 的輸出（該 bug 是 glyph 畫錯、底層文字正確，`pdftotext` 抓不到）：

  ```bash
  pdftoppm -png -r 80 -f 1 -l 1 <report.pdf> /tmp/cover && open /tmp/cover-01.png
  ```

## 改版預期會改變的（不是 regression）

- 章節結構、標題文字、頁數、findings 編號格式。
- 「工具原始輸出 vs 交付版掃描結果」對照表與 `severity_chart.png` 會消失。
- 整案等級（第X級）那句話會從報告本文消失；內部版浮水印保留。
