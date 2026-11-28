# 審查行文法與機器可讀測試向量

本文件定義 MyCodeQuality 中「審查行（Review Line）」的完整文法規則、解析結果欄位語義、角色與註記相容規則、合併時間判定及 CI 合併閘門條件。外部工具（例如 CI 閘門、定期品質報告、自動化合併機器人）應引用同一份文法與測試向量標準。

所有範例與說明一律使用合成資料（例如 `vendor/model-x`、`acme/widgets`）。

---

## 1. 文法與 Pattern 逐欄說明

審查行必須位於 PR 留言的**第一行**（`first_line`），行首不得有任何空白字元或 Markdown 語法（例如粗體 `**` 或引用 `>`）。

內建標準比對模式（`DEFAULT_CONFIG["verdict_pattern"]`）：

```python
r"^(?P<role>\S*審查)：(?P<model>[^\s（）]+)(?:（(?P<note>[^）]*)）)? 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})(?:[；;][^）]*)?）"
```

各欄位與字元規則逐段說明如下：

| 段落 | 正規表示式群組 / 字元 | 說明 |
|---|---|---|
| 行首錨點 | `^` | 嚴格比對行首，行首有空白（如 ` 審查：...`）或 Markdown 標記將無法匹配。 |
| 審查角色 | `(?P<role>\S*審查)` | 角色名稱，由零或多個非空白字元接「審查」結尾（例如 `審查`、`結構審查`、`安全審查`）。 |
| 角色冒號 | `：` | 必須使用**全形冒號**。半形冒號 `:` 視為不匹配。 |
| 模型名稱 | `(?P<model>[^\s（）]+)` | 模型識別字串（如 `vendor/model-x`）。不可包含空白（半形或全形）或全形括號 `（` `）`。半形括號 `()` 會被視為 model 名稱的一部分。若模型名稱含空白（如 `Vendor Model X (Medium)`）將無法匹配。 |
| 可選全形註記 | `(?:（(?P<note>[^）]*)）)?` | 選填，接在模型名稱後。必須為**全形括號** `（` `）`，括號內不得包含 `）`，但**可包含空白**或標點（如 `（pipe a, high）`）。無註記時 `note` 為 `null`，空括號 `（）` 時 `note` 為空字串 `""`。註記不進入審查指標。若括號為半形 `()` 則不被當成註記，而是被併入 `model`。 |
| 分隔空白 | ` ` | 模型（或其註記）與「結論：」之間必須有恰好**一個半形空白**。不得省略，也不得使用全形空白 `　`。 |
| 結論標籤 | `結論：` | 固定中文字「結論」接**全形冒號** `：`。 |
| 結論內容 | `(?P<verdict>[^（]+)` | 結論字串，不含全形開括號 `（`。解析時會去除首尾空白（`.strip()`）。 |
| head 標籤 | `（head ` | 必須以**全形開括號** `（` 開頭，接固定小寫英文字串 `head` 及一個半形空白。若括號不以 `head ` 開頭（如 `（審查對象 1111111；head 2222222）`）或缺少 head 關鍵字將無法匹配。 |
| head SHA | `(?P<head>[0-9a-f]{7,40})` | 審查目標 commit SHA，必須為 7 到 40 碼的**小寫十六進位**字元（`0-9a-f`）。大寫字母或 6 碼、41 碼均無法匹配。 |
| 可選補充說明 | `(?:[；;][^）]*)?` | head 括號內的可選補充說明。必須緊接在 head 後方以**全形分號 `；`** 或**半形分號 `;`** 起始，內容不含全形閉括號 `）`。若出現此補充，該行被標記為非標準（`nonstandard`）。 |
| head 閉括號 | `）` | 必須使用**全形閉括號** `）`。不得使用半形括號 `)`。 |
| 結尾補充 | （無 `$` 錨點） | pattern 結尾未加 `$`，因此全形閉括號 `）` 之後同一行接續的說明文字（例如 ` 高 1、中 3，報告見 REPORT-12-review.md`）不影響解析。 |

---

