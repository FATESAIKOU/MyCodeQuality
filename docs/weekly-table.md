# 每週表（`mcq-report table`）

`mcq-report table` 把一個目錄裡的 taskquality 報告（每張單一份）整理成一張週表：每張單一列，加上總計與逐 PR 清單。它只用標準函式庫，不連網，也不讀時鐘；窗的起訖由呼叫端給，表本身不篩選。

本文件涵蓋三部分：taskquality 的 PR 欄位（§0）、週表的命令與輸出（§1），以及讀取方要求的追加欄位（§1a）。

## 0. taskquality 的 PR 欄位

- **`first_review_head_stale`**（PR 層）：已合併、有審查結論（V 非空）、快照有 `head_sha` 時，合併前第一筆結論（`V[0]`）的 head 不是 PR `head_sha` 的前綴 → `true`，是 → `false`；其餘（未合併、V 為空或 `null`、快照無 `head_sha`）→ `null`。
- **`first_review_head_stale_prs`**（metrics）：已合併 PR 中 `first_review_head_stale` 為 `true` 的數目。
- **`ci_runs`**（PR 層）：該 PR 計入的 CI run 數，與 `prs_without_ci` 同一套篩選。

只加不改：舊的鍵與值不變，舊版報告沒有這些鍵時，週表對應欄位為 `null`。

## 1. 命令

```
mcq-report table --reports <目錄> --from <UTC> --to <UTC> [--population <population.json>] --out <table.json> [--md <table.md>]
```

- `--reports`：目錄內每個 `*.json` 都必須是 `kind: "taskquality-report"`，否則 exit 2。依檔名排序讀入，最後依 `ticket` 排序輸出。同一張單出現兩份 → exit 2。
- `--from`、`--to`：只寫進輸出（`window`），表不依它篩選。格式為 `YYYY-MM-DDTHH:MM:SSZ`。
- `--population`：選填，見 §1a。
- `--costs`：保留給 #63 驅動（成本匯出目錄）；本單還不支援，給了就 exit 2（`not supported yet`）。
- `--md`：人看的 Markdown 表，見本節最後。

錯誤（exit 2，stderr 一行 `mcq-report: error <code>: <msg>`）：目錄不存在（`bad_reports_dir`）、JSON 壞（`bad_json`）、kind 不對（`bad_report`）、ticket 重複（`duplicate_ticket`）、population 的 kind 不對（`bad_population`）、時間格式錯（`bad_time`）。

### 1.1 輸出 JSON

```json
{
  "kind": "mcq-weekly-table",
  "schema_version": 1,
  "tool_version": "0.5.0",
  "window": {"from": "...", "to": "..."},
  "incomplete": false,
  "incomplete_reasons": [],
  "rows": [ ... ],
  "summary": { ... },
  "flags": { ... }
}
```

鍵排序、縮排 2、結尾換行；同樣的輸入產生位元組相同的輸出。

### 1.2 每列（`rows[]`）

- `ticket`、`status`、`tool_version`、`config_digest`：取自該張報告。
- `prs_merged`、`fix_rounds`、`review_first_pass`（`{num, den}`）、`ci_first_green`（`{num, den}`）、`unreviewed_merged_prs`、`prs_without_ci`、`unparsed_verdict_lines`、`post_merge_verdicts`、`first_review_head_stale_prs`、`cycle_seconds`：取自報告的 metrics。
- `review_rounds`：已合併 PR 的 `verdicts` 之和。任一已合併 PR 的 `verdicts` 為 `null` → 該列 `null`；沒有已合併 PR → `null`。
- `fix_prs_within_7d`（Q-9）：已合併 PR 中，`merged_at` 在「最早合併的 PR 的 `merged_at`」之後、且不超過 7×86400 秒（含）的 PR 數。與最早合併同一秒的 PR 不算（「之後」）。沒有已合併 PR → `null`。
- `cycle_seconds`：取自 metrics。
- `usage`：報告的 `usage.by_role_model` 原樣；報告的 `usage` 為 `null` → `null`。
- `closed_at`：見 §1a。

缺鍵（例如舊版報告沒有 Q-8 欄位）→ 該欄 `null`，**不補 0**。

### 1.3 總計（`summary`）

- **計數欄**（`prs_merged`、`review_rounds`、`fix_rounds`、`unreviewed_merged_prs`、`prs_without_ci`、`unparsed_verdict_lines`、`post_merge_verdicts`、`first_review_head_stale_prs`、`fix_prs_within_7d`）：非 `null` 值之和，加上 `<欄>_null_rows`（為 `null` 的列數）。
- **比率欄**（`review_first_pass`、`ci_first_green`）：`num`、`den` 各自加總（`null` 的列不計），`null_rows` 記 `null` 的列數，`sample_sufficient` ＝ `den ≥ 20`。
- **分布欄**（`review_rounds_dist`、`cycle_seconds_dist`；`review_rounds` 本身是上面的計數欄）：`n`（非 `null` 的列數）、`median`、`p90`、`sample_sufficient`。百分位用最近秩法：排序後取第 ⌈p×n⌉ 個（整數運算），p 為 0.5 與 0.9。`n < 20` 時 `median`、`p90` 為 `null`。
- `tickets`：列數。
- `usage_by_role_model`：所有列的 `usage` 依 `(role, provider, model)` 再加總。token 鍵：任一項為 `null` → `null`。加權：只要任何參與的項目帶有 `weighted_micro_units` 鍵，就輸出 `weighted_micro_units`（非 `null` 之和；全部 `null` 才 `null`）與 `weighted_null_rows`（各項的 `weighted_null_rows` 加總；沒帶 `weighted` 鍵的項目，每項算作一個 null 列）。都沒有加權鍵 → 不輸出這兩個鍵。沒有任何列有 `usage` → `null`。（與 #61 的規則一致。）
- `usage_null_rows`：`usage` 為 `null` 的列數（這些列不參與 `usage_by_role_model` 的加總）。

