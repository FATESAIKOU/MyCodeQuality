# 定期品質報告：慣例

本頁說明 PR 要怎麼寫，`taskquality` 才能正確讀到審查結論與單號。格式以現行程式的行為為準；`tests/test_conventions_lock.py` 把這裡的每一列鎖成測試（契約 C-P1、C-P2）。內建 verdict_pattern 於本版改變；使用者自訂 config 的 pattern 不會自動更新。

範例都用合成資料：單是 `acme/widgets#310`，PR 也在 `acme/widgets`。

## 1. 每一輪審查結論：PR 留言的第一行

本節是摘要。正式文法以 [docs/review-lines.md](review-lines.md) 與 `tests/vectors/review_lines.json` 為準；兩者若有不同，以向量檔為準（向量檔由 `tests/test_review_line_vectors.py` 對照實作）。

格式（逐字，`<…>` 換成實際內容）：

```
審查：<provider>/<model>[（<註記>）] 結論：<結論字>（head <commit SHA>）
```

- `審查`、`結論` 後面是**全形冒號** `：`。
- `<model>` 與 `結論` 之間是**一個半形空白**。
- `<model>` 後可接**一個**全形括號註記 `（<註記>）`（內容不含 `）`，可含空白），註記不進入審查指標。若註記內容含有「架構」或「結構」字樣（例如 `（架構師結構審）`），視為結構審查、不進入審查指標，改計入 `structure_note_verdicts`。這條是舊寫法的相容規則；架構師的結構審查一律寫成 `結構審查：` 開頭。半形括號 `(…)` 不當註記：它會整段併進 `<model>`，該行照一般審查計入，即使內容含「結構」也不算結構審查；請一律用全形。
- 括號是**全形** `（` `）`；`head` 與 SHA 之間是一個半形空白。
- SHA 是**小寫**十六進位，7～40 碼。
- `<provider>/<model>` 中間不能有空白或全形括號。
- 對於已合併（`merged`）的 PR，結論序列只採計 `at ≤ merged_at`（同一秒算在內）；合併後才貼的審查行另計入 `post_merge_verdicts`，不進入一次通過、要修輪數、重審、approved_head_stale 或未審先合的判斷。
- `<結論字>` 只能是下列之一：
  - 通過：`可以 merge`、`通過`
  - 要修：`要修`、`要退回`、`要退回設計`
  - 其他字會被當成 `other`，該 PR 的審查各項（`review_first_pass`、`fix_rounds` 等）會是 `null`（`unrecognized_verdict`）；`re_reviews` 不受影響，仍是數字（實測為 `0`）。報告的 `warnings` 會列出這種情況（`unrecognized_verdict: N …`，不含結論字本身）。
- 補充說明寫在 `）` **之後**（同一行），或寫在第二行以下。不要寫進 head 的括號裡；括號內的補充（`（head 4cac21d；無高）`）會被容忍、照常計入審查，但記入 `nonstandard_verdict_lines`，不算標準寫法。
- 這一行必須是留言的**第一行**，前面不能有空白或 markdown。
- 結論與 `（head <7 碼>）` 必須寫在**同一行**（第一行）：只存留言的第一行，結論後面換行才寫的 `（head …）` 看不到，整行會被當成不是審查行（不是「結論字串帶換行」），這一輪就算不到。細節放第二行以後。
- 每一輪都要貼，包含「要修」那幾輪；head 是該輪審查的 commit。
- 結構審查用同格式、角色字換成 `結構審查`。它會被認出來，但不進審查指標。