## 2. 解析結果欄位定義

機器可讀向量檔 `tests/vectors/review_lines.json` 中每一筆測試向量均包含下列 12 個欄位（鍵名固定、順序固定）：

```json
{
  "id": "kebab-case-unique-identifier",
  "line": "逐字留言第一行",
  "parsed": true,
  "role": "審查",
  "model": "vendor/model-x",
  "note": null,
  "verdict_class": "pass",
  "head": "4cac21d",
  "counts_as_review": true,
  "unparsed": false,
  "nonstandard": false,
  "structure_note": false
}
```

各欄位定義：

1. `id`（字串，必填）：唯一識別碼，採 kebab-case（小寫英數字與連字號）。
2. `line`（字串，必填）：PR 留言第一行逐字字串。
3. `parsed`（布林值，必填）：是否成功由內建 pattern 比對且 `role`、`model`、`verdict`、`head` 均有值。若為 `false`，則 `role`、`model`、`note`、`verdict_class`、`head` 全為 `null`。
4. `role`（字串或 `null`）：解析出的角色名稱（如 `"審查"`、`"結構審查"`）。
5. `model`（字串或 `null`）：解析出的模型識別碼。
6. `note`（字串或 `null`）：全形註記內容。若無註記為 `null`；若註記為空括號 `（）` 則為 `""`。
7. `verdict_class`（字串或 `null`）：依內建設定分類之結論類別，只能是 `"pass"`、`"fail"`、`"other"` 之一（`parsed` 為 `false` 時為 `null`）：
   - `"pass"`：`verdict.strip()` 屬於 `pass_verdicts`（`["可以 merge", "通過"]`）。
   - `"fail"`：`verdict.strip()` 屬於 `fail_verdicts`（`["要修", "要退回", "要退回設計"]`）。
   - `"other"`：其餘未列入清單的結論字串（如 `"可以"`、`"LGTM"`）。
8. `head`（字串或 `null`）：小寫十六進位 commit SHA（7～40 碼）。
9. `counts_as_review`（布林值，必填）：是否計入一般審查指標序列。
   - 判定條件：`parsed` 為真 ∧ `role` 屬於 `review_roles`（內建預設為 `["審查"]`）∧ 未因註記規則（含「架構／結構」）被排除。
10. `unparsed`（布林值，必填）：看似審查行但無法解析。
    - 判定條件：`not parsed` 且開頭符合 `^\S*審查：`。此類留言在系統中會計入 `unparsed_verdict_lines` 警示計數。
11. `nonstandard`（布林值，必填）：是否為容忍但非標準之審查行。
    - 判定條件：`counts_as_review` 為真 ∧ head 後緊接全形分號 `；` 或半形分號 `;`。計入 `nonstandard_verdict_lines`。
12. `structure_note`（布林值，必填）：是否因舊式註記規則被排除出一般審查。
    - 判定條件：`parsed` 為真 ∧ `role` 屬於 `review_roles` ∧ `note` 中包含「架構」或「結構」字樣。計入 `structure_note_verdicts`。

---

## 3. 角色與結構審查規則

### 「審查：」與「結構審查：」的分別
- 系統透過 `review_roles` 設定決定哪些角色計入審查序列，預設僅有 `["審查"]`。
- 若留言行以 `結構審查：` 開頭，文法 pattern 能夠正常匹配（`parsed=true`），但因角色不在 `review_roles` 中，故不計入審查指標（`counts_as_review=false`）。
- 結構審查結果獨立於一般審查指標之外。

### 註記含「架構／結構」的相容規則
- **舊相容寫法**：歷史上曾有審查員在 `審查：` 行中以註記方式標註結構審（例如 `審查：vendor/model-x（架構師結構審） 結論：通過（head 1234567）` 或 `審查：vendor/model-x（架構師） 結論：通過（head 1234567）`）。
- 當角色為 `審查` 且註記內容包含「架構」或「結構」字樣時，系統視為結構審查：
  - `parsed`: `true`
  - `counts_as_review`: `false`
  - `structure_note`: `true`（計入 `structure_note_verdicts`）
