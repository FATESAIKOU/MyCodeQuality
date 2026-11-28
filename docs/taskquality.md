# Task Quality (`taskquality`) 規格與說明

`taskquality` 是針對單一工單（ticket）執行過程品質的量測工具。它與程式碼全域指標（`qmetrics repo`）互不依賴，不引入 `qmetrics`、不用浮點數、不讀系統時鐘、計算階段不連網，完全採確定性演算法產出結果。

本工具提供三大子命令：
- `taskquality fetch --ticket OWNER/REPO#N [--search-repo OWNER/REPO ...] [--pr OWNER/REPO#N ...] --out SNAPSHOT.json`：唯一連網之子命令，透過 GitHub API 取得工單候選 PR 及其審查、CI 等資訊，產出確定性快照檔。
- `taskquality score --snapshot SNAPSHOT.json [--input INPUT.json] [--config CONFIG.json] [--json]`：讀取快照與外部輸入，依慣例設定計算品質指標並輸出報告。
- `taskquality defaults`：印出內建預設的 config JSON，可供自訂設定時複製與修改。

---

## 1. 快照格式（Snapshot）

快照（Snapshot）由取得層（`fetch`）抓取 GitHub 資料後產出，作為 `score` 的主要輸入。快照檔不含抓取時刻、帳號；但含 PR 標題／本文／留言第一行，私有 repo 的快照不要 commit 到公開 repo。

```json
{
  "kind": "taskquality-snapshot",
  "schema_version": 1,
  "ticket": "acme/widgets#11",
  "ticket_labels": [
    {"at": "2030-01-02T02:00:00Z", "action": "labeled", "label": "status:in-progress"}
  ],
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
        {"id": 501, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：vendor/model-x 結論：要修（head 0000000）"},
        {"id": 502, "created_at": "2030-01-02T04:50:00Z", "first_line": "審查：vendor/model-x 結論：可以 merge（head 1111111）"}
      ],
      "reviews": [
        {"id": 601, "submitted_at": "2030-01-02T04:55:00Z", "state": "APPROVED", "commit_id": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
      ],
      "ci_runs": [
        {"run_id": 9001, "workflow": "ci", "event": "pull_request", "head_sha": "0000000ccccccccccccccccccccccccccccccccc", "run_attempt": 1, "created_at": "2030-01-02T03:01:00Z", "status": "completed", "conclusion": "failure"},
        {"run_id": 9002, "workflow": "ci", "event": "pull_request", "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "run_attempt": 1, "created_at": "2030-01-02T04:41:00Z", "status": "completed", "conclusion": "success"}
      ]
    }
  ]
}
```

### 欄位說明
- `kind`: 固定為 `"taskquality-snapshot"`。
- `schema_version`: 目前為 `1`。
- `ticket`: 工單識別，格式為 `owner/repo#number`。
- `ticket_labels`（選填；`fetch` 一律輸出，沒有事件時為 `[]`）: 工單的標籤加上／移除事件，每筆為 `{"at", "action", "label"}`。
  - `action`: `"labeled"` 或 `"unlabeled"`。
  - 依 (`at`, `action`, `label`) 排序；**不含操作者**。
  - 沒有這個鍵的舊快照照常計算（`score` 的輸出不變）。
- `prs`: 陣列，依 PR 識別 `(owner/repo, number)` 排序。
  - `id`: PR 識別，格式為 `owner/repo#number`。
  - `title`, `body`: PR 標題與內文。
  - `state`: `"open"` 或 `"closed"`。是否已合併由 `merged_at` 判定。
  - `created_at`, `merged_at`, `closed_at`: ISO 8601 UTC 時刻字串（`YYYY-MM-DDTHH:MM:SSZ`）。未發生為 `null`。
  - `head_sha`: 40 碼十六進位字串。
  - `comments`: 留言清單，只存第一行 `first_line`。
  - `reviews`: GitHub 正式 Review 清單。`state` 包含 `APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`。
  - `ci_runs`: Actions 執行記錄，包含 `run_id`, `workflow`, `head_sha`, `run_attempt`, `status`, `conclusion`。

