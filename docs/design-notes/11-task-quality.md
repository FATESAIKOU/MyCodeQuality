# #11 任務品質（ticket 單位）：介面設計

作者：anthropic/claude-opus-5-5（專案架構師，作者模式）。狀態：待非作者審查；本人看過介面、同意後才實作。
範例全是合成資料（`acme/widgets` 等名稱、SHA、時刻都是假的）。

## 0. 先看這裡（給本人）

範圍照本人 11-24 的更正（#11 最新留言）：兩個命令各管一件事。

- **程式碼品質＝整個 repo 的全體分數**：`qmetrics repo`。量某個 commit 上 `src` 全部的程式碼，不分 ticket，也不做 ticket 彙總。以 qmetrics 現有的定義為底（函式長度、巢狀深度、重複、AST 相同、測試數）。
- **任務品質＝一張 ticket 的邏輯模板**：`taskquality`。`fetch` 從 GitHub 取資料存成快照，`score` 只吃快照，算執行過程指標，再帶上導入方填的輸入（token、模型、內部記錄）。比對的慣例都寫在 config 裡，換團隊只改 config。
- 輸出全是**分項**，不加權；任務品質另給一個是非判定 `clean`。**加權的合成分先不做**，見 §8 Q1。
- 缺值一律 `null`，`missing` 列出原因；不補 0。
- 本人要決定的事集中在 §8。其中 Q2 會影響數字的意義：團隊目前多半只把**最後一輪**「可以 merge」貼在 PR 上，「要修」那幾輪留在報告檔。這樣從 PR 留言算出的「審查一次通過率」會偏高。

## 1. 目標與不做什麼

目標：用確定的程式量兩件事，之後改成本（/compact、換模型）時才能比較前後品質：(1) repo 的程式碼整體狀態；(2) 一張 ticket 的執行過程。

不做：
- 不用 LLM，不判讀自由文字的意思；只認設定好的格式（§4.1）。
- 計算不讀時鐘、不讀環境變數；時間只用輸入裡的時刻。`qmetrics repo` 只讀本機 git，`taskquality score` 不連網。
- 取不到的（token、模型用量、內部記錄、開工時刻）不猜，一律當**輸入**（§3.3）。
- 不做 ticket 的程式碼品質彙總（已取消）。
- 不改 `qmetrics diff`、它的 schema 2、`qmetrics gate`。
- 不做跨 ticket 的排名或趨勢；一次只算一張 ticket、一個 commit。

## 2. CLI

exit code 沿用 `qmetrics gate`：0＝成功、1＝判定失敗、2＝工具錯誤（stderr 一行 `<prog>: error <code>: <message>`，控制字元跳脫，與 `cli._one_line` 相同）。本單的命令都**不做判定**，所以只會回 0 或 2；1 保留，給之後的門檻選項。

### 2.1 `qmetrics repo`（PR-A）

```
qmetrics repo [--repo PATH] [--rev REV] [--src src] [--tests tests] [--json]
```

- 量 `--rev`（預設 `HEAD`）那個 commit 的樹，不看工作目錄裡未 commit 的改動，所以同一個 commit 永遠得到同一份結果。
- 不帶 `--json` 印人看的摘要；帶 `--json` 印 §3.4 的 JSON。
- git 存取沿用 `gitio.Git`（白名單環境、空 HOME、固定選項）。只讀一棵樹、不需要歷史，所以**淺 clone 可以用**：`preflight` 加一個關鍵字參數 `history`（預設 `True`，`diff` 的行為不變）；`repo` 用 `history=False`，跳過 shallow 檢查，grafts 與 alternates／replace 的檢查照舊。
- 工具錯誤（exit 2）的 code 沿用 diff：`not_a_repository`、`bad_revision`、`unknown_revision`、`grafts_present`、`git_failed`、`object_missing`、`git_unavailable`。
### 2.2 `taskquality`（PR-B1、PR-B2）

同一個 Python distribution 裡的第二個 console script（`[project.scripts] taskquality = "taskquality.cli:main"`）；不 import `qmetrics`，兩者互不依賴。它是一張 ticket 的「邏輯模板」：指標的算法固定（§4），比對的慣例（ticket 關聯、審查結論格式、返工、CI）放在 config（§3.5），導入方的資料放在 input（§3.3）。

```
taskquality fetch    --ticket OWNER/REPO#N [--search-repo OWNER/REPO ...] [--pr OWNER/REPO#N ...] --out SNAPSHOT.json
taskquality score    --snapshot SNAPSHOT.json [--input INPUT.json] [--config CONFIG.json] [--json]
taskquality defaults                       # 印出內建的 config（§3.5），可複製來改
```

- `fetch`：唯一連網的子命令（經 `gh api`）。找出 ticket 的候選 PR 並抓齊 §3.1 的欄位，寫 `--out`。任一頁沒抓完就是工具錯誤，不寫出不完整的快照。
- `score`：純計算。`--input` 選填（缺了相關欄位就是 `null`，原因 `input_missing`）；`--config` 選填，缺了用內建預設。
- `score` 的工具錯誤 code：`bad_arguments`、`file_unreadable`、`file_not_json`、`snapshot_bad_shape`、`input_bad_shape`、`config_bad_shape`、`ticket_mismatch`（快照與 input 的 `ticket` 不一致）、`bad_time`（時刻不是 `YYYY-MM-DDTHH:MM:SSZ`）、`bad_pattern`（config 的 regex 編不起來）。
- `fetch` 的工具錯誤 code：`bad_arguments`、`gh_unavailable`、`gh_failed`、`not_found`、`rate_limited`（重試用完）、`incomplete_pagination`、`out_unwritable`。