| 寫法（逐字） | 結果 |
|---|---|
| `審查：vendor/model-x 結論：可以 merge（head 4cac21d）` | ✅ 通過 |
| `審查：vendor/model-x（pipe a, high） 結論：可以 merge（head 1234567）` | ✅ 通過（註記含空白） |
| `審查：vendor/model-x(結構) 結論：通過（head 1234567）` | ✅ 通過（半形括號不當註記，併進 model；不算結構審查） |
| `審查：vendor/model-x 結論：要修（head 30b3c96）` | ✅ 要修 |
| `審查：vendor/model-y 結論：要退回（head 30b3c96a1b2c3d4e5f60718293a4b5c6d7e8f901）` | ✅ 要修（40 碼可） |
| `審查：vendor/model-x 結論：要修（head 30b3c96） 高 1、中 3，報告見 REPORT-12-review.md` | ✅ 要修（補充寫在 `）` 之後） |
| `審查：vendor/model-x 結論：可以 merge （head 4cac21d）` | ✅ 通過（結論字前後的空白會被去掉） |
| `結構審查：vendor/model-z 結論：通過（head 7c3e45b）` | 認得，但不進審查指標 |
| `審查:vendor/model-x 結論：可以 merge（head 4cac21d）` | ❌ 半形冒號，不算結論 |
| `審查：vendor/model-x結論：可以 merge（head 4cac21d）` | ❌ 模型與「結論」之間少了空白 |
| `審查：vendor/model-x　結論：可以 merge（head 4cac21d）` | ❌ 全形空白 |
| `審查：vendor/model-x 結論：可以 merge(head 4cac21d)` | ❌ 半形括號 |
| `審查：vendor/model-x 結論：可以 merge（head 4CAC21D）` | ❌ 大寫 |
| `審查：vendor/model-x 結論：可以 merge（head 4cac21）` | ❌ 只有 6 碼 |
| `審查：vendor/model-x 結論：可以 merge（head: 4cac21d）` | ❌ `head:` 多了冒號 |
| `審查：vendor/model-x 結論：可以 merge（head 4cac21d；無高）` | ✅ 通過（容忍 head 括號內有補充，計入 nonstandard_verdict_lines） |
| `審查：vendor/model-x 結論：可以 merge（無阻擋項）（head 4cac21d）` | ❌ head 前多一組括號 |
| `審查：vendor/model-x 結論：要修（輕）（head e786beb）` | ❌ 同上 |
| `審查：vendor/Model X (Medium) 結論：可以 merge（head 8521f31）` | ❌ 模型名有空白 |
| `審查（第一輪）：vendor/model-x 結論：要修（head 9a05dc4）` | ❌ 角色字後面加了括號 |
| `**審查**：vendor/model-x 結論：可以 merge（head 4cac21d）` | ❌ markdown |
| ` 審查：vendor/model-x 結論：可以 merge（head 4cac21d）`（行首有空白） | ❌ |
| `審查：vendor/model-y 結論：可以 merge` | ❌ 沒有 head |
| `審查：vendor/model-x 結論：可以merge（head 4cac21d）` | ⚠️ 結論是 `other`（少了空白），審查各項（`review_first_pass`、`fix_rounds` 等）變成 `null`；`re_reviews` 仍是 `0` |
| `審查：vendor/model-x 結論：可以（head 4cac21d）` | ⚠️ 結論是 `other`（「可以」不在清單裡），審查各項（`review_first_pass`、`fix_rounds` 等）變成 `null`；`re_reviews` 仍是 `0` |

## 2. PR 內文寫單號

PR **內文**（description）寫一行，每張單都要有自己的關鍵字：

```
Closes #<N>          ← 這個 PR 做完就關單
Refs #<N>            ← 只是相關（多 PR 的單、不想自動關單時）
```

- 單在別的 repo 時寫 `Closes <owner>/<repo>#<N>`。但 workflow 只看同一個 repo 的 PR，跨 repo 的單不會被算到。
- 多張單每張都要有關鍵字：`Closes #12, closes #13`。
- 接受的關鍵字（不分大小寫）：`closes close closed fixes fix fixed resolves resolve resolved refs ref`。前九個會讓 GitHub 自動關單；`refs`、`ref` 只建立關聯，不會關單。
- 關鍵字前面要是行首、空白、非文字字元或中文字；後面可以接一個半形冒號（可省略），**然後至少一個空白**，再接單號。
- 單號可以是 `#N`、`owner/repo#N`，或 `https://<host>/<owner>/<repo>/issues/<N>`。
- 標題照同樣的規則也會被算，但 GitHub 只看內文，所以**規定寫在內文**。

