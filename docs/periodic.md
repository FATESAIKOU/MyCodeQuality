# 定期品質報告：慣例

本頁說明 PR 要怎麼寫，`taskquality` 才能正確讀到審查結論與單號。格式以現行程式的行為為準；`tests/test_conventions_lock.py` 把這裡的每一列鎖成測試（契約 C-P1、C-P2）。內建 config 不改，所以這些格式不會因為升版而變。

範例都用合成資料：單是 `acme/widgets#310`，PR 也在 `acme/widgets`。

## 1. 每一輪審查結論：PR 留言的第一行

格式（逐字，`<…>` 換成實際內容）：

```
審查：<provider>/<model> 結論：<結論字>（head <commit SHA>）
```

- `審查`、`結論` 後面是**全形冒號** `：`。
- `<model>` 與 `結論` 之間是**一個半形空白**。
- 括號是**全形** `（` `）`；`head` 與 SHA 之間是一個半形空白。
- SHA 是**小寫**十六進位，7～40 碼。
- `<provider>/<model>` 中間不能有空白。
- `<結論字>` 只能是下列之一：
  - 通過：`可以 merge`、`通過`
  - 要修：`要修`、`要退回`、`要退回設計`
  - 其他字會被當成 `other`，該 PR 的審查各項（`review_first_pass`、`fix_rounds` 等）會是 `null`（`unrecognized_verdict`）；`re_reviews` 不受影響，仍是數字（實測為 `0`）。
- 補充說明寫在 `）` **之後**（同一行），或寫在第二行以下。不要寫進括號裡。
- 這一行必須是留言的**第一行**，前面不能有空白或 markdown。
- 每一輪都要貼，包含「要修」那幾輪；head 是該輪審查的 commit。
- 結構審查用同格式、角色字換成 `結構審查`。它會被認出來，但不進審查指標。

| 寫法（逐字） | 結果 |
|---|---|
| `審查：vendor/model-x 結論：可以 merge（head 4cac21d）` | ✅ 通過 |
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
| `審查：vendor/model-x 結論：可以 merge（head 4cac21d；無高）` | ❌ 括號內有補充 |
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

  程式碼時改用 `--rev <commit SHA> --target main`，不給 `--ticket` 與 `--search-repo`。`--file` 可重複，檔案必須是帶 `kind` 與 `schema_version` 的 JSON，否則 exit 2。

- `mcq-report name`：印出 artifact 名稱（一行）。

  ```bash
  mcq-report name code --repo acme/widgets --target main --committed-at 2030-01-02T23:59:59Z --rev <commit SHA>
  mcq-report name task --ticket acme/widgets#11 --closed-at 2030-01-02T05:00:00Z --run-at 2030-01-05T00:00:00Z \
    --report taskquality-report.json --snapshot taskquality-snapshot.json --settle-days 2
  ```

- `mcq-report select`：決定任務 workflow 這次要算哪些單，輸出一行 JSON：`{"tickets": [...], "truncated": [...], "skipped_final": [...], "skipped_not_completed": [...]}`。
  - `--event` 是 `issues`、`schedule`、`workflow_dispatch` 之一。
  - `schedule` 與 `issues` 要給 `--gh-issues`、`--gh-artifacts`（分別是 `gh issue list`、`gh issue view` 與 `gh api --paginate --slurp` 的輸出）。`workflow_dispatch` 給 `--tickets`（空白分隔的單號）。
  - `--max-tickets`（預設 20，上限 256）之外的單放進 `truncated`，摘要用 `::warning::` 標示，不讓 job 失敗。
  - `gh issue list` 的結果不依 `closedAt` 排序，所以排序在指令裡做。結果剛好 1000 筆時表示可能被截斷，exit 2，請縮小 `--backfill-days`。
  - 摘要寫到 `--summary` 指定的檔案；沒給時寫到 stderr。

工具錯誤（參數錯、JSON 形狀不對、檔案讀不到）一律 exit 2，訊息寫在 stderr。
