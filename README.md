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
      qmetrics-ref: main       # replace with a tag or commit SHA
```

The workflow checks out the full history (`fetch-depth: 0`; a shallow clone is a tool error), runs `qmetrics diff`, writes a summary to the job summary and uploads `qmetrics.json`. It only reports: the job fails only if qmetrics itself errors. Python projects only for now.