| 寫法（單是 `acme/widgets#310`，PR 在 `acme/widgets`） | 結果 |
|---|---|
| `Closes #310`、`closes #310`、`CLOSES: #310`、`Fixes #310`、`Resolves #310`、`Refs #310`、`ref #310` | ✅ |
| `Closes acme/widgets#310`、`Closes acme/Widgets#310`（repo 名不分大小寫） | ✅ |
| `Refs https://github.com/acme/widgets/issues/310` | ✅ |
| `本單 Refs #310。`、`修正closes #310`（前面是中文字） | ✅ |
| `Closes #222, closes #310` | ✅（第二個有自己的關鍵字） |
| `Closes #222, #310` | ❌ 對 #310 不算，#310 沒有關鍵字 |
| `Closes:#310`、`Refs#310` | ❌ 冒號或關鍵字後沒有空白 |
| `Closes：#310`、`Closes： #310` | ❌ 全形冒號（冒號後有沒有空白都不算） |
| `（#310 調查；#222）`、`(#310, #222)`、`feat(#310): add cache` | ❌ 沒有關鍵字（標題括號或 scope） |
| `#310`、`See #310`、`Part of #310`、`Related: #310`、`Implements #310`、`關閉 #310` | ❌ 關鍵字不在清單裡 |
| `Closes https://github.com/acme/widgets/pull/310` | ❌ URL 要是 `/issues/` |
| `Refs other/repo#310` | ❌ 不同的 repo |

常見錯誤是把單號寫在標題括號、conventional commit 的 scope，或只寫上層單號。這三種都屬於上表的「沒有關鍵字」。

## 3. 不要改內建 config

這些慣例是現行內建 config 的行為。要放寬或改寫其中任何一條，都會改變內建 `config_digest`，讓升版前後的數字不能比較。個別 repo 真的需要不同設定時，用該 repo 的 config 檔，它只影響那個 repo，而且 digest 看得出來。

若團隊習慣只寫「可以」（不寫「可以 merge」），在自己的 config（v1 或 v2）的 `pass_verdicts` 加上它即可，例如 `["可以 merge", "通過", "可以"]`。**不要改內建預設**：那會改變 `config_digest`。報告的 `warnings` 會提醒 `unrecognized_verdict`，見 [taskquality.md](taskquality.md)。

## 4. 結果檔：artifact 名稱與 `index.json`

定期報告（程式碼與任務）每次跑都會產生一個 artifact。名稱與裡面的 `index.json` 是給使用方讀的介面，格式固定；`mcq-report` 指令負責產生它們。

**artifact 名稱**（只用 `[A-Za-z0-9._-]`；`owner`、`repo` 小寫，`.` 連接）：

| 種類 | 名稱 |
|---|---|
| 程式碼 | `mcq-code--<owner>.<repo>--<target>--<YYYYMMDD>--<rev 7 碼>` |
| 任務 | `mcq-task--<owner>.<repo>--i<N>--<YYYYMMDD>--<final 或 prov>--<快照 sha256 前 8 碼>` |

- 程式碼的日期取該 commit 的 committer date（UTC）；任務的日期取單的 `closedAt`（UTC）。
- 任務的 `final`：距離 `closedAt` 已經滿 `settle-days` 天，而且報告的 `status` 不是 `in_progress`，`missing` 裡也沒有 `ci_incomplete`。否則是 `prov`。
- 使用方**只應相信 `index.json` 的 `repo` 與 `ticket`**，名稱只拿來篩選。

**`index.json`**（`kind: mcq-report-index`、`schema_version: 1`）：

```json
{
  "files": [
    {"kind": "taskquality-config", "name": "taskquality-config.json", "schema_version": 1, "sha256": "…"},
    {"kind": "taskquality-report", "name": "taskquality-report.json", "schema_version": 1, "sha256": "…"},
    {"kind": "taskquality-snapshot", "name": "taskquality-snapshot.json", "schema_version": 1, "sha256": "…"}
  ],
  "kind": "mcq-report-index",
  "python_version": "3.12",
  "qmetrics_ref": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "repo": "acme/widgets",
  "rev": null,
  "report": "task",
  "schema_version": 1,
  "search_repos": ["acme/widgets"],
  "target": null,
  "ticket": "acme/widgets#11"
}
```

