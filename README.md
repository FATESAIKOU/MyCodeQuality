# MyCodeQuality
Deterministic code-quality metrics (no LLM): a small CLI plus a reusable GitHub Actions workflow.

## Use it in another repo

Add a workflow that calls the reusable one. Pin `qmetrics-ref` to a tag or commit so the numbers stay reproducible.

```yaml
name: quality
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  quality:
    uses: FATESAIKOU/MyCodeQuality/.github/workflows/quality.yml@main
    with:
      python-version: "3.12"   # pin: AST output can differ between minor versions
      src: src
      tests: tests
      qmetrics-ref: <full commit SHA>  # pin: "main" moves, so the same inputs can give different numbers
```

The workflow checks out the full history (`fetch-depth: 0`; a shallow clone is a tool error), runs `qmetrics diff`, writes a summary to the job summary and uploads `qmetrics.json`. It only reports: metric values never fail the job. It fails on tool errors (qmetrics exits non-zero) and infrastructure errors (checkout, pip install, file redirection, step summary, artifact upload). Python projects only for now.

## Task quality (`taskquality`)

`taskquality fetch` writes a ticket snapshot (including `ticket_labels`, the ticket's labeled/unlabeled events, no actors); `taskquality score` turns it into metrics. Config v2 adds two optional keys: `started_label` (start the cycle at the first `labeled` event of that label) and `ci_required` (`false` stops requiring CI for `clean`). A config with `schema_version: 1` that contains either key is rejected with `config_bad_shape`, by design. Details: [docs/taskquality.md](docs/taskquality.md).

## Optional gate (Q1)

By default the workflow only reports. Set `fail-on: q1` to also fail **pull_request** runs (pushes stay report-only) when either of two events, whose baseline is 0, appears:

- `crossing_1000`: a file crosses 1000 lines;
- `ast_dup`: a new function has the same AST as an existing one.

If either count is `null` (undetermined, e.g. a syntax error under `src`), the gate fails too. A reviewer who has judged the change acceptable lets it through by adding the exact label `quality:arch-ok` to the PR (case-sensitive, no near matches); the gate then prints a notice instead of failing. Make the calling workflow also run on `labeled` and `unlabeled` so adding the label re-runs the check:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled]
jobs:
  quality:
    uses: FATESAIKOU/MyCodeQuality/.github/workflows/quality.yml@<ref>
    with:
      fail-on: q1