---

## 2. 外部輸入檔格式（External Input）

外部輸入檔（`--input`）由導入方或使用方的成本管理模組產生，提供無法從 GitHub 公開資料取得的執行資訊（例如 token 用量、模型費用、內部會話計數或審查結果覆寫）。

```json
{
  "kind": "taskquality-input",
  "schema_version": 1,
  "ticket": "acme/widgets#11",
  "started_at": "2030-01-02T02:00:00Z",
  "usage": [
    {
      "pr": "acme/widgets#21",
      "role": "impl",
      "provider": "vendor",
      "model": "model-y",
      "input_tokens": 120000,
      "output_tokens": 8000,
      "cache_read_tokens": 90000,
      "cache_write_tokens": null,
      "cost_micro_usd": 410000
    }
  ],
  "counters": {
    "compactions": 2,
    "sessions": 3
  },
  "prs": {
    "acme/widgets#21": {
      "verdicts": [
        {"at": "2030-01-02T04:00:00Z", "role": "審查", "model": "vendor/model-x", "verdict": "fail", "head": "0000000"},
        {"at": "2030-01-02T04:50:00Z", "role": "審查", "model": "vendor/model-x", "verdict": "pass", "head": "1111111"}
      ],
      "rework": false
    }
  }
}
```

### 欄位說明
- `kind`: 固定為 `"taskquality-input"`。
- `schema_version`: 目前為 `1`。
- `ticket`: 必須與快照的 `ticket` 完全一致，否則視為 `ticket_mismatch` 工具錯誤。
- `started_at`（選填）: 開工時刻（UTC）。未提供時，若 config 有 `started_label`（config v2）且快照有該標籤的 `labeled` 事件，改採該標籤最早一次的時刻（`cycle_basis: "ticket_label"`）；再沒有，才採最早建立的 PR `created_at`。
- `usage`（選填）: Token 與成本記錄陣列。各 token 與 `cost_micro_usd` 均為非負整數（避免浮點數；費用單位為微美元 micro-USD，即百萬分之一美元）。每項可再帶兩個選填鍵：
  - `weighted_micro_units`: 非負整數或 `null`（加權單位，微單位）。`null` 表示該項未計價（例如免費模型），不是 0。只要任何一項帶有此鍵（值可為 `null`），報告的 `by_model`、`by_role_model`、`totals` 會多出 `weighted_micro_units` 與 `weighted_null_rows` 兩鍵（見下）。
  - `agent`（選填，字串或 `null`）: 存在且非 `null` 時必須是非空字串；`null` 視同沒帶。這是輸入方的識別資訊，**不進任何輸出**：報告、`warnings`、`missing` 與錯誤訊息都不會出現它的值（錯誤訊息只指出鍵名）。
- `counters`（選填）: 名稱與非負整數的對應物件，原樣輸出至報告。
- `prs.<id>.verdicts`（選填）: 覆寫特定 PR 的審查結論序列。若存在（包含空陣列），該 PR 的 `verdicts_source` 記為 `"input"`；若給定 `null`，則該 PR 審查各項輸出為 `null`，原因為 `input_null`。
- `prs.<id>.rework`（選填）: 布林值或 `null`，覆寫特定 PR 的返工推斷結果，`rework_source` 記為 `"input"`。

---

## 3. 設定格式（Config）

`--config` 定義了工單關聯、審查結論擷取正規式、返工關鍵字等慣例。執行 `taskquality defaults` 可取得內建預設值：

