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

## Limits

- The checks were validated on a small sample; the two Q1 events have no real positive example among real PRs yet (only synthetic cases).
- A copy that only renames variables has a different AST and is not detected.
- A docstring-only change counts as a code change (the comparison is on the literal AST).
- `null` means "undetermined" (for example a syntax error under `src`); Q1 treats it as a failure (fail-closed) until the label is added.