- **統一規範**：所有架構師與結構審查往後一律強制使用 `結構審查：` 開頭，不可再依賴註記相容規則。

### 半形括號不當註記
- 註記必須使用**全形括號** `（` `）`。
- 若使用半形括號 `(...)`，pattern 的 `model` 段 `[^\s（）]+` 會將半形括號整段視為模型名稱的一部分（例如 `vendor/model-x(結構)`）。
- 由於其未被匹配至 `note` 群組，因此不會觸發註記中的「結構」排除邏輯，仍會被算入一般審查指標（`counts_as_review=true`）。若半形括號前有空白（如 ` (PMO-rev)`），則會因空白導致 model 比對中斷而失敗（`unparsed=true`）。

---

## 4. 合併前／後的採計規則

對於已合併（`merged`）的 PR，審查結論的採計具有嚴格的時間點限制：

- **只採計合併前**：審查結論序列僅包含留言時間 `at ≤ merged_at` 的審查行（同一秒算在內）。
- **合併後審查分離**：若審查行貼出的時間 `at > merged_at`，不納入一般結論序列，改計入 `post_merge_verdicts`。
- **指標隔離**：合併後的審查行不會影響一次通過（`first_review_pass`）、修復輪數（`fix_rounds`）、重審次數（`re_reviews`）、`approved_head_stale` 或未審先合（`unreviewed_merged_prs`）之計算。

---

## 5. 合併閘門用法（Gate Criteria）

CI 閘門或自動化合併工具判定「審查是否可以放行」時，必須嚴格同時滿足以下三個條件：

$$\text{可以放行} \iff \text{parsed} \land (\text{verdict\_class} == \text{"pass"}) \land \text{counts\_as\_review}$$

- 若 `parsed == false`：非合法審查行，不放行。
- 若 `verdict_class == "other"`：結論字串非正式通過詞（例如寫成「可以」），審查指標為 `null`，不放行。
- 若 `verdict_class == "fail"`：審查要求退回或修改，不放行。
- 若 `counts_as_review == false`：屬於結構審查或架構註記排除，不能代表一般審查放行。

---

## 6. 引用方式與版本慣例

- **檔案位置**：本規範的機器可讀測試向量存放於 repository 的 `tests/vectors/review_lines.json`。
- **引用機制**：外部專案或合併閘門規則表應透過固定 Release Tag 的 GitHub Raw URL 引用測試向量，例如：
  `https://raw.githubusercontent.com/FATESAIKOU/MyCodeQuality/<TAG>/tests/vectors/review_lines.json`
- **契約原則**：**改向量＝改慣例**。任何對審查行解析規則的修訂，必須先更新向量檔並通過回歸測試，禁止在不更新向量的情況下私自變更解析實作。

---

## 7. 範例對照（取自測試向量）

### 正例（`parsed: true` 且 `counts_as_review: true`）

| 向量 ID | 留言第一行（逐字） | verdict_class | 說明 |
|---|---|---|---|
| `periodic-row-01-std-pass-can-merge` | `審查：vendor/model-x 結論：可以 merge（head 4cac21d）` | pass | 最簡標準通過格式 |
| `std-pass-tong-guo` | `審查：vendor/model-x 結論：通過（head 1234567）` | pass | 「通過」標準詞 |
| `periodic-row-02-note-with-spaces` | `審查：vendor/model-x（pipe a, high） 結論：可以 merge（head 1234567）` | pass | 註記含空白合法 |
| `note-empty` | `審查：vendor/model-x（） 結論：可以 merge（head 4cac21d）` | pass | 空註記 `note=""` |
| `periodic-row-04-std-fail-yao-xiu` | `審查：vendor/model-x 結論：要修（head 30b3c96）` | fail | 「要修」標準詞 |
| `periodic-row-05-std-fail-tui-hui-40hex` | `審查：vendor/model-y 結論：要退回（head 30b3c96a1b2c3d4e5f60718293a4b5c6d7e8f901）` | fail | 40 碼 SHA 合法 |
| `std-fail-tui-hui-she-ji` | `審查：vendor/model-x 結論：要退回設計（head 30b3c96）` | fail | 「要退回設計」標準詞 |
| `periodic-row-06-supplement-after-closing-paren` | `審查：vendor/model-x 結論：要修（head 30b3c96） 高 1、中 3，報告見 REPORT-12-review.md` | fail | 閉括號後接補充文字合法 |
| `periodic-row-16-head-fullwidth-semicolon-note` | `審查：vendor/model-x 結論：可以 merge（head 4cac21d；無高）` | pass | head 後容許全形分號補充（`nonstandard=true`） |
| `head-ascii-semicolon-note` | `審查：vendor/model-x 結論：可以 merge（head 4cac21d;說明）` | pass | head 後容許半形分號補充（`nonstandard=true`） |