- `report` 是 `code` 或 `task`。程式碼時 `rev`、`target` 有值，`ticket` 與 `search_repos` 是 `null`；任務時相反。
- `search_repos` 是任務抓取時實際搜尋的 repo（排序後），用來說明 `no_prs` 的範圍。
- `files` 依 `name` 排序；`kind` 與 `schema_version` 從檔案本身讀出。
- 不含時刻、run id、觸發事件，所以同樣的檔案得到位元組相同的 `index.json`。
- 新指標進來時只會多出 `qmetrics-repo.json` 的新欄位，index 格式不變。使用方要用 `tool_version` 判斷有沒有那些欄位；舊版輸出沒有的鍵是「沒量」，不是 0。

## 5. `mcq-report` 子命令

`mcq-report` 只用標準函式庫，不連網，也不讀時鐘；時刻都由參數給。

- `mcq-report index`：寫出 `index.json`。

  ```bash
  mcq-report index --report task --repo acme/widgets --qmetrics-ref <SHA> --python-version 3.12 \
    --ticket acme/widgets#11 --search-repo acme/widgets \
    --file taskquality-snapshot.json --file taskquality-report.json --file taskquality-config.json \
    --out index.json
  ```

  程式碼時改用 `--rev <commit SHA> --target main`，不給 `--ticket` 與 `--search-repo`。`--target` 與名稱的規則相同（只用 `[A-Za-z0-9._-]`，不能是 `.` 或 `..`）。任務的 `--ticket` 必須在 `--repo` 裡。`--file` 可重複，檔案必須是帶 `kind` 與 `schema_version`（整數）的 JSON，否則 exit 2。

- `mcq-report name`：印出 artifact 名稱（一行）。

  ```bash
  mcq-report name code --repo acme/widgets --target main --committed-at 2030-01-02T23:59:59Z --rev <commit SHA>
  mcq-report name task --ticket acme/widgets#11 --closed-at 2030-01-02T05:00:00Z --run-at 2030-01-05T00:00:00Z \
    --report taskquality-report.json --snapshot taskquality-snapshot.json --settle-days 2
  ```

  `--settle-days` 預設 2，範圍 0～36500；負數或過大的值 exit 2。

- `mcq-report select`：決定任務 workflow 這次要算哪些單，輸出一行 JSON：`{"tickets": [...], "truncated": [...], "skipped_final": [...], "skipped_not_completed": [...]}`。
  ```bash
  mcq-report select --event schedule --repo acme/widgets --now 2030-01-09T00:00:00Z --backfill-days 7 \
    --max-tickets 20 --gh-issues issues.json --gh-artifacts artifacts.json --summary summary.md
  ```
  - `--repo`（必填）是呼叫端的 `OWNER/REPO`；`--now`（必填）是 UTC 時刻，由 workflow 給；`--backfill-days`（預設 7，1～36500）是回溯窗口。
  - `--event` 是 `issues`、`schedule`、`workflow_dispatch` 之一。
  - `schedule` 與 `issues` 要給 `--gh-issues`、`--gh-artifacts`（分別是 `gh issue list`、`gh issue view` 與 `gh api --paginate --slurp` 的輸出）。`workflow_dispatch` 給 `--tickets`（空白分隔的單號）。
  - `issues` 事件只看單的 `number` 與 `stateReason`；`COMPLETED` 才選，其餘（包括重新打開、還沒關閉的單）放進 `skipped_not_completed`，exit 0。
  - `select` 沒有 `--settle-days`：final／prov 只由 `name task` 判定。這與原設計少一個參數。
  - `--max-tickets`（預設 20，上限 256）之外的單放進 `truncated`，摘要用 `::warning::` 標示，不讓 job 失敗。
  - `gh issue list` 的結果不依 `closedAt` 排序，所以排序在指令裡做。結果剛好 1000 筆時表示可能被截斷，exit 2，請縮小 `--backfill-days`。
  - 摘要寫到 `--summary` 指定的檔案；沒給時寫到 stderr。

