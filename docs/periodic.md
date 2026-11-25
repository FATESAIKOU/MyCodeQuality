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