### 特殊角色與註記排除（`parsed: true` 但 `counts_as_review: false`）

| 向量 ID | 留言第一行（逐字） | structure_note | 說明 |
|---|---|---|---|
| `periodic-row-08-arch-review-role` | `結構審查：vendor/model-z 結論：通過（head 7c3e45b）` | false | 角色為「結構審查」，不計入一般審查指標 |
| `structure-note-arch-struct` | `審查：vendor/model-x（架構師結構審） 結論：通過（head 1234567）` | true | 舊式註記含「架構／結構」排除 |
| `structure-note-arch-only` | `審查：vendor/model-x（架構師） 結論：通過（head 1234567）` | true | 舊式註記含「架構」排除 |
| `other-role-security` | `安全審查：vendor/model-s 結論：通過（head 1234567）` | false | 角色不在 review_roles |

### 反例（`parsed: false`）

| 向量 ID | 留言第一行（逐字） | unparsed | 原因 |
|---|---|---|---|
| `periodic-row-09-halfwidth-colon-role` | `審查:vendor/model-x 結論：可以 merge（head 4cac21d）` | false | 角色後為半形冒號（不合 `^\S*審查：`） |
| `periodic-row-10-no-space-before-conclusion` | `審查：vendor/model-x結論：可以 merge（head 4cac21d）` | true | 模型與結論間缺少空格 |
| `periodic-row-11-fullwidth-space-conclusion` | `審查：vendor/model-x　結論：可以 merge（head 4cac21d）` | true | 結論前使用全形空白 |
| `periodic-row-12-halfwidth-paren-head` | `審查：vendor/model-x 結論：可以 merge(head 4cac21d)` | true | head 括號為半形 |
| `periodic-row-13-uppercase-hex-head` | `審查：vendor/model-x 結論：可以 merge（head 4CAC21D）` | true | SHA 含大寫十六進位 |
| `periodic-row-14-head-6-chars` | `審查：vendor/model-x 結論：可以 merge（head 4cac21）` | true | SHA 僅 6 碼（需 7～40 碼） |
| `head-41-chars` | `審查：vendor/model-x 結論：可以 merge（head 30b3c96a1b2c3d4e5f60718293a4b5c6d7e8f901a）` | true | SHA 為 41 碼 |
| `periodic-row-15-head-colon-after-keyword` | `審查：vendor/model-x 結論：可以 merge（head: 4cac21d）` | true | `head:` 多了冒號 |
| `head-not-at-start-of-paren` | `審查：vendor/model-x 結論：可以 merge（審查對象 1111111；head 2222222）` | true | 括號非以 head 開頭 |
| `periodic-row-19-model-spaces` | `審查：vendor/Model X (Medium) 結論：可以 merge（head 8521f31）` | true | 模型名稱包含空白 |
| `periodic-row-21-markdown-bold` | `**審查**：vendor/model-x 結論：可以 merge（head 4cac21d）` | false | Markdown 粗體開頭 |
| `periodic-row-22-leading-space` | ` 審查：vendor/model-x 結論：可以 merge（head 4cac21d）` | false | 行首有空白 |
| `plain-comment-en` | `LGTM! Thanks for the fix.` | false | 一般英文留言 |