```json
{
  "kind": "taskquality-config",
  "schema_version": 1,
  "ticket_ref_keywords": ["closes", "close", "closed", "fixes", "fix", "fixed", "resolves", "resolve", "resolved", "refs", "ref"],
  "verdict_sources": ["comments"],
  "github_review_role": "審查",
  "verdict_pattern": "^(?P<role>\\S*審查)：(?P<model>[^\\s（）]+)(?:（(?P<note>[^）]*)）)? 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})(?:[；;][^）]*)?）",
  "review_roles": ["審查"],
  "pass_verdicts": ["可以 merge", "通過"],
  "fail_verdicts": ["要修", "要退回", "要退回設計"],
  "rework_keywords": ["修正", "fix", "fixes", "follow-up", "revert"],
  "ci_workflows": null,
  "ci_green_conclusions": ["success", "neutral", "skipped"]
}
```

### config v2（`schema_version: 2`）

新增兩個選填鍵；只有用了新鍵的 config 才需要寫成 v2。

- `started_label`（字串，非空）: 開工標籤。沒有 `input.started_at` 時，取快照中該標籤**最早一次** `labeled` 的時刻，報告的 `cycle_basis` 為 `"ticket_label"`。快照沒有 `ticket_labels`，或找不到該標籤，就往下採 PR `created_at`（`"first_pr_created"`）。標籤常在開單後幾秒內加上，所以它是近似的開工時刻。
- `ci_required`（布林，預設 `true`）: `false` 時 `clean` 不看「每個合併的 PR 都要有 CI run」這一條。沒有 CI run 的合併 PR 仍計入 `prs_without_ci`，`ci_first_green` 仍為 `null`（`no_ci_runs`）；CI 失敗仍使 `clean` 為 `false`；CI 還沒跑完（`ci_incomplete`）仍使 `clean` 為 `null`。
- 版本規則：
  - `schema_version` 接受 `1` 與 `2`。
  - v2 必須有 v1 的所有必填鍵。
  - **v1 config 出現 `ci_required` 或 `started_label` 是 `config_bad_shape`（exit 2）。** 這是刻意收緊：v1 過去會靜靜忽略未知鍵，現在帶新鍵的 v1 檔直接報錯，避免版本不一致時算出不同的 `clean`。其他未知鍵仍被忽略。
  - 錯誤訊息的版本文字改為 `schema_version=1 or 2`。
- `cycle_basis` 的值現在可能是：`"input_started_at"`、`"ticket_label"`、`"first_pr_created"`，或 `null`。

### 雜湊計算（`config_digest`）
- 針對 14 個既定認得的鍵（含 `ci_required`、`started_label`，只有存在時才雜湊），依 `json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` 序列化後計算 SHA-256。
- 輸出格式為 `"sha256:" + 64碼小寫十六進位`。

---

## 4. 報告格式（Report）

`taskquality score --json` 產出之報告結構如下：