```

The decision is also a CLI: `qmetrics gate --file qmetrics.json --event <push|pull_request> --labels-json '["quality:arch-ok"]'`. Exit 0 = pass (or event not judged), 1 = gate failed, 2 = tool error (report file missing, not JSON, wrong shape, bad labels JSON; stderr has a code and a message). It reads only the given file: no network, same input gives the same output. `qmetrics diff` and its JSON schema are unchanged.

In this repo's own `ci.yml`, `qmetrics-ref` is the PR head SHA (or the pushed SHA): the repo measures itself with the version under test. Other repos should still pin a tag or commit.

## Measure whole repository (`qmetrics repo`)

Measure the static code quality of an entire repository at a single commit:

```bash
qmetrics repo [--repo PATH] [--rev REV] [--src src] [--tests tests] [--json]
```

- `--rev`: commit to measure (default: `HEAD`). It measures the committed tree at that revision; uncommitted changes in the working tree are ignored.
- Supports shallow repositories (does not require full history).
- Exit codes: 0 = success, 2 = tool error (stderr: `qmetrics: error <code>: <message>`).

### Output format

Without `--json`, prints a human-readable summary. With `--json`, prints a deterministic JSON object following design §3.4:

- `applicable`: boolean, `true` if any `.py` file exists under `src`, `false` otherwise.
- `totals`: `files` (.py count), `lines` (total line count), `functions` (function/method count), `tests` (count of `test_*` functions in `tests`), `cognitive_units` (scoring units: functions not nested in another function) and `cognitive` (sum of their cognitive complexity).
- `counts`: `long_files` (> 1000 lines), `long_functions` (> 50 lines), `deep_functions` (nesting depth >= 4), `ast_dup_functions` (AST-identical functions >= 5 lines, grouped: size - 1 summed), `dup_windows` (6-line duplicate code windows appearing across >= 2 files), `complex_functions` (cognitive complexity > 15 per scoring unit; not part of `smell_events`), `dup_lines` (distinct source rows that fall inside a `dup_windows` window; not part of `smell_events`), and `smell_events` (sum of the five categories).
- `ratios`: `{num, den}` ratios for `long_files` (den: `totals.files`), `long_functions`, `deep_functions`, and `ast_dup_functions` (den: `totals.functions`), `complex_functions` (den: `totals.cognitive_units`, which is not `totals.functions`), and `dup_lines` (den: `totals.lines`). If denominator is 0, the ratio is `null`. No floating-point numbers are output.
- `findings`: detail list for each detected issue (`long_file`, `long_function`, `deep_function`, `ast_dup_function`, `complex_function`, `dup_windows`, `import_cycle`: one entry per module in an import cycle, `value` = size of that cycle), sorted deterministically by `(kind, file, function, value)`.
- `arch`: module import graph under `src` (Python only, stdlib `ast`). `modules`, `edges`, `cycles` (strongly connected components of size >= 2), `modules_in_cycles`, `max_fan_in`, `max_fan_out`, `unresolved_internal_like` and `unresolved_self_prefix` (signs that the import root is wrong; they warn, they do not fix), `shadowed_files` (a `x.py` hidden by `x/__init__.py`), and `packages[]` with Martin's Ca, Ce and instability (`null` when Ca + Ce is 0). Imports inside functions and under `TYPE_CHECKING` count as dependencies; re-exports from a package's `__init__` back into its own children do not. Cycle counts are a trend, not a to-do list. `arch` is `null` when `src` fails to parse, and all zeros with empty `packages` when `src` has no `.py` files.

  Import root limits: module names are relative to the import root.
  When `--src` is a directory that has an `__init__.py`, names get that directory's name as a prefix
  (`acme/widgets.py` is `acme.widgets`); with `--src .` there is no prefix.
  A relative import that climbs above the import root (e.g. `from ...y import z` in a depth-1 package)
  is not an edge. `from ..y import z` in a depth-1 package resolves to the root-level module `y`;
  that is a known loose spot, kept on purpose.
  Known blind spot: a flat import (`import util` in a package under `--src` that has an `__init__.py`)
  resolves to nothing and silently counts as 0 edges, with no warning.
  `arch_import_root_suspect` means an unresolved import matches a module under `--src` at a deeper path
  (`--src` is probably too shallow) or starts with `--src`'s own directory name (the import root is
  probably its parent); the numbers are not changed, only the warning is set.
  `arch_module_shadowed` means two files give the same module name (`x.py` and `x/__init__.py`, or
  `a.b.py` and `a/b.py`); one of them is listed in `shadowed_files` and not analyzed.

- Cognitive complexity is a self-written approximation over Python's `ast` (not SonarQube's numbers: parenthesized boolean sequences, `match` guards, lambdas and recursion are counted differently or not at all). Known limitation (#31): two functions with the same qualified name under different parents (for example `def f` at module level and `def f` inside an `if`) share a key, and the later one replaces the earlier, so that unit is dropped from `cognitive_units`/`cognitive`; `metrics.funcs` behaves the same way.
- `parse_failures`: files that failed to parse (`{file, scope}`). If any file in `src` fails to parse, `totals.functions`, `totals.cognitive_units`, `totals.cognitive`, `counts`, `ratios`, and `findings` are `null` (fail-closed); if in `tests`, `totals.tests` is `null`.
- `warnings`: sorted array of codes from the preflight checks (such as `alternates_present`, `replace_refs_present`) and from `arch` (`arch_import_root_suspect`, `arch_module_shadowed`).

## Limits

- The checks were validated on a small sample; the two Q1 events have no real positive example among real PRs yet (only synthetic cases).
- A copy that only renames variables has a different AST and is not detected.
- A docstring-only change counts as a code change (the comparison is on the literal AST).
- `null` means "undetermined" (for example a syntax error under `src`); Q1 treats it as a failure (fail-closed) until the label is added.
