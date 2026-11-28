# mcq-weekly：每週驅動（#63）

把一段時間內關閉的合格單，依序做成快照、報告與週表。兩段式：`select` 線上凍結母體（population），`run` 只吃凍結的母體，可離線重跑。只用標準函式庫；table 步驟呼叫 `mcqreport.table`（#62）。

## 用法

```
mcq-weekly select --repos <repos.json> --from <UTC> --to <UTC> --as-of <UTC> --out <population.json> [--max-tickets N]
mcq-weekly run --population <population.json> --work <目錄> [--costs <目錄>] [--refetch | --offline]
```

執行方式二選一：`PYTHONPATH=<clone>/src python3 -m mcqweekly ...`，或安裝後使用 `mcq-weekly`。

- `--repos`：`{"kind":"mcq-weekly-repos","schema_version":1,"repos":["owner/name", ...]}`。repo 規則同 taskquality 的 OWNER/REPO；大小寫不分的重複、空清單 → exit 2。檔案放使用方的私有目錄。
- `--from` 含、`--to` 不含（UTC `YYYY-MM-DDTHH:MM:SSZ`，from < to）。程式不讀時鐘。
- `--as-of`：呼叫者標記的資料截點，只寫進母體，見下節。
- `--max-tickets`：每個 repo 最多保留幾張（1～5000，預設 500）；依 closed_at、ticket 取前 N，超過的 repo 標 `truncated`。
- `--costs`：成本匯出目錄，檔名 `<owner>__<repo>__<n>.json`（小寫），內容是 taskquality-input。沒有檔的單成本欄為「—」。
- `--refetch`：重抓快照（失敗就是失敗，不退回舊檔）。`--offline`：不呼叫 gh，缺快照的單記 failed。兩者互斥。

## 母體（population）怎麼選

`select` 查的是**查詢當下**的狀態（`gh issue list --state closed`），條件為：

- 當下 closed，且 stateReason = COMPLETED；
- 最後一次 closedAt 落在 [from, to)；
- 當下 label 含 `層級:c` 或 `層級:d`；兩個都有 → level `c`（c 比 d 大，PM 追加 2 裁定）。

已知限制（**不是歷史快照**）：

- 窗內關閉後又 reopen、現在仍開著的單會漏掉；窗外又關閉過的單會以最後關閉時間判斷。
- 事後改 label 或改名，會改變該單是否入選。
- `as_of` 只是呼叫者標記的截點，gh 查的永遠是查詢當下的狀態；不要把任意回填的時間當成歷史快照。
- 因此母體要**凍結保存**，基準與各週都用凍結的母體重跑。完成事件版本（抓關閉事件）不在本單範圍。

母體的 `repos[].status`：`ok`、`truncated`（gh 回 1000 筆以上，或超過 `--max-tickets`，依保守原則把 1000 筆本身也算截斷）、`list_failed`（gh 非零結束、JSON 壞、或欄位形狀不符；整個 repo 不採用部分清單）。任一非 `ok` → `select` exit 3，母體照寫。

## 快照與 PR 範圍

- 快照存在 `<work>/snapshots/`，預設重用；重用前驗證 kind、schema、ticket 與內容，不符或壞檔即視為不存在（線上重抓，`--offline` 記 failed）。
- 跨 repo PR：`search_repos` 是母體的整個 repo 清單。**清單外 repo 的 PR 不收**，表會低估這種情況；ticket 的引用規則照 taskquality。

## 目錄結構（`--work`，整個目錄視為私有）

```
<work>/
  snapshots/<owner>__<repo>__<n>.json      快取，可跨 run
  runs/<NNN>/                              每次 run 一個，不覆寫
    population.json                        母體的正規化副本
    reports/<owner>__<repo>__<n>.json      只含這次成功產出的報告
    table.json                             週表：incomplete、incomplete_reasons 由 #62 的 build_table 參數帶入；failed_tickets 是驅動加的頂層鍵
    table.md                               人看的表；不完整時結尾附一行註記（由本層加在 render_md 之後，不是 #62 的輸出）
    run.json                               診斷（不在決定性範圍內）
  out.json                                 指標：{"current":"runs/<NNN>"}，原子切換
```

發佈協定：全部寫進新的 `runs/<NNN>/`（每個檔寫完 fsync，目錄 fsync），再寫 `out.json.tmp`、fsync、`os.replace` 成 `out.json`、fsync `<work>`。任何寫入或 table 步驟失敗 → exit 2，`out.json` 不動，舊的結果仍可讀。

權限：目錄 0700、檔案 0600（建立時設定，重用的既有檔案也會收緊）；chmod 失敗 → exit 2。

## 決定性契約

同一份母體＋快照＋成本匯出＋tool_version → `reports/*`、`table.json`、`table.md` 位元組相同。`run.json` 是診斷，不在契約內（它記 fetched／reused、gh 命令數、`api_pages`、`rate_limit_waits`、耗時以外的計數）。所有 JSON 以 `sort_keys`、縮排 2、UTF-8、結尾一個換行序列化；排序：repo 依小寫名稱，ticket 依 (repo 小寫, 號碼)，failed 依 (ticket, stage, code)，`incomplete_reasons` 依 (repo 先、ticket 後, 小寫名稱, reason)，完全相同的項目去重。

## 版本

`tool_version` 取 `mcqweekly.__version__`（目前 `0.5.0`，與其他套件同值），發版時與其他套件一起升。

## 退出碼

- `0`：全部成功、母體完整。
- `3`：有 failed 單、或母體有 truncated／list_failed 的 repo（輸出照寫，`out.json` 已切換）。
- `2`：用法或設定錯（repos 壞、窗壞、母體壞、costs 目錄不存在、`--offline` 與 `--refetch` 同用）、隱私檢查失敗、發佈或 table 步驟失敗、未預期例外。stderr 一行：`mcq-weekly: error <code>: <msg>`。
- 單一快照、成本檔或 score 的失敗是 exit 3，不是 exit 2。

## 隱私

- `--work`、`--costs`、`--out` 解析 realpath 後，若位於任何 git 工作樹內（往上找到 `.git`）→ exit 2。
- 快照與報告含私有 PR 文字；整個 `--work` 視為私有，不做內容過濾。
- stderr 只印代碼與計數，不印 PR 標題或內文。
- 「agent 名不進輸出」只保證 cost input 的 agent 欄位（由 taskquality／mcqreport 的 usage 聚合保證）；PR 自由文字不在此保證範圍。
- 不讀憑證；gh 的登入由 gh 自己處理。

## table 介面（#62）

`src/mcqweekly/_table.py` 直接使用 `mcqreport.table`：`build_table(reports, window, closed_at=None, incomplete_reasons=None) -> dict` 與 `render_md(table) -> str`。`incomplete_reasons` 由驅動傳入，`incomplete`／`incomplete_reasons` 由 `build_table` 產生，驅動不事後覆寫。`failed_tickets` 是驅動加的頂層鍵（單與 stage、code 的失敗清單，依 (ticket, stage, code) 排序）。table.md 不完整時，結尾的註記是驅動加在 `render_md` 之後的一行。測試以 `table_api` 參數注入假函式。

## 效能紀錄

`run.json` 記 `gh_calls`（run 階段所有 gh 呼叫）、`api_pages`（只計 `gh api` 呼叫，每次一頁，因為不用 `--paginate`；`select` 的 `gh issue list` 不計入）、`rate_limit_waits`（taskquality 的重試等待次數）、`tickets`、`prs`、`exit_code`。端到端時間由呼叫端量測。10 分鐘是試跑的量測目標，不是保證。