```json
{
  "clean": false,
  "config_digest": "sha256:…",
  "counters": {
    "compactions": 2,
    "sessions": 3
  },
  "excluded_prs": [
    {
      "pr": "acme/widgets#30",
      "reason": "no_ticket_ref"
    }
  ],
  "kind": "taskquality-report",
  "metrics": {
    "approved_head_stale": 0,
    "ci_first_green": {
      "den": 1,
      "num": 0
    },
    "cycle_basis": "input_started_at",
    "cycle_seconds": 10800,
    "fix_rounds": 1,
    "nonstandard_verdict_lines": 0,
    "post_merge_verdicts": 0,
    "prs_closed_unmerged": 0,
    "prs_merged": 1,
    "prs_open": 0,
    "prs_without_ci": 0,
    "re_reviews": 1,
    "review_first_pass": {
      "den": 1,
      "num": 0
    },
    "rework_prs": 0,
    "structure_note_verdicts": 0,
    "unparsed_verdict_lines": 0,
    "unreviewed_merged_prs": 0
  },
  "missing": [
    {
      "field": "usage.by_model[vendor,model-y].cache_write_tokens",
      "reason": "input_null"
    },
    {
      "field": "usage.totals.cache_write_tokens",
      "reason": "input_null"
    }
  ],
  "prs": [
    {
      "approved_head_stale": false,
      "ci_first_green": false,
      "ci_first_head": "0000000ccccccccccccccccccccccccccccccccc",
      "created_at": "2030-01-02T03:00:00Z",
      "first_review_pass": false,
      "fix_rounds": 1,
      "merged_at": "2030-01-02T05:00:00Z",
      "nonstandard_verdict_lines": 0,
      "post_merge_verdicts": 0,
      "pr": "acme/widgets#21",
      "re_reviews": 1,
      "rework": false,
      "rework_source": "derived",
      "state": "merged",
      "structure_note_verdicts": 0,
      "unparsed_verdict_lines": 0,
      "verdicts": 2,
      "verdicts_source": "comments"
    }
  ],
  "schema_version": 1,
  "status": "complete",
  "ticket": "acme/widgets#11",
  "tool_version": "0.5.0",
  "usage": {
    "by_model": [
      {
        "cache_read_tokens": 90000,
        "cache_write_tokens": null,
        "cost_micro_usd": 410000,
        "input_tokens": 120000,
        "model": "model-y",
        "output_tokens": 8000,
        "provider": "vendor"
      }
    ],
    "by_role_model": [
      {
        "cache_read_tokens": 90000,
        "cache_write_tokens": null,
        "cost_micro_usd": 410000,
        "input_tokens": 120000,
        "model": "model-y",
        "output_tokens": 8000,
        "provider": "vendor",
        "role": "impl"
      }
    ],
    "totals": {
      "cache_read_tokens": 90000,
      "cache_write_tokens": null,
      "cost_micro_usd": 410000,
      "input_tokens": 120000,
      "output_tokens": 8000
    }
  },
  "warnings": []
}
```

### 提示（`warnings`）
`warnings` 是只加不改的提示：不影響任何指標、`clean`、`missing` 或 `config_digest`，人看的摘要（不帶 `--json`）會以 `warning: <代碼>` 一行一個印出。字串依字典序排序、去重；沒有觸發時是 `[]`。目前有三種：

- `unparsed_verdict_lines: N verdict-like line(s) did not match verdict_pattern`：工單已合併 PR（merged PR）留言中，有 N 筆第一行符合 `^\S*審查：` 但整行不符合 `verdict_pattern`（與 metrics 的加總範圍一致，只看 comments 來源）。留言的實際文字不會出現在提示裡。
- `unrecognized_verdict: N verdict line(s) …`：工單各 PR 的審查行中，有 N 筆結論字既不在 `pass_verdicts` 也不在 `fail_verdicts`（即 `other`）。這些審查行已被認得（格式正確），只是結論字不在清單裡，所以審查各項會是 `null`（`unrecognized_verdict`）。**結論字的實際文字不會出現在提示裡**。處理：若那是團隊慣用的通過字（例如只寫「可以」），在自己的 config 的 `pass_verdicts` 加上它；若是要修的字，加進 `fail_verdicts`。不要靠改內建預設。
- `ci_workflows_unmatched: <名稱>`：config 的 `ci_workflows` 有一項，與快照中任何 CI run 的 workflow 名稱都不相等（通常是改名，或寫錯）。這一項因此對不上任何 run，PR 會靜靜地變成 `no_ci_runs`。快照裡一筆 CI run 都沒有時不提示（那是 `no_ci_runs` 本來的訊息）；`ci_workflows` 是 `null` 時也不提示。若只差大小寫，訊息改為 `ci_workflows_unmatched: <名稱> (case differs from an existing workflow name)`，並不列出實際名稱。比對範圍是整個快照的 CI run（包括被排除的 PR 與 `run_attempt` 不是 1 的 run）：警告只抓「名稱在整個快照裡都對不到」；工單本身沒有符合的 run 時，仍由 `missing` 的 `no_ci_runs` 反映。處理：把 config 的名字改成 GitHub Actions 顯示的 workflow `name:` 一字不差的寫法。