### 1.4 逐 PR 清單（`flags`）

`flags` 只列出逐 PR 的事實，依 `(ticket, pr)` 排序：

- `merged_without_review`：`[{"ticket", "pr"}]`，已合併且合併前審查結論數為 0。
- `merged_without_ci`：`[{"ticket", "pr"}]`，已合併且 `ci_runs` 為 0（與 `prs_without_ci` 的判定相同）。
- `verdict_format_mismatch`：`[{"ticket", "pr", "state", "lines"}]`，**所有** PR 中 `unparsed_verdict_lines > 0` 者（不限已合併），`lines` 為該數。
- `flags_null_prs`：有任一項判不出來的 PR 數（已合併而 `verdicts` 為 `null`、已合併而沒有 `ci_runs`、或沒有 `unparsed_verdict_lines`）。這些 PR 不列入上面三張清單。

### 1.5 Markdown（`--md`）

欄位：單｜模型｜角色｜成本｜審查輪數｜一次過｜CI 首綠｜未審先合｜無 CI 合併｜首審過期（Q-8）｜7 天內修正（Q-9）。

- 模型以 `provider/model` 列出，多個以「、」連接；角色同序。
- 成本：列內 `weighted_micro_units` 合計；沒有時顯示「—」。
- 最後一列「合計」取 `summary`；比率樣本不足（den < 20）加「（樣本不足）」。
- 所有 `null` 一律顯示「—」。
- 表格的 `|` 會被跳脫成 `\|`。

## 1a. 追加欄位（讀取方要求）

- **`closed_at`（每列）**：UTC 字串或 `null`。由 `--population <population.json>` 提供，格式為 #63 產出的 `{"kind": "mcq-weekly-population", "schema_version": 1, ..., "tickets": [{"ticket", "closed_at", "level"}]}`。本單只讀 `tickets[].ticket` 與 `tickets[].closed_at`；`kind` 不符 → exit 2。沒給 population，或單不在 population 裡 → `null`。
- **`flags`（頂層）**：見 §1.4。
- **`incomplete`、`incomplete_reasons`（頂層，一律有）**：`incomplete` 為布林；`incomplete_reasons` 為 `[{"repo" 或 "ticket": ..., "reason": ...}]`，排序為全序：repo 項在前、ticket 項在後，同類內依小寫名稱（repo 或 ticket）再依 reason；完全相同的項目去重。單獨跑 `mcq-report table` 一律是 `false` 與 `[]`。#63 驅動會帶入 reasons：有任一項 → `incomplete` 為 `true`。
- `window` 鍵維持 `{"from", "to"}`。

## 程式介面（給 #63）

```python
from mcqreport.table import build_table, render_md

build_table(reports: list[dict], window: dict, closed_at: dict | None = None,
            incomplete_reasons: list[dict] | None = None) -> dict
render_md(table: dict) -> str
```

- `reports`：已讀進來、kind 已檢查的 taskquality-report dict，每張單一份。
- `window`：`{"from": UTC, "to": UTC}`。
- `closed_at`：`{ticket: UTC 字串或 None}`。
- `incomplete_reasons`：`None` → `[]` 與 `false`。
- `build_table` 不做 I/O；讀檔、驗證與寫檔在 `mcq-report table` 的 CLI 裡。

## 2. 設計決定（N10b 報告 §7）

1. **Q-9「之後」**：以嚴格大於最早合併的時間計算；與最早合併同一秒的 PR 不算。
2. **`review_rounds` 沒有已合併 PR → `null`**：沒有已合併的單不當作 0 輪，避免拉低分布。
3. **比率的 `null_rows` 放在比率物件內**：`{num, den, null_rows, sample_sufficient}`；分布物件只有 `n`，沒有 `null_rows`。
4. **`usage_by_role_model` 的加權規則與 `usage_null_rows`**：見 §1.3。
5. **`first_review_head_stale` 為 `null` 時不進 `missing[]`**：為了讓既有 golden 只新增鍵；代價是快照沒有 `head_sha` 時沒有 reason 可查。
6. **`flags_null_prs`**：有任一項判不出來的 PR 計入（已合併而 `verdicts` 為 `null`、已合併而沒有 `ci_runs`、或沒有 `unparsed_verdict_lines`）。這些 PR 不進三張清單。
7. **md 合計列的「審查輪數」**：顯示 `中位 X、P90 Y`；樣本不足加「（樣本不足）」。
8. **版本**：`mcqreport.__version__ = "0.5.0"`（mcq-report 原本沒有版本常數，而且不 import taskquality）。taskquality 的 `TOOL_VERSION` 維持 0.5.0，沒有升版（N10a 也沒有升）。
9. **summary 鍵名**：分布欄為 `review_rounds_dist`、`cycle_seconds_dist`；`review_rounds` 是計數加總（同時有 `review_rounds_null_rows`）。
10. **`ci_runs` 缺鍵的舊報告**：`merged_without_ci` 判不出來，計入 `flags_null_prs`，不算作「有 CI」。
