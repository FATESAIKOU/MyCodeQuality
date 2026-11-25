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
- `totals`: `files` (.py count), `lines` (total line count), `functions` (function/method count), `tests` (count of `test_*` functions in `tests`).
- `counts`: `long_files` (> 1000 lines), `long_functions` (> 50 lines), `deep_functions` (nesting depth >= 4), `ast_dup_functions` (AST-identical functions >= 5 lines, grouped: size - 1 summed), `dup_windows` (6-line duplicate code windows appearing across >= 2 files), and `smell_events` (sum of the five categories).
- `ratios`: `{num, den}` ratios for `long_files` (den: `totals.files`), `long_functions`, `deep_functions`, and `ast_dup_functions` (den: `totals.functions`). If denominator is 0, the ratio is `null`. No floating-point numbers are output.
- `findings`: detail list for each detected issue (`long_file`, `long_function`, `deep_function`, `ast_dup_function`, `dup_windows`), sorted deterministically by `(kind, file, function, value)`.
- `parse_failures`: files that failed to parse (`{file, scope}`). If any file in `src` fails to parse, `totals.functions`, `counts`, `ratios`, and `findings` are `null` (fail-closed); if in `tests`, `totals.tests` is `null`.
- `warnings`: array of preflight check warnings (such as `alternates_present`, `replace_refs_present`).

## Limits

- The checks were validated on a small sample; the two Q1 events have no real positive example among real PRs yet (only synthetic cases).
- A copy that only renames variables has a different AST and is not detected.
- A docstring-only change counts as a code change (the comparison is on the literal AST).
- `null` means "undetermined" (for example a syntax error under `src`); Q1 treats it as a failure (fail-closed) until the label is added.