### 審查行解析與新欄位（N37）
- **合併前結論序列過濾**：對已合併（`merged`）的 PR，結論序列 V 只採計 `at ≤ merged_at`（同一秒算在內）；`at > merged_at` 的審查行另外計入 PR 層的 `post_merge_verdicts`，不進入一次通過、修訂輪數、重審、approved_head_stale 或未審先合的判斷。`open` 與 `closed_unmerged` PR 不進行時間過濾。`--input` 覆寫的 `verdicts` 亦同樣適用此過濾規則。
- **結構審查註記排除**：若 config 的 `verdict_pattern` 定義了名為 `note` 的擷取群組，且 `role` 屬於 `review_roles`，當 `note` 內容含有「架構」或「結構」字樣時，該審查行不進入 V，改計入 `structure_note_verdicts`。若 pattern 未包含 `note` 群組，此規則不作用。
- **head 括號內補充說明容忍**：pattern 的 head 段支援 `（head (?P<head>[0-9a-f]{7,40})(?:[；;][^）]*)?）`，當 head 後接全形或半形分號時，容忍括號內之補充說明，補充說明不進任何指標。此類解析成功但屬非標準寫法之審查行，計入 PR 層的 `nonstandard_verdict_lines`。
- **指標加總與新欄位**：
  - PR 層：`nonstandard_verdict_lines`、`post_merge_verdicts`、`structure_note_verdicts`、`unparsed_verdict_lines`。
  - metrics 層：上述四者在 `merged` PR 的加總值。
  - 無上述情形時，新欄位數值皆為 0。

### 工單狀態（`status`）
- `no_prs`: 快照中無屬於本工單的 PR。
- `in_progress`: 仍有 `state == "open"` 的 PR。
- `no_merged_pr`: 無 open PR，且亦無已合併的 PR（全部為 `closed_unmerged`）。
- `complete`: 無 open PR，且至少有一個 PR 已合併。

### 判定旗標（`clean`）
當且僅當 `status == "complete"` 時進行是非判定。必須滿足以下七項條件：
1. `unreviewed_merged_prs == 0`
2. `prs_without_ci == 0`
3. `review_first_pass.num == review_first_pass.den`
4. `fix_rounds == 0`
5. `approved_head_stale == 0`
6. `ci_first_green.num == ci_first_green.den`
7. `rework_prs == 0`

- **短路判定**：若任一條件確定不成立，`clean` 立即判定為 `false`（不論其他項是否為 `null`）。
- **全部成立**：若全數成立，`clean` 為 `true`。
- **未定**：若無不成立條件，但有條件因依賴項為 `null` 而無法判斷，則 `clean` 為 `null`，並在 `missing` 記錄每個判不出的原因。

---

## 5. 缺值行為（Missing Values）

工具不補 0、不自動猜測數值。當鍵不存在或值為 `null` 時，報告一律輸出 `null`，並於 `missing` 陣列登錄原因。

### 缺值原因代碼（`reason`）
- `input_missing`: 外部輸入檔案未提供（或整個鍵未給定）。
- `input_null`: 外部輸入檔案顯式給予 `null`。
- `no_verdict`: PR 無任何合格的審查結論。
- `unrecognized_verdict`: 審查結論字無法比對至 `pass_verdicts` 或 `fail_verdicts`（即 `other`）。
- `no_ci_runs`: PR 無符合條件的 attempt 1 CI 記錄。
- `ci_incomplete`: 首個 head 上的 CI 尚未全部完成。
- `pr_open`: 仍有 PR 處於開啟狀態，工單尚未結束。
- `no_merged_pr`: 工單無已合併之 PR。
- `bad_interval`: 結束時刻早於起始時刻。