工具錯誤（參數錯、JSON 形狀不對、檔案讀不到）一律 exit 2，訊息寫在 stderr。

## 6. 可重用 workflow（給使用方呼叫）

MCQ 提供兩個可重用 workflow，使用方的 repo 用 `uses:` 呼叫。兩者都只有 `on: workflow_call`，不需要 secrets。

| workflow | 量什麼 | 產出的 artifact |
|---|---|---|
| `.github/workflows/code-quality-report.yml` | 整個 repo（`qmetrics repo`），對一個 commit | `mcq-code--…`（`index.json`、`qmetrics-repo.json`） |
| `.github/workflows/task-quality-report.yml` | 每張單一個 matrix job（`taskquality fetch`、`score`） | `mcq-task--…`（`index.json`、快照、報告、config） |

`task-quality-report.yml` 先用 `mcq-report select` 決定這次要算哪些單，再為每張單開一個 job；同一張單不會同時跑兩個，一次只跑一張（`max-parallel: 1`）。

### 呼叫端範例（合成）

```yaml
# acme/widgets/.github/workflows/quality-report.yml
name: quality-report
on:
  push:
    branches: [main]
  schedule:
    - cron: "17 3 * * 1"   # code: weekly
    - cron: "41 2 * * *"   # task: daily backfill
  issues:
    types: [closed]
  workflow_dispatch:
    inputs:
      tickets:
        description: "issue numbers, space separated (task only)"
        default: ""
      rev:
        description: "commit to measure (code only; default: the pushed/latest commit)"
        default: ""
permissions: {}            # everything off; each job grants its own
jobs:
  code:
    if: github.event_name == 'push' || github.event.schedule == '17 3 * * 1' || (github.event_name == 'workflow_dispatch' && inputs.tickets == '')
    permissions:
      contents: read
    uses: FATESAIKOU/MyCodeQuality/.github/workflows/code-quality-report.yml@<完整 commit SHA>
    with:
      qmetrics-ref: <同一個完整 commit SHA 或 tag>
      rev: ${{ inputs.rev }}   # empty except on workflow_dispatch
      src: src
      tests: tests
  task:
    # public repos: also require github.event.issue.author_association in OWNER/MEMBER/COLLABORATOR
    if: github.event_name == 'issues' || github.event.schedule == '41 2 * * *' || (github.event_name == 'workflow_dispatch' && inputs.tickets != '')
    permissions:
      contents: read
      issues: read
      pull-requests: read
      actions: read
    uses: FATESAIKOU/MyCodeQuality/.github/workflows/task-quality-report.yml@<完整 commit SHA>
    with:
      qmetrics-ref: <同一個完整 commit SHA 或 tag>
      tickets: ${{ inputs.tickets }}
      config: .github/taskquality.json
```

- `if:` 裡的 cron 字串要和 `on.schedule` 的 cron **逐字相同**，否則排程觸發時 job 會被跳過。
- 一個 repo 有多個套件時，`code` job 用 matrix，每個套件給不同的 `target`。
- 私有 repo 呼叫公開的可重用 workflow：呼叫端 repo 的 Actions 設定要允許使用可重用 workflow。`GITHUB_TOKEN` 只能讀呼叫端自己的 repo，所以跨 repo 的單不會被算到（見下面「使用方要知道的限制」）。

### inputs

`code-quality-report.yml`：

