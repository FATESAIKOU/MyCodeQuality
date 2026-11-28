# 每週表前後對照：`mcq-report compare`

把兩份 `mcq-weekly-table`（每週表）並排比較，輸出每個指標的前、後數值與變化。只讀兩個輸入檔，不連網、不讀時鐘。

範例都用合成資料（單是 `acme/widgets#N`）。

## 用法

```
mcq-report compare <before.json> <after.json> --out <compare.json> [--md <compare.md>]
```

- `before.json`、`after.json`：`mcq-weekly-table`、`schema_version` 1 的檔案。其他 kind 或版本 → exit 2。
- `--out`：必填，寫入 `mcq-weekly-compare` JSON（鍵排序、縮排 2、結尾換行；同輸入位元組相同）。
- `--md`：選填，寫一張人看的 Markdown 表，一個指標一列。

錯誤時 exit 2，stderr 一行：`mcq-report: error <code>: <訊息>`。`bad_kind`、`bad_schema_version`、`bad_table`（缺欄位、型別不對）、`bad_json`、`unreadable`。

## 輸出

```json
{
  "kind": "mcq-weekly-compare",
  "schema_version": 1,
  "tool_version": "0.5.0",
  "before": {"window": {"from": "...", "to": "..."}, "tickets": 20},
  "after": {"window": {"from": "...", "to": "..."}, "tickets": 20},
  "metrics": [ ... ],
  "warnings": []
}
```

`metrics` 的順序固定，依序是：計數欄、比率欄、分布欄、`flags`（三張逐 PR 清單的筆數）。每個 summary 欄位都在內（`usage_by_role_model` 不是數值欄，不比）。

| 類別 | 欄位 | 形狀 |
|---|---|---|
| 計數 | `tickets`、`prs_merged`、`review_rounds`、`fix_rounds`、`unreviewed_merged_prs`、`prs_without_ci`、`unparsed_verdict_lines`、`post_merge_verdicts`、`first_review_head_stale_prs`、`fix_prs_within_7d` | `{"name","before","after","delta"}` |
| 比率 | `review_first_pass`、`ci_first_green` | `{"name","before":{num,den},"after":{num,den},"delta_ratio"}` |
| 分布 | `review_rounds_dist`、`cycle_seconds_dist` | `{"name","before":{n,median,p90},"after":{…},"delta_median","delta_p90"}` |
| flags | `flags.merged_without_review`、`flags.merged_without_ci`、`flags.verdict_format_mismatch` | 計數欄；值是清單的筆數（不比內容） |

## 規則

- **計數**：`delta = after − before`。兩邊任一是 null → `delta` 是 null。
- **flags**：表頂層的 `flags` 有三張逐 PR 清單，只比筆數（清單長度）。舊表沒有 `flags`，或其中某張清單缺漏，該計數是 null，**不是 0**。
- **比率**：兩邊的 `den` 都 ≥ 20 才算 `delta_ratio`＝`after_num/after_den − before_num/before_den`。結果是字串，四捨五入到小數 4 位（恰好在中間時遠離 0 進位，例如 `0.01875` → `"0.0188"`、`-0.01875` → `"-0.0188"`），用精確分數運算，位元組不受浮點影響。任一邊 `den` < 20 → `delta_ratio` 是 null，並加 `"conclusion": "sample_insufficient"`。
- **分布**（`median`、`p90`）：兩邊 `n` 都 ≥ 20 才給 `delta_median`、`delta_p90`。否則兩者都是 null，並加 `"conclusion": "sample_insufficient"`。
- **樣本門檻 20**：樣本不足時不下結論。Markdown 的「說明」欄寫「樣本不足，不下結論」。
- **新舊不可直接比**：兩邊 rows 的 `config_digest` 集合不同 → `warnings` 含 `config_digest_differs`；`tool_version` 集合不同 → 含 `tool_version_differs`。這只是警告，不會擋下輸出；Markdown 會把它寫在表的上方。`warnings` 永遠存在，沒有問題時是空陣列。

## Markdown 怎麼讀

```
| 指標 | 前 | 後 | 變化 | 說明 |
|---|---|---|---|---|
| prs_merged | 30 | 33 | +3 |  |
| review_first_pass | 1/19 | 4/20 | — | 樣本不足，不下結論 |
```

- `—` 表示 null（這一邊沒有值，或變化無法計算）。
- 比率的前、後欄是 `num/den`；變化欄是 `delta_ratio`。
- 分布的前、後欄是「中位、p90（n=）」。
- 計數變化前面加正負號（`+3`、`-1`、`+0`）。

## 注意

- 比較兩週時，先看 `warnings`。出現任何警告，表示兩週用的設定或工具版本不同，數字不能直接當成「變好」或「變差」。
- 樣本不足的指標，即使有數字也不要解讀。
- 這個指令只比兩份表，不篩選單、不重算指標；窗（`window`）是產生表的人決定的。