### 欄位路徑（`field`）表示法
- PR 層級：`prs[owner/repo#number].欄位`（例如 `prs[acme/widgets#21].fix_rounds`）。
- 工單指標層級：`metrics.欄位`（例如 `metrics.review_first_pass`）。
- 用量層級：`usage.by_model[provider,model].欄位` 或 `usage.totals.欄位`。

### 用量分項（`usage`）
- `usage.by_model`：依 `(provider, model)` 分組，按此排序。
- `usage.by_role_model`：依 `(role, provider, model)` 分組，按此排序；每列鍵為 `role`、`provider`、`model` 加各 token 鍵。null 的傳遞規則與 `by_model` 相同，但 `by_role_model` 不新增 `missing` 項目（`by_model` 與 `totals` 已經報了）。
- 加權兩鍵（只在輸入有任何項目帶 `weighted_micro_units` 時出現）：
  - `weighted_micro_units`: 該組中非 `null` 值之和；組內全部為 `null`（或該組沒有任何項目帶此鍵）時為 `null`。`null` 表示未計價，不是 0。
  - `weighted_null_rows`: 該組中值為 `null` 或沒帶此鍵的項目數（整數）。
  - 加權不進 `missing`，也不影響 `clean`。
- 沒有任何項目帶 `weighted_micro_units` 時，這兩鍵不出現，輸出與加入此功能前相同（除了多出的 `by_role_model`）。
- 整體缺值：若整個區塊未提供，標示至該層級（如 `usage`, `counters`, `clean`）。
- 說明性欄位（`merged_at`, `ci_first_head`, `cycle_basis`）為 `null` 時不在 `missing` 中列出。

---

## 6. 工具錯誤與 Exit Code

- 正常結束回傳碼為 `0`。
- 發生工具錯誤時回傳碼為 `2`，標準錯誤（stderr）輸出單行錯誤訊息：
  ```
  taskquality: error <code>: <message>
  ```
  標準輸出（stdout）為空。

### 錯誤代碼一覽
- `bad_arguments`: 指令列引數解析錯誤或缺少必要選項。
- `file_unreadable`: 檔案無法讀取（不存在或無權限）。
- `file_not_json`: 檔案非合法的 JSON 格式。
- `snapshot_bad_shape`: 快照結構錯誤、缺少必要欄位、或 kind/schema 不符。
- `input_bad_shape`: 外部輸入結構錯誤或 kind/schema 不符。
- `config_bad_shape`: 設定結構錯誤、缺少必要欄位、或來源定義不合法。
- `ticket_mismatch`: 快照之工單號與外部輸入之工單號不相符。
- `bad_time`: 時間字串不符合 UTC ISO 8601（`YYYY-MM-DDTHH:MM:SSZ`）格式。
- `bad_pattern`: 設定檔中之正規表示式編譯失敗。
- `gh_unavailable`: 系統中找不到 `gh` 執行檔。
- `gh_failed`: `gh` API 或子程序呼叫失敗。
- `not_found`: 工單（issue）或指定之 PR 不存在。
- `rate_limited`: 限流重試 3 次後仍被拒絕。
- `incomplete_pagination`: 分頁資料未完整讀取即中斷。
- `out_unwritable`: `--out` 輸出檔案路徑無法寫入。

---

## 7. 工單快照抓取（`taskquality fetch`）

`taskquality fetch` 為 `taskquality` 工具中唯一連網的子命令。它經由 `gh api` 呼叫 GitHub API，抓取指定 ticket 的候選 PR，並將各 PR 的詳細資訊、留言、正式 Review 及 GitHub Actions 執行記錄完整收錄至快照 JSON。