| input | 型別 | 預設 | 說明 |
|---|---|---|---|
| `qmetrics-ref` | string | （必填） | MCQ 的 tag 或完整 commit SHA。沒有預設，避免 `main` 漂移 |
| `python-version` | string | `"3.12"` | AST 會隨版本變 |
| `src`、`tests` | string | `src`、`tests` | 同 `qmetrics repo` |
| `target` | string | `main` | 一個 repo 量多個套件時的區分名（只用 `[A-Za-z0-9._-]`） |
| `rev` | string | `""`（＝呼叫端的 `github.sha`） | 要量的 commit |
| `retention-days` | number | `90` | artifact 保存天數（公開 repo 上限 90） |
| `runs-on` | string | `ubuntu-latest` | 一個 runner 標籤，或 JSON 陣列字串（例如 `["self-hosted","linux"]`）；見 [§9](#9-導入到一個-repo) 自架 runner 的前置 |

`task-quality-report.yml`：

| input | 型別 | 預設 | 說明 |
|---|---|---|---|
| `qmetrics-ref` | string | （必填） | 同上 |
| `python-version` | string | `"3.12"` | |
| `tickets` | string | `""` | 只在 `workflow_dispatch` 用；空白分隔的單號（只收數字）。指定到**還沒關閉、或不是 completed 關閉**的單時，那張單會被略過，run 裡顯示 `::warning::`，job 仍然成功 |
| `config` | string | `""` | 呼叫端 repo 裡的 config 路徑（相對路徑，不接受絕對路徑或含 `..` 的路徑）；空的話用內建 config。不要接到 `workflow_dispatch` 的自由輸入：artifact 是公開的 |
| `backfill-days` | number | `7` | 只在 `schedule` 用：回溯幾天內關閉、還沒有最終結果的單 |
| `settle-days` | number | `2` | 關單後幾天以上、狀態已定，才算 `final`（影響 artifact 名稱） |
| `max-tickets` | number | `20` | 每次排程最多算幾張（控制 API 用量；上限 256） |
| `retention-days` | number | `90` | artifact 保存天數 |
| `runs-on` | string | `ubuntu-latest` | 一個 runner 標籤，或 JSON 陣列字串（例如 `["self-hosted","linux"]`）；`select` 與 `ticket` 兩個 job 都用它 |

`code-quality-report.yml` 輸出 `artifact-name`（本次上傳的 artifact 名稱）。`task-quality-report.yml` 沒有 workflow 層的輸出：每張單各自上傳一個 artifact；要找的時候用 §7 的方法，以 `mcq-task--<owner>.<repo>--i<N>--` 前綴篩。

### 權限

- 呼叫端在 job 上授權，被呼叫端只會再縮，不會放寬。
- `code-quality-report.yml`：`contents: read`。
- `task-quality-report.yml`：`contents: read`、`issues: read`、`pull-requests: read`、`actions: read`。
- 兩個 workflow 都沒有 `write` 權限，也不需要 secrets。artifact 只能讀取，不寫入任何地方。

### 使用方要知道的限制

- **`no_prs` 的範圍**：task 的 `index.json` 的 `search_repos` 是 `[呼叫端 repo]`。workflow 輸出中的 `no_prs` 只表示「在 `search_repos` 這些 repo 裡沒有找到」，**不能**當成「這張單沒有 PR」。
- **跨 repo 的單**：PR 在別的 repo 時，workflow 不會把它算進來。需要時由維護者在本機手動跑 `taskquality fetch --search-repo A --search-repo B`。
- **結果是暫定的，直到 `final`**：`issues: closed` 那次的結果可能還沒包含合併後才貼的審查，或 CI 還沒跑完。排程會在 `backfill-days` 內補算，直到有 `final` 為止。使用方取同一張單**最新的一次** run 的結果。
- **未關閉的單會被略過**：手動指定的單如果還沒關閉、或 `stateReason` 不是 completed，這張單不會產生 artifact，run 裡會有 `::warning::` 說明。這不是工具錯誤，job 仍然成功；單關閉後，再次手動指定，或由每日補算排到它，才會算。
- **重跑會覆蓋同名的 artifact**：名稱與內容對同一個輸入是確定的，所以 Re-run all jobs 會上傳同名的 artifact。上傳步驟設了 `overwrite: true`，舊的同名 artifact 會先被刪掉再上傳（新的 artifact ID，名稱與內容不變）。這點已在真的 GitHub Actions 上驗證：對同一個 run 按 Re-run all jobs 不會因同名而失敗，同一個 run 內只剩一份（不同 run 的同名 artifact 各留一份，見 §9）。
- **`GITHUB_TOKEN` 觸發的事件不會啟動新的 run**：如果 PR 是由 workflow 用 `GITHUB_TOKEN` 合併的，`issues: closed` 不會觸發本 workflow，只能靠每日補算。

## 7. 使用方怎麼取（範例，合成）

使用方只需要能讀這個 repo 的 Actions artifact（既有的讀取權限即可），不需要新憑證。

```bash
# 1. 列出 artifact（分頁），以名稱前綴篩出想要的單；?name= 是精確比對，不能當前綴用
gh api --paginate repos/acme/widgets/actions/artifacts \
  --jq '.artifacts[] | select(.name | startswith("mcq-task--acme.widgets--i11--")) | [.name, .workflow_run.id, .created_at, .expired] | @tsv'
# 2. 下載那一個 run 中的那一個 artifact
gh run download <run id> -R acme/widgets -n mcq-task--acme.widgets--i11--20300102--final--abcd1234 -D out/i11
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["files"])' out/i11/index.json
```

- 同一張單有多個 artifact 時，優先取 `final`；都是 `prov` 時取 `created_at` 最晚的那一個。
- `expired: true` 的 artifact 不能下載。
- 使用方只相信 `index.json` 的 `repo`、`ticket`、`files`；名稱只用來篩選。

## 8. 升版流程（pin 完整 SHA）

1. MCQ 合併後，由維護者打 tag（例如 `v0.4.1`）並寫 release note，標明哪些輸出欄位新增、哪些定義改了。
2. 各 repo 開一個 PR，**同時**改兩個 ref：`uses:` 的 `@<完整 commit SHA>`，以及 `qmetrics-ref`。兩者要是同一個版本。`.github/workflows/` 的改動需要有 workflow 權限的人推送並 merge。
3. 那個 PR 的 CI 與一次 `workflow_dispatch` 試跑，確認 artifact 名稱與 `index.json` 正常。
4. 使用方從 `index.json` 的 `qmetrics_ref`、`tool_version` 與 score 的 `config_digest` 看出定義在哪一刻變了，**不要把升版前後的數字直接相比**。
5. `uses:` 不寫 `@main` 或 `@v4` 這種會移動的 ref；workflow 內的第三方 action 一律用完整 SHA，並在後面的註解寫版本號。

## 9. 導入到一個 repo

1. **前置：憑證範圍**。拉取 artifact 的憑證若限定可見的 repo 範圍，新 repo 要先加進該範圍；否則拉取端會看到 404，這不是 workflow 的錯。
2. **同名 artifact**。同一個 commit 或同一張單在不同 run 各產生一份同名 artifact（`overwrite` 只在同一個 run 內覆蓋）。使用方列出後依 `created_at` 取最新一份，或依 `index.json` 的 `rev`／`ticket` 去重（任務品質的取法見 §7：優先取 `final`，都是 `prov` 時才取最晚的一份）；Re-run all jobs 不會撞名。
3. **手動指定未關閉或非 completed 的單**。ticket job 印 `::warning::` 並略過，job 仍然成功，沒有 artifact。單關閉後再指定一次即可。
4. **`started_label`**。快照取該標籤第一次 `labeled` 的時刻；沒有標籤時 `cycle_basis` 為 `first_pr_created`。沒有 PR CI 的 repo 在 config v2 設 `ci_required: false`，見 [taskquality.md](taskquality.md) 的 config v2。
5. **只導入任務品質的 repo**：呼叫端把 `code` job、`on.push` 與程式碼品質的 cron 拿掉，否則每次 push 都會留下一個只有略過 job 的 run；`workflow_dispatch` 的 `rev` 輸入也可以拿掉。只導入任務品質時 `runs-on` 只影響 `select` 與 `ticket` 兩個 job。
6. **自架 runner 的前置**（`runs-on` 指向自架 runner 時）：
   - 作業系統是 Linux，並有 bash、git、`gh`、`jq`、GNU `date`。
   - workflow 用 `GH_TOKEN` 環境變數認證 `gh`，runner 上不需要事先 `gh auth login`。
   - 有 pip 與可用的 python。`setup-python` 必須能取得 `python-version` 所選的版本：先看 tool cache，沒有就從 GitHub Releases（`actions/python-versions`）下載，PyPy 另從 PyPy 官方站下載。
   - 能連到 Actions 的必要網域（[官方文件](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)列出的）：`github.com`、`api.github.com`、`*.actions.githubusercontent.com`、`codeload.github.com`、`results-receiver.actions.githubusercontent.com`、`*.blob.core.windows.net`（log、artifact、cache）。`pip install git+https://…` 要從 `github.com` 取 MCQ，`gh` 的 API 走 `api.github.com`。
   - 能連 PyPI：pip 預設的 index 是 `https://pypi.org/simple`（[pip 官方文件](https://pip.pypa.io/en/stable/cli/pip_install/)）。實際下載套件檔的主機（推論為 `files.pythonhosted.org`）未由文件確認，**未驗**，要在防火牆內時請實測。
   - runner 應用程式要夠新：workflow 用的 `actions/setup-python@v5`、`actions/upload-artifact@v4` 都是 `node20` action，runner 需支援 node20，[actions/runner](https://github.com/actions/runner/releases) 在 v2.308.0 才加入（release 說明 “Add node20 to runner”）。更舊的 runner 會在這些步驟失敗。自動更新關閉時，要在新版釋出後 63 天內更新，否則 GitHub 不再派工給它（[官方文件](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)）。artifact 服務對 runner 版本的更細要求**未驗**。
   - `gh` 至少 v2.48.0（`gh api --paginate --slurp` 在 [v2.48.0](https://github.com/cli/cli/releases/tag/v2.48.0) 的 release 說明中加入）。只有 `task` 的 `select` job 用到 `--slurp`，只導入程式碼品質的 repo 不需要 `gh`、`jq`。
   - runner 的標籤要與 `runs-on` 一致（單一標籤用字串；多個標籤用 JSON 陣列字串，例如 `["self-hosted","linux"]`，runner 必須同時帶著這些標籤）。`runs-on` 必須是合法 JSON（雙引號）字串陣列或單一標籤，不要有前導空白；空陣列或空字串不會套用預設值 `ubuntu-latest`，而是得到空的 `runs-on`。非法 JSON 會讓整個 run 在 job 啟動前就失敗（startup failure）：沒有 job 的 log，錯誤文字只出現在 Actions 網頁該 run 的 annotation（測試時用 `gh`、REST API 與 GraphQL 都取不到）。單元素陣列（例如 `["ubuntu-latest"]`）與不傳（預設 `ubuntu-latest`）都已在 GitHub-hosted runner 上驗證可以正常執行；自架 runner 也已在一個私有 repo 實跑通過（`runs-on` 傳一個自訂標籤，`setup-python` 與 `pip install git+https` 都成功）；排程觸發的補算 run 另外在一個公開 repo 的 GitHub-hosted runner 上實跑通過（當時有 20 個符合條件的單：`select` 與 20 個 ticket job 都成功，各產生一份 artifact 與 `index.json`）。這些都只影響呼叫端自己的 repo。
7. **慣例提醒**。每一輪審查的第一行與 PR 內文的 `Closes`／`Refs`，照本檔 [§1](#1-每一輪審查結論pr-留言的第一行)、[§2](#2-pr-內文寫單號) 的格式寫，否則算不到。

導入檢查表：

- [ ] 拉取憑證的範圍已包含新 repo
- [ ] 呼叫端 workflow 與 config（例如 `.github/taskquality.json`）已放進該 repo
- [ ] `uses:` 與 `qmetrics-ref` 都 pin 完整 SHA（或 tag 對應的 SHA），兩者是同一版
- [ ] 第一天手動跑一次，確認 artifact 名稱與 `index.json` 正常
- [ ] 之後每週拉取一次最新 run 的結果