## 3. JSON 格式

### 3.0 共通規則（位元組相同的保證）

- 輸出：`json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"`（與 `qmetrics diff --json` 相同）。
- 數值只用整數；比率寫成 `{"num": 整數, "den": 整數}`，不輸出浮點數。時長是整數秒。
- 時刻：只收 `YYYY-MM-DDTHH:MM:SSZ`（UTC，GitHub 的格式），原樣輸出；其他格式是 `bad_time`。
- 陣列的排序在各欄位寫明；物件靠 `sort_keys`。
- PR 識別一律 `owner/repo#number`；排序時依 (owner/repo 字串, number 數字)。
- 每個檔都有 `kind` 與 `schema_version`；讀到不認得的 `kind` 或版本是工具錯誤。未知欄位：輸入檔忽略（前向相容），輸出不加。
- 缺值：**鍵不存在**＝沒提供；**值是 `null`**＝提供了但未知。兩者在輸出都是 `null`，`missing[].reason` 分別是 `input_missing`／`input_null`。不補 0。

### 3.1 快照（`fetch` 的輸出、`score` 的輸入）

```json
{
  "kind": "taskquality-snapshot",
  "schema_version": 1,
  "ticket": "acme/widgets#11",
  "prs": [
    {
      "id": "acme/widgets#21",
      "title": "Add widget cache",
      "body": "Closes #11",
      "state": "closed",
      "draft": false,
      "created_at": "2030-01-02T03:00:00Z",
      "merged_at": "2030-01-02T05:00:00Z",
      "closed_at": "2030-01-02T05:00:00Z",
      "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "merge_commit_sha": "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "comments": [
        {"id": 501, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：vendor/model-x 結論：要修（head 0000000）"}
      ],
      "reviews": [
        {"id": 601, "submitted_at": "2030-01-02T04:30:00Z", "state": "APPROVED", "commit_id": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "first_line": ""}
      ],
      "ci_runs": [
        {"run_id": 9001, "workflow": "ci", "event": "pull_request", "head_sha": "0000000cccccccccccccccccccccccccccccccc", "run_attempt": 1, "created_at": "2030-01-02T03:01:00Z", "status": "completed", "conclusion": "failure"}
      ]
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `prs` | 陣列，依 PR 識別排序 | `fetch` 找到的**候選**；屬不屬於這張 ticket 由 `score` 依 config 判（§4.1），規則只放一個地方 |
| `state` | `"open"`／`"closed"` | 是否 merged 看 `merged_at` |
| `merged_at`、`closed_at`、`merge_commit_sha` | 字串或 `null` | |
| `head_sha` | 40 碼 | 抓取當下的 head；已 merge 的 PR 就是最後的 head |
| `comments` | 陣列，依 (`created_at`, `id`) | PR（issue）留言；**只存第一行**（少存私人內容） |
| `reviews` | 陣列，依 (`submitted_at`, `id`) | GitHub 正式 review；`state` 原樣（`APPROVED`、`CHANGES_REQUESTED`、`COMMENTED`、`DISMISSED`） |
| `ci_runs` | 陣列，依 (`created_at`, `run_id`, `run_attempt`) | 這個 PR 的 Actions workflow run（每個 attempt 一筆）；`conclusion` 未完成時是 `null` |

快照含 PR 標題與本文（判斷關聯與返工要用）；**私有 repo 的快照不要 commit 到公開 repo**。`score` 的輸出不含任何自由文字（§3.4、§3.6）。

### 3.2 `taskquality fetch` 抓什麼（最小呼叫）

1. 候選 PR：GraphQL `repository(owner,name).issue(number).timelineItems(itemTypes:[CONNECTED_EVENT, CROSS_REFERENCED_EVENT])`，取來源是 PR 的；再加上 `--pr` 指定的。`--search-repo` 給了就只留那些 repo 的 PR（不給＝不限）。
2. 每個 PR：REST `GET /repos/{o}/{r}/pulls/{n}`；`/issues/{n}/comments`、`/pulls/{n}/reviews` 全頁；Actions `GET /repos/{o}/{r}/actions/runs?event=pull_request&branch={head_ref}` 全頁後，只留 `pull_requests[].number == n` 或 `head_sha` 屬於該 PR 的 commit（`/pulls/{n}/commits`）的 run；重跑的 attempt 以 `/actions/runs/{id}/attempts/{k}` 補齊。
3. 分頁：REST 用 `gh api --paginate`；GraphQL 以 `pageInfo.endCursor` 迴圈。任何一頁失敗就是 `incomplete_pagination`，不寫檔。
4. 限流：回應 403／429 且帶限流標頭時，最多重試 3 次，等待 `Retry-After` 或到 `x-ratelimit-reset`，單次上限 60 秒；用完回 `rate_limited`。這是 `fetch` 唯一用到時鐘的地方（只用來睡），時鐘的值不進快照。
5. 快照不記抓取時刻、帳號、作者名、機器位址。同一個 API 狀態抓兩次得到位元組相同的快照。
6. 呼叫 `gh` 的部分是可注入的 runner（argv → stdout／exit），測試用錄好的合成回應，不連網。

### 3.3 外部輸入檔（`--input`；MyCostControl 之後會產這個）

```json
{
  "kind": "taskquality-input",
  "schema_version": 1,
  "ticket": "acme/widgets#11",
  "started_at": "2030-01-02T02:00:00Z",
  "prs": {
    "acme/widgets#21": {
      "verdicts": [
        {"at": "2030-01-02T04:00:00Z", "role": "審查", "model": "vendor/model-x", "verdict": "fail", "head": "0000000"},
        {"at": "2030-01-02T04:50:00Z", "role": "審查", "model": "vendor/model-x", "verdict": "pass", "head": "1111111"}
      ],
      "rework": false
    }
  },
  "usage": [
    {"pr": "acme/widgets#21", "role": "impl", "provider": "vendor", "model": "model-y",
     "input_tokens": 120000, "output_tokens": 8000, "cache_read_tokens": 90000, "cache_write_tokens": null,
     "cost_micro_usd": 410000}
  ],
  "counters": {"compactions": 2, "sessions": 3}
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `started_at` | 時刻、`null` 或缺 | 開工時刻；缺／`null` 時週期時間改用第一個 PR 的 `created_at`（§4.7） |
| `prs.<id>.verdicts` | 陣列或缺 | 有給就**取代**從留言／review 讀出的審查結論（來源記成 `input`）；`verdict` 只能是 `pass`／`fail`／`other`；`head` 是 7～40 碼小寫十六進位；依 (`at`, 原順序) 排 |
| `prs.<id>.rework` | 布林、`null` 或缺 | 有給就取代 §4.5 的推斷 |
| `usage[]` | 陣列或缺 | `role` ∈ `impl`／`review`／`arch`／`pm`／`other`；`pr` 可為 `null`（不屬於單一 PR）；token 與 `cost_micro_usd` 是非負整數或 `null`（成本單位：百萬分之一美元，避免浮點） |
| `counters` | 物件或缺 | 名稱 → 非負整數或 `null`；原樣帶到輸出，不解讀 |

### 3.4 `qmetrics repo --json` 的輸出

```json
{
  "kind": "qmetrics-repo",
  "schema_version": 1,
  "tool_version": "0.3.0",
  "python_version": "3.12",
  "git_version": "2.43.0",
  "rev": "3333333ddddddddddddddddddddddddddddddddd",
  "src": "src",
  "tests": "tests",
  "applicable": true,
  "totals": {"files": 6, "lines": 812, "functions": 40, "tests": 57},
  "counts": {"long_files": 0, "long_functions": 1, "deep_functions": 2,
             "ast_dup_functions": 0, "dup_windows": 3, "smell_events": 6},
  "ratios": {"long_files": {"num": 0, "den": 6}, "long_functions": {"num": 1, "den": 40},
             "deep_functions": {"num": 2, "den": 40}, "ast_dup_functions": {"num": 0, "den": 40}},
  "findings": [
    {"kind": "deep_function", "file": "src/pkg/a.py", "function": "Parser.run", "value": 4},
    {"kind": "dup_windows", "file": "src/pkg/b.py", "function": null, "value": 3},
    {"kind": "long_function", "file": "src/pkg/a.py", "function": "Parser.run", "value": 63}
  ],
  "parse_failures": [],
  "warnings": []
}
```

定義（`src` 底下的 `.py` 檔，取法與 `metrics.list_tree` 相同：跳過 symlink 與 submodule；函式取法與 `metrics.funcs` 相同，含方法與巢狀函式）：

| 欄位 | 定義 |
|---|---|
| `totals.files` | `.py` 檔數 |
| `totals.lines` | 各檔行數加總（`metrics.lines_of`） |
| `totals.functions` | 函式數 |
| `totals.tests` | `tests` 底下 `.py` 檔中 `test_*` 函式數（`metrics.count_tests`） |
| `counts.long_files` | 行數 > 1000 的檔數 |
| `counts.long_functions` | 長度（`end_lineno − lineno + 1`）> 50 的函式數 |
| `counts.deep_functions` | 巢狀深度（`metrics.depth`）≥ 4 的函式數 |
| `counts.ast_dup_functions` | 依 `metrics.shape`（只看 ≥ 5 行的函式）分組，每組大小 ≥ 2 時記「大小 − 1」，加總 |
| `counts.dup_windows` | 6 行視窗（`metrics.windows`）出現在 ≥ 2 個不同檔的**相異**視窗數 |
| `counts.smell_events` | 上面五項加總 |
| `ratios.<k>` | `{num: counts.<k>, den: totals.files 或 totals.functions}`；den＝0 時 `null` |
| `findings` | 每個被計到的項目一筆：`long_file`（value＝行數）、`long_function`（長度）、`deep_function`（深度）、`ast_dup_function`（同組大小；組內每個函式都列）、`dup_windows`（該檔與他檔共有的視窗數）；依 (`kind`, `file`, `function` 或 "", `value`) 排序 |
| `applicable` | `src` 下有任何 `.py` |

門檻（1000、50、4、6 行、5 行）與 `diff` 的事件定義相同，所以兩個命令的數字可以對照。

缺值：`src` 下任一檔解析失敗 → `totals.functions`、`counts`、`ratios`、`findings` 都是 `null`（沿用 diff 的 fail-closed；`files`、`lines` 不用解析，照算）。`tests` 下任一檔解析失敗 → `totals.tests` 是 `null`。失敗的檔列在 `parse_failures`（`{file, scope}`，依 (`file`, `scope`) 排序）。

不輸出加權分數：要看「好不好」看 `ratios`，要看「哪裡」看 `findings`（§8 Q1 也適用於這裡）。

### 3.5 config（`--config`；`taskquality defaults` 印出內建值）

```json
{
  "kind": "taskquality-config",
  "schema_version": 1,
  "ticket_ref_keywords": ["closes", "close", "closed", "fixes", "fix", "fixed", "resolves", "resolve", "resolved", "refs", "ref"],
  "verdict_sources": ["comments"],
  "verdict_pattern": "^(?P<role>\\S*審查)：(?P<model>\\S+) 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})）",
  "review_roles": ["審查"],
  "pass_verdicts": ["可以 merge", "通過"],
  "fail_verdicts": ["要修", "要退回", "要退回設計"],
  "rework_keywords": ["修正", "fix", "fixes", "follow-up", "revert"],
  "ci_workflows": null,
  "ci_green_conclusions": ["success", "neutral", "skipped"]
}
```

- `ticket_ref_keywords`：PR 標題或本文中，`<keyword>[:]? <ref>`（不分大小寫）裡的 `<ref>` 指到這張 ticket（同 repo 的 `#N`、`owner/repo#N`、或 issue URL）就屬於這張 ticket。
- `verdict_sources`：`comments`（留言第一行套 `verdict_pattern`）、`reviews`（GitHub review：`APPROVED`→pass、`CHANGES_REQUESTED`→fail、其他不算結論；head＝`commit_id`）。可兩個都開。
- `review_roles`：只有 `role` 在這個清單的結論算進審查指標（預設不含「結構審查」；架構審查另計是 §8 Q6）。
- `verdict` 文字去頭尾空白後完全比對 `pass_verdicts`／`fail_verdicts`；都不中是 `other`。
- `ci_workflows`：`null`＝全部 workflow；否則只看列出的名字。
- 輸出記 `config_digest`＝`sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True))`，換了慣例看得出來。

### 3.6 `taskquality score --json` 的輸出

```json
{
  "kind": "taskquality-report",
  "schema_version": 1,
  "tool_version": "0.3.0",
  "ticket": "acme/widgets#11",
  "config_digest": "sha256:…",
  "status": "complete",
  "prs": [
    {"pr": "acme/widgets#21", "state": "merged", "created_at": "2030-01-02T03:00:00Z", "merged_at": "2030-01-02T05:00:00Z",
     "verdicts_source": "comments", "verdicts": 2, "first_review_pass": false, "fix_rounds": 1, "re_reviews": 1,
     "approved_head_stale": false, "ci_first_head": "0000000cccccccccccccccccccccccccccccccc", "ci_first_green": false,
     "rework": false, "rework_source": "derived"}
  ],
  "excluded_prs": [{"pr": "acme/widgets#30", "reason": "no_ticket_ref"}],
  "metrics": {
    "prs_merged": 1, "prs_open": 0, "prs_closed_unmerged": 0,
    "review_first_pass": {"num": 0, "den": 1}, "unreviewed_merged_prs": 0,
    "fix_rounds": 1, "re_reviews": 1, "approved_head_stale": 0,
    "ci_first_green": {"num": 0, "den": 1}, "prs_without_ci": 0,
    "rework_prs": 0,
    "cycle_seconds": 10800, "cycle_basis": "input_started_at"
  },
  "usage": {"by_model": [{"provider": "vendor", "model": "model-y", "input_tokens": 120000, "output_tokens": 8000,
                          "cache_read_tokens": 90000, "cache_write_tokens": null, "cost_micro_usd": 410000}],
            "totals": {"input_tokens": 120000, "output_tokens": 8000, "cache_read_tokens": 90000,
                       "cache_write_tokens": null, "cost_micro_usd": 410000}},
  "counters": {"compactions": 2, "sessions": 3},
  "clean": false,
  "missing": [{"field": "usage.totals.cache_write_tokens", "reason": "input_null"}],
  "warnings": []
}
```

排序：`prs`、`excluded_prs` 依 PR 識別；`usage.by_model` 依 (`provider`, `model`)；`missing` 依 (`field`, `reason`)；`warnings` 依字串。
`usage`：依 (provider, model) 加總；任一筆是 `null`，那一格就是 `null`。`counters`：原樣。沒給都是 `null`。

## 4. 指標定義

以下「PR」都只指**屬於這張 ticket** 的 PR（§3.5 `ticket_ref_keywords`）；`excluded_prs` 不算。`state`：`merged`（`merged_at` 有值）、`open`、`closed_unmerged`。審查與 CI 指標的分母只算 `merged` 的 PR（`open` 的還沒結束；`closed_unmerged` 計數但不進比率）。

### 4.1 審查結論的辨認

一個 PR 的結論序列 V＝(v1, v2, …)，來源依序取第一個有的：input 的 `prs.<id>.verdicts` → config `verdict_sources`（兩個都開就合併，依時刻排）。每筆是 (at, role, verdict ∈ pass/fail/other, head)。只留 `role` ∈ `review_roles` 的。head 比對用前綴（7 碼對 40 碼）。

團隊現行慣例（PR 留言第一行「審查：<模型> 結論：可以 merge（head <7碼>）」，另有「結構審查：… 結論：通過（…）」）就是內建預設。**不夠通用的地方**已改成 config：角色字、結論字、正規式、是否讀 GitHub review。另一個不足不是格式而是**慣例本身**：「要修」那幾輪常不貼在 PR 上（見 §0、§8 Q2）。

### 4.2 審查一次通過率 `review_first_pass`

- 每 PR：V 非空時 `first_review_pass` ＝ (v1.verdict == pass)；V 空時 `null`（原因 `no_verdict`），該 PR 計入 `unreviewed_merged_prs`。
- ticket：`{num: first_review_pass 為 true 的 merged PR 數, den: V 非空的 merged PR 數}`；den＝0 時整個是 `null`（`no_verdict`）。

### 4.3 要修輪數 `fix_rounds`

- 每 PR：V 中 verdict＝fail 的筆數。V 中有 `other` 時 `null`（`unrecognized_verdict`；不猜它算不算要修）。V 空時 `null`（`no_verdict`）。
- ticket：merged PR 的加總，V 空的跳過；跳過以外任一 PR 是 `null` 就是 `null`。

### 4.4 head 變動後重審次數 `re_reviews`，與核准後 head 又變 `approved_head_stale`

- 每 PR：`re_reviews` ＝ i ≥ 2 且 vi.head 與 v(i−1).head 不同（互不為前綴）的筆數。V 空 → `null`。
- 每 PR：`approved_head_stale` ＝ V 最後一筆是 pass 且它的 head 不是 PR 最終 `head_sha` 的前綴（核准的不是 merge 的那個 head）。V 空或最後一筆不是 pass → `null`。
- ticket：`re_reviews` 加總（規則同 §4.3）；`approved_head_stale` ＝ true 的 PR 數。

### 4.5 返工 PR 數 `rework_prs`

- 每 PR：input 有 `rework` 就用（`rework_source: "input"`）；否則推斷（`"derived"`）：PR 的標題或本文裡，`rework_keywords` 之一後面接著另一個**同 ticket、且在這個 PR `created_at` 之前已 merge** 的 PR 參照（`#n`、`owner/repo#n` 或 PR URL），就算返工。
- 依序切開的計畫 PR（設計 → PR-A → PR-B）只要不寫「修正 #<前一個 PR>」就不會被誤判；寫了就會。這是啟發式，見 §8 Q3。
- ticket：`rework` 為 true 的 PR 數（所有 state 都算；返工 PR 本身可能還開著）；任一 PR 是 `null`（input 明給 `null`）就是 `null`。

### 4.6 CI 首次綠率 `ci_first_green`

- 每 PR：取 `run_attempt == 1` 且 workflow 在 `ci_workflows` 內的 run；其中 `created_at` 最早的那個 run 的 `head_sha` 是 `ci_first_head`。看 `ci_first_head` 上所有 attempt 1 的 run：全部 `completed` 且 `conclusion` ∈ `ci_green_conclusions` → true；有任一 completed 但不在清單 → false；否則（還有沒跑完的）→ `null`（`ci_incomplete`）。沒有任何 run → `null`（`no_ci_runs`），計入 `prs_without_ci`。重跑（attempt ≥ 2）不算首次。
- ticket：`{num: true 的 merged PR 數, den: true 或 false 的 merged PR 數}`；任一 merged PR 是 `ci_incomplete` → 整個 `null`；den＝0 → `null`。

### 4.7 開工到合併時間 `cycle_seconds`

- 起點：input `started_at`（`cycle_basis: "input_started_at"`）；沒有就用屬於 ticket 的 PR 中最早的 `created_at`（`"first_pr_created"`）。
- 終點：merged PR 中最晚的 `merged_at`。
- 有 `open` 的 PR，或沒有 merged PR → `null`（`pr_open`／`no_merged_pr`）。終點早於起點 → `null`（`bad_interval`）。
- 值＝終點 − 起點，整數秒。

### 4.8 缺值的總則

1. **沒有資料**（PR 沒有任何結論、沒有任何 CI run）：該 PR 不進分母，另外計數（`unreviewed_merged_prs`、`prs_without_ci`）。沒被審就 merge 本身是訊號，不藏起來，也不讓整張變未定。
2. **有資料但判不出來**（不認得的結論字、CI 沒跑完、input 明給 `null`）：該項是 `null`，往上傳到 ticket 的那一項。
3. 每個 `null` 都在 `missing` 有一筆 `{field, reason}`；reason ∈ `input_missing`、`input_null`、`no_verdict`、`unrecognized_verdict`、`no_ci_runs`、`ci_incomplete`、`pr_open`、`no_merged_pr`、`bad_interval`。
4. 從不把 `null` 當 0 加。

### 4.9 整張 ticket 的狀態 `status`

- `no_prs`：沒有屬於 ticket 的 PR。`metrics` 中所有值為 `null`，計數為 0。
- `in_progress`：有 `open` 的 PR。各項照算（只算已 merge 的），但 `cycle_seconds` 與 `clean` 是 `null`。
- `complete`：沒有 open、至少一個 merged。

### 4.10 分數怎麼合成（建議）

推薦（本設計的預設）：**只輸出分項，不加權**，加一個是非判定：

- `clean`：`status == complete` 且 `review_first_pass.num == den > 0`、`unreviewed_merged_prs == 0`、`fix_rounds == 0`、`approved_head_stale == 0`、`ci_first_green.num == den > 0`、`rework_prs == 0`。用到的任一項是 `null` → `null`。（`re_reviews` 不在條件內：一次就過時，它必然是 0。）

取捨：

| 方案 | 好處 | 壞處 |
|---|---|---|
| A 分項＋`clean`（推薦） | 數字的意思一眼看懂；換成本前後逐項比；不需要先定權重 | 不能直接排名 |
| B 加權合成分（例如 0～1000 整數，權重在 config） | 一個數字好比 | 權重沒有資料依據；換權重後新舊分數不可比；遮蔽是哪一項變差 |
| C 只有 `clean` | 最簡單 | 丟掉程度（要修 1 輪和 5 輪一樣） |

任務品質只含執行過程與導入方的輸入，不含程式碼品質（程式碼品質是 repo 全體的分數，§3.4；兩者範圍不同，不合成）。

推薦 A：現在還沒有夠多 ticket 的資料來定權重。累積一批之後，若要 B，可以在 config 加 `weights`，輸出多一個 `composite`，用分項算，不動既有欄位（schema 只加欄位）。

## 5. 模組與依賴方向

```
qmetrics.cli ──> qmetrics.repo ──> qmetrics.metrics（沿用函式取法、深度、視窗、AST 形狀）
                             └──> qmetrics.gitio（沿用 git 存取）
taskquality.cli ──> taskquality.fetch ──> gh（subprocess，runner 可注入）
               └─> taskquality.score ──> taskquality.conventions
                                     └─> taskquality.formats
```

| 模組 | 職責 | 不做 |
|---|---|---|
| `qmetrics/repo.py` | 讀一個 commit 的樹、算 §3.4 | 不比較兩個 commit、不讀 PR 資料、不判定 |
| `qmetrics/gitio.py`（改） | `preflight(git, history=True)` 多一個關鍵字參數 | 預設行為不變 |
| `taskquality/formats.py` | 三種檔案（snapshot、input、config）的讀取與驗證、時刻與 PR 識別的解析、輸出序列化 | 不算指標 |
| `taskquality/conventions.py` | 內建 config、ticket 關聯、結論辨認、返工推斷 | 不讀檔、不連網 |
| `taskquality/score.py` | §4 的全部指標、`missing`、`status`、`clean` | 不讀檔、不連網、不讀時鐘 |
| `taskquality/fetch.py` | §3.2 的取得、分頁、限流、產快照 | 不判斷關聯或指標 |
| `taskquality/cli.py` | 參數、錯誤轉 exit code、摘要文字 | 不放計算規則 |

- 無環：`repo` 依賴 `metrics` 與 `gitio`，`metrics` 不知道 `repo`；`score` 不知道 `fetch`；`taskquality` 與 `qmetrics` 互不 import。
- `repo` 重用 `metrics` 的既有函式（`list_tree`、`lines_of`、`parse`、`funcs`、`depth`、`shape`、`windows`、`count_tests`），只呼叫、不改，所以 `diff` 的數字不變；兩個命令的門檻定義因此一致。
- `taskquality` 自己定義 `ToolError(code, message)`，不借 `qmetrics.gitio`（那是 git 的模組）。
- SOLID：
  - S：取得、驗證、慣例、計算、CLI 分開（上表）。符合。
  - O：新慣例改 config，不改程式。新指標加欄位，schema 只加不改。符合。
  - L：不適用（沒有繼承）。
  - I：`score` 只依賴快照的欄位，不依賴 GitHub 的完整回應。符合。
  - D：`fetch` 依賴注入的 runner，不直接 `subprocess`。符合。

## 6. 取得層、計算層與 workflow

- 取得與計算分開：`fetch` 產快照，`score` 只吃快照。測試 `score` 只要手寫的合成快照；測試 `fetch` 用注入的 runner。
- 程式碼品質與任務品質分開跑、分開看：`qmetrics repo` 量 repo 某個 commit（例如 main 的最新 commit），`taskquality` 量一張 ticket。兩者不互相輸入。
- 可重用 workflow（選配，§8 Q5）：
  - `qmetrics repo`：**建議做**，成本小。在現有的 `quality.yml` 加 `push` 時多跑一步 `qmetrics repo --rev "$SHA" --json > qmetrics-repo.json`，一起上傳成 artifact、摘要印在 job summary；只報告，不影響 gate。不需要新的權限。
  - `taskquality`：**建議本單不做**。跨 repo 抓 PR 需要比 `GITHUB_TOKEN` 更大的讀取權，權限怎麼給要另外決定；ticket 什麼時候算完也沒有現成的事件可以觸發。之後要做的形狀：`workflow_call`＋`workflow_dispatch`，輸入 `ticket`、`search-repos`、`qmetrics-ref`，步驟 fetch → score，上傳兩個 JSON；只報告。

## 7. 切 PR 與契約

建議順序（照範圍更正）：設計（本檔）→ PR-A 程式碼品質全體分數 → PR-B1 任務品質模板（`score`）→ PR-B2 取得層（`fetch`）→（選配）PR-C workflow。PR-B 拆成兩個：`score` 是純計算，可以先審先 merge；`fetch` 碰 GitHub API，另外審。排序由 PM 定。
每條契約都要有測試；實作報告逐條寫對應的測試名。所有測試資料是合成的（測試裡建的暫存 git repo）。

### PR-A：`qmetrics repo`

- **C-A1** 合成 repo（`src` 有一個 60 行函式、一個深度 4 的函式、兩個檔共有 6 行以上相同的程式、兩個 AST 相同的 ≥5 行函式；`tests` 有 3 個 `test_*`）→ `--json` 符合 §3.4：`long_functions == 1`、`deep_functions == 1`、`dup_windows ≥ 1`、`ast_dup_functions == 1`、`tests == 3`、`smell_events` 是五項加總、`ratios` 的 den 是 `functions` 或 `files`。
- **C-A2** 1001 行的檔 → `long_files == 1`；1000 行 → 0。51 行函式算長、50 行不算；深度 3 不算、4 算（與 `diff` 的 `crossing_*` 門檻相同）。
- **C-A3** 量的是 `--rev` 的樹：工作目錄有未 commit 的改動時輸出不變；`--rev` 指舊 commit 時量舊樹。
- **C-A4** 同一個 commit 跑兩次 → 位元組相同；`findings` 依 (`kind`, `file`, `function`, `value`) 排序；輸出沒有浮點數。
- **C-A5** `src` 有一個語法錯誤的檔 → `totals.functions`、`counts`、`ratios`、`findings` 是 `null`，`files`、`lines` 照算，`parse_failures` 有那個檔（scope `src`）；exit 0。`tests` 有語法錯誤 → 只有 `totals.tests` 是 `null`。
- **C-A6** `src` 下沒有 `.py` → `applicable == false`、計數 0、`ratios` 全 `null`（den＝0）。
- **C-A7** 淺 clone（depth 1）→ `repo` 成功；同一個淺 clone 跑 `diff` 仍是 `shallow_repository`。有 grafts → `grafts_present`。`--rev` 解不出來 → exit 2 `unknown_revision`，stderr 一行，stdout 空。
- **C-A8** `qmetrics diff` 與 `qmetrics gate` 的既有測試不改、全過（輸出不變）。

### PR-B1：`taskquality score` 與 `defaults`

- **C-B1** 合成快照＋input＋config → 輸出符合 §3.6，跑兩次位元組相同；輸出中沒有浮點數。
- **C-B2** 關聯：本文有 `Closes #11` 的算；只有 `see #11`（關鍵字不在清單）的進 `excluded_prs`，reason `no_ticket_ref`；`owner/repo#11` 與 issue URL 都認得。
- **C-B3** 結論辨認：預設 pattern 認得「審查：m 結論：可以 merge（head abc1234）」（pass）、「…結論：要修（…）」（fail）；「結構審查：…」不進審查指標；結論字不在兩個清單 → `other`，該 PR 的 `fix_rounds` 是 `null`、`missing` 有 `unrecognized_verdict`。
- **C-B4** input 有 `prs.<id>.verdicts` → 取代留言結論，`verdicts_source == "input"`。
- **C-B5** `review_first_pass`：PR1 (fail, pass)、PR2 (pass) → `{num:1, den:2}`；沒有結論的 merged PR → 不進 den、`unreviewed_merged_prs == 1`。
- **C-B6** `re_reviews`：heads (aaaaaaa, aaaaaaa, bbbbbbb) → 1；7 碼與 40 碼前綴相同視為同一個 head。`approved_head_stale`：最後一筆 pass 的 head 不是最終 head 的前綴 → 該 PR true。
- **C-B7** CI：首個 head 的 attempt 1 有一個 failure → false；全部 success/skipped → true；首個 head 上還有未完成的 → ticket `ci_first_green` 是 `null`、reason `ci_incomplete`；attempt 2 的成功不改變結果；沒有 run → 計入 `prs_without_ci`。
- **C-B8** 返工推斷：PR2 在 PR1 merge 之後開、本文「修正 #21」→ rework true；本文只有「接 #21」→ false；PR2 在 PR1 merge 之前開 → false；input 給 `rework` → 取代推斷，`rework_source == "input"`。
- **C-B9** 週期：有 `started_at` → 用它；沒有 → 最早 PR 的 `created_at`；有 open PR → `null`（`pr_open`），`status == "in_progress"`，`clean` 是 `null`。
- **C-B10** 缺值：沒給 `--input` → `usage`、`counters` 是 `null`，`missing` 有 `input_missing`；input 某 token 是 `null` → 該格 `null`（`input_null`），不是 0。
- **C-B11** 錯誤：快照不是 JSON → exit 2 `file_not_json`；`kind` 不對 → `snapshot_bad_shape`；快照與 input 的 `ticket` 不同 → `ticket_mismatch`；時刻帶 `+08:00` → `bad_time`；config regex 壞掉 → `bad_pattern`。
- **C-B12** `taskquality defaults` 印出的 JSON 當 `--config` 用 → 與不帶 `--config` 的輸出位元組相同（含 `config_digest`）。
- **C-B13** `score` 不讀時鐘、不連網：測試把 `time.time`、`datetime.now`、`socket.socket` 換成會丟錯的替身，`score` 仍成功。

### PR-B2：`taskquality fetch`

- **C-F1** 注入的 runner 回錄好的合成回應 → 快照符合 §3.1，各陣列照規定排序；同樣回應不同順序 → 位元組相同。
- **C-F2** 分頁：runner 回兩頁 → 全部收進快照；第二頁失敗 → exit 2 `incomplete_pagination`，`--out` 的檔案不存在（原本有檔時不被覆寫）。
- **C-F3** 限流：runner 先回 429（帶 `Retry-After: 1`）再回成功 → 成功，睡眠函式被叫一次、引數 1；連續 4 次 429 → `rate_limited`。睡眠函式可注入，測試不真的睡。
- **C-F4** 留言只存第一行；快照裡沒有作者名、帳號、抓取時刻。
- **C-F5** `gh` 不存在 → `gh_unavailable`；issue 不存在 → `not_found`。
- **C-F6** `--search-repo` 給了 → 其他 repo 的候選 PR 不進快照；`--pr` 指定的一定進。

### PR-C（選配）：workflow

照 §8 Q5 的決定。若做 `qmetrics repo` 那一步：

- **C-C1** `quality.yml` 在 `push` 時多產 `qmetrics-repo.json` 並上傳、印在 job summary；`pull_request` 的行為與 gate 不變。
- **C-C2** `qmetrics repo` 回非 0 時 job 失敗（工具錯誤），數值本身從不讓 job 失敗。
- 改 `.github/workflows/` 的部分照團隊規則由 PMO 推。

## 8. 待本人決定（附選項與建議）

- **Q1 分數怎麼合成**：任務品質 A 分項＋`clean`（推薦）／B 加權合成分／C 只有 `clean`，見 §4.10。程式碼品質同理：A `counts`＋`ratios`＋`findings`，不給單一分數（推薦）／B 加權成一個 0～1000 的整數。
- **Q2 審查結論要不要每輪都貼在 PR 上**：抽查 MyCodeQuality 已 merge 的 PR，PR 留言只有最後一輪「可以 merge」；「要修」那一輪只在報告檔。這樣算出的 `review_first_pass` 會偏高，`fix_rounds` 偏低。
  選項：A 團隊規則改成**每一輪結論都在 PR 留一行**（同格式），程式照現在設計（推薦；最便宜，資料留在 GitHub）；B 不改規則，由 PM 或 MyCostControl 把每輪結論寫進 `--input` 的 `verdicts`；C 接受偏差，輸出照現在設計（`verdicts_source` 已標來源）。
- **Q3 返工 PR 怎麼認**：A 預設推斷（關鍵字＋參照同 ticket 已 merge 的 PR）並可用 input 覆寫（推薦）；B 只認 input 或固定 label（例如 `rework`），不推斷；C 任何在第一個 merge 之後才開的 PR 都算（會把計畫內的後續 PR 算進去，不推薦）。
- **Q4 週期的起點**：A input `started_at`，沒有就用第一個 PR 的建立時刻（推薦）；B 用 ticket（issue）的建立時刻（常常早於開工很多）；C 只認 input，沒有就 `null`。
- **Q5 可重用 workflow**：A 只把 `qmetrics repo` 加進現有 `quality.yml` 的 push（推薦；不用新權限），`taskquality` 之後另開單；B 兩個都不做；C 兩個都做，`taskquality` 只支援同 repo 的 ticket（只要 `GITHUB_TOKEN`）。
- **Q6 結構審查（架構師）要不要另算一組指標**：A 不算，只看 `review_roles`（推薦；需要時改 config）；B 另輸出一組 `arch_*` 指標。
- **Q7 命令名**：`taskquality` 是暫名。A 照用（推薦）；B 改成 `qmetrics task` 子命令（同一個命令比較好找，但會讓 qmetrics 依賴 GitHub 資料，職責變寬）。
- **Q8 程式碼品質要不要掛到 ticket 上**（範圍更正後已不做）：例如任務品質報告附上 ticket 開工前後兩個 commit 的 `qmetrics repo` 差。A 不做（推薦，照更正）；B 之後另開單，以 input 的 `counters` 帶入。

## 9. 被捨棄的方案

- **計算時直接呼叫 GitHub API**：無法離線重算、測試要連網、同輸入不保證同輸出。捨棄，改成快照。
- **ticket 下全部 PR 的程式碼品質彙總（`qmetrics ticket`）**：本人 11-24 更正範圍後取消；程式碼品質改量 repo 全體。
- **`qmetrics repo` 用 `diff` 從空樹量到 rev**：`diff` 的事件是「跨過門檻」與「新增」，語意是變化量，不是狀態；用空樹當 base 會把所有既有程式都當成新增。捨棄，另寫 `repo.py`，只共用 `metrics` 的基本函式。
- **`repo` 量工作目錄而不是 commit**：同一個 commit 可能因未 commit 的檔而不同，不確定。捨棄。
- **比率輸出浮點數**：不同語言、不同版本的序列化可能不同。捨棄，改用 num/den 整數。
- **把慣例（關聯、結論）放在 `fetch`**：規則會分散兩處，換慣例要重抓。捨棄，`fetch` 只抓候選，規則全部放在 `score` 的 config。
- **缺 token 時當 0**：會讓「沒記錄」看起來像「很省」。捨棄，用 `null`。

## 10. 風險與未決

- 結論不貼在 PR 上的偏差（Q2）：本人決定。
- 返工推斷是啟發式（Q3）：本人決定；用 input 覆寫可補救。
- `fetch` 找 CI run 依賴分支名＋PR 號，fork PR 的 `pull_requests` 是空的，靠 commit SHA 補；實作時用合成資料測這一條（C-F1 擴充），真機行為未驗。
- GitHub API 欄位名與分頁行為以實作時的文件為準；本設計只定快照格式，取得細節可換。