### 命令列參數
- `--ticket OWNER/REPO#N`（必填）：目標工單識別碼，例如 `acme/widgets#11`。
- `--search-repo OWNER/REPO`（選填，可重複指定）：篩選候選 PR 之儲存庫。若提供，則僅保留來自這些 repo 的候選 PR；未提供則不限制。
- `--pr OWNER/REPO#N`（選填，可重複指定）：顯式指定要抓取的 PR。以此選項指定的 PR 一定會納入快照，不受 `--search-repo` 之過濾影響。
- `--out SNAPSHOT.json`（必填）：快照輸出檔案路徑。上層目錄必須已存在（若不存在回報 `out_unwritable`，不自動建立目錄）。寫入時採同目錄暫存檔搭配原子 rename；若中途有任何錯誤或抓取失敗，先關閉暫存檔再 unlink 刪除，絕不留下殘缺檔案或覆寫現存檔案。

### 存取的 GitHub API
1. **候選 PR 清單**：
   - GraphQL API：查詢 `repository(owner, name).issue(number).timelineItems(itemTypes: [CONNECTED_EVENT, CROSS_REFERENCED_EVENT])`，取來源為 PullRequest 的項目（`__typename == "PullRequest"`）。以 `pageInfo.endCursor` 分頁抓取全頁。
2. **PR 基本資訊**：
   - REST API：`GET /repos/{owner}/{repo}/pulls/{number}`，取得標題、本文、狀態、草稿狀態、建立／合併／關閉時刻、head SHA 與 merge commit SHA。快照輸出之 PR 識別碼依 API 回傳的規範 repo 寫法（`base.repo.full_name`）結合 PR 號碼，並依 (owner/repo 小寫, number) 去重。
3. **PR 留言**：
   - REST API：`GET /repos/{owner}/{repo}/issues/{number}/comments`（以 `--paginate` 分頁）。留言僅保留第一行（`first_line`），不存作者或帳號資訊。
4. **GitHub 正式 Review**：
   - REST API：`GET /repos/{owner}/{repo}/pulls/{number}/reviews`（以 `--paginate` 分頁）。僅存已提交之審查狀態（`APPROVED` 等）與提交時刻，不存 Review 內文與作者。
5. **PR Commits**：
   - REST API：`GET /repos/{owner}/{repo}/pulls/{number}/commits`（以 `--paginate` 分頁），記錄該 PR 所屬的所有 commit SHA。
6. **Actions 執行記錄（Workflow Runs）**：
   - REST API：`GET /repos/{owner}/{repo}/actions/runs?event=pull_request&branch={head_ref}`（以 `--paginate` 分頁）。過濾條件為：`pull_requests[].number == number` 或 run 的 `head_sha` 屬於 PR 的 commit SHA（此機制使 fork PR 亦能正確對應 CI run）。
7. **重跑 Attempt 補齊**：
   - REST API：若 workflow run 之 `run_attempt > 1`，呼叫 `GET /repos/{owner}/{repo}/actions/runs/{id}/attempts/{k}`（$k = 1 \dots \text{run\_attempt}-1$）補齊先前的 attempt 記錄。

### 分頁與限流處理
- **分頁**：REST 請求使用 `gh api --paginate`，GraphQL 迴圈檢查 `pageInfo.hasNextPage` 與 `endCursor`。任何 REST 分頁呼叫或 GraphQL 分頁中途回傳非 0 狀態碼，一律視為工具錯誤（`incomplete_pagination`），不寫出快照（僅單頁端點失敗使用 `gh_failed`）。
- **限流偵測與重試**：當指令執行回傳非 0 且（stderr 包含 `(HTTP 429)`、或 exit code 為 429、或 stderr 包含 `(HTTP 403)` / exit code 為 403 且訊息包含 `rate limit`（不分大小寫）），或 GraphQL 回應中包含 `errors[].type == "RATE_LIMITED"`，均視為觸發限流。若回應帶有 `Retry-After` 或 `x-ratelimit-reset` 標頭文字則依其等待，若無標頭則固定等待 60 秒（單次睡眠上限 60 秒）。最多自動重試 3 次（共 4 次請求）；若重試用盡仍被限流，則拋出 `rate_limited` 工具錯誤。
