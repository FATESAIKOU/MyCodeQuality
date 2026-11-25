"""C-P10 and C-P12: static checks on the two reusable workflows.

YAML is parsed with PyYAML, so structure is checked on the parsed document, not by matching text.
PyYAML reads the bare key `on` as the boolean True (YAML 1.1), so the trigger block is looked up as True.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CODE = WORKFLOWS / "code-quality-report.yml"
TASK = WORKFLOWS / "task-quality-report.yml"
CI = WORKFLOWS / "ci.yml"

READS = {"contents": "read", "issues": "read", "pull-requests": "read", "actions": "read"}
PERMISSIONS = {CODE: {"contents": "read"}, TASK: READS}
USES_RE = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)@([0-9a-f]{40})")
FAILURE_SWALLOWED_RE = re.compile(r"\|\|\s*(true|:|exit\s+0)\b")


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def trigger(doc):
    return doc[True] if True in doc else doc["on"]


def steps_of(doc):
    for job_name, job in doc["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


def runs_of(doc):
    return [step["run"] for _, step in steps_of(doc) if "run" in step]


def keys_named(node, name):
    """Every mapping key called `name` anywhere in the document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == name:
                yield k
            yield from keys_named(v, name)
    elif isinstance(node, list):
        for item in node:
            yield from keys_named(item, name)


@pytest.fixture(params=[CODE, TASK], ids=["code", "task"])
def wf(request):
    return request.param, load(request.param)


# --- C-P10 ------------------------------------------------------------------------


def test_c_p10_only_workflow_call_trigger(wf):
    path, doc = wf
    assert set(trigger(doc)) == {"workflow_call"}


def test_c_p10_permissions_are_exactly_the_design_set(wf):
    path, doc = wf
    assert doc["permissions"] == PERMISSIONS[path]
    for job_name, job in doc["jobs"].items():
        for perm, level in job.get("permissions", {}).items():
            assert level == "read", f"{job_name} grants {perm}: {level}"
            assert perm in PERMISSIONS[path], f"{job_name} grants {perm}, not in the design set"


def test_c_p10_no_secrets(wf):
    path, doc = wf
    assert list(keys_named(doc, "secrets")) == []
    assert "secrets" not in trigger(doc)["workflow_call"]


def test_c_p10_qmetrics_ref_required_without_default(wf):
    path, doc = wf
    spec = trigger(doc)["workflow_call"]["inputs"]["qmetrics-ref"]
    assert spec["required"] is True
    assert "default" not in spec


def test_c_p10_run_strings_have_no_expressions(wf):
    path, doc = wf
    for run in runs_of(doc):
        assert "${{" not in run, run


def test_c_p10_every_uses_is_pinned_to_a_full_sha_with_version_comment(wf):
    path, doc = wf
    text_lines = path.read_text(encoding="utf-8").splitlines()
    uses = [step["uses"] for _, step in steps_of(doc) if "uses" in step]
    assert uses, "expected at least one action"
    for ref in uses:
        assert USES_RE.fullmatch(ref), ref
    for line in text_lines:
        if re.search(r"^\s*-?\s*uses:", line):
            assert re.search(r"#\s*v\d", line), f"no version comment: {line.strip()}"


def test_c_p10_checkout_never_persists_credentials(wf):
    path, doc = wf
    for _, step in steps_of(doc):
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False


def test_c_p10_task_ticket_job_matrix_and_concurrency():
    doc = load(TASK)
    job = doc["jobs"]["ticket"]
    assert job["strategy"]["matrix"]["ticket"] == "${{ fromJSON(needs.select.outputs.tickets) }}"
    assert job["strategy"]["max-parallel"] == 1
    assert job["strategy"]["fail-fast"] is False
    assert "matrix.ticket" in job["concurrency"]["group"]
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "if" in job and "count" in job["if"]


def test_c_p10_fetch_passes_search_repo_from_github_repository():
    doc = load(TASK)
    fetch_runs = [run for run in runs_of(doc) if "taskquality fetch" in run]
    assert len(fetch_runs) == 1
    assert '--search-repo "$GITHUB_REPOSITORY"' in fetch_runs[0]


def test_c_p10_select_job_runs_mcq_report_select():
    doc = load(TASK)
    assert any("mcq-report select" in run for run in runs_of(doc))


def test_c_p10_closed_check_gates_every_later_step():
    steps = load(TASK)["jobs"]["ticket"]["steps"]
    assert steps[0]["id"] == "closed"
    gate = "steps.closed.outputs.closed == 'true'"
    for step in steps[1:]:
        cond = str(step.get("if", ""))
        assert gate in cond and "success()" in cond, step["name"]


def test_c_p10_closed_check_warns_and_skips_without_failing():
    run = load(TASK)["jobs"]["ticket"]["steps"][0]["run"]
    assert "COMPLETED" in run
    assert "::warning::" in run
    assert 'echo "closed=false" >> "$GITHUB_OUTPUT"' in run
    assert "exit" not in run


def test_c_p10_ci_runs_actionlint_on_both_workflows():
    text = CI.read_text(encoding="utf-8")
    assert "ACTIONLINT_SHA256" in text
    assert "sha256sum -c" in text
    assert "actionlint .github/workflows/code-quality-report.yml .github/workflows/task-quality-report.yml" in text


# --- C-P12 ------------------------------------------------------------------------


def test_c_p12_every_run_fails_on_error(wf):
    path, doc = wf
    for run in runs_of(doc):
        assert run.lstrip().startswith("set -euo pipefail"), run.splitlines()[0]
        assert not FAILURE_SWALLOWED_RE.search(run), run


def test_c_p12_no_continue_on_error_anywhere(wf):
    path, doc = wf
    assert list(keys_named(doc, "continue-on-error")) == []


# --- PR-P4 review fixes: supply chain, wiring and the ci.yml checksum step -----------

ALLOWED_OWNERS = {"actions"}
# The three SHAs this PR uses (they are the v4.2.2, v5.6.0 and v4.6.2 tags). Changing one means changing this table too.
PINNED = {
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
PIP_PREFIX = 'python -m pip install "git+https://github.com/FATESAIKOU/MyCodeQuality.git@'
ACTIONLINT_PIN = {
    "ACTIONLINT_VERSION": "1.7.12",
    "ACTIONLINT_SHA256": "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
}
UPLOAD_JOB = {CODE: "code", TASK: "ticket"}
UPLOAD_PATH = {CODE: "${{ runner.temp }}/mcq-out", TASK: "${{ runner.temp }}/mcq-task"}


def step_named(doc, job, name):
    matches = [s for s in doc["jobs"][job]["steps"] if s.get("name") == name]
    assert len(matches) == 1, name
    return matches[0]


def stripped_lines(text):
    return [line.strip() for line in text.splitlines()]


def test_m2_pip_install_url_starts_with_the_fixed_repo(wf):
    path, doc = wf
    installs = [run for run in runs_of(doc) if "pip install" in run]
    assert installs
    for run in installs:
        command = next(line for line in stripped_lines(run) if "pip install" in line)
        assert command.startswith(PIP_PREFIX), command


def test_m2_every_uses_is_an_allowed_owner_at_its_pinned_sha(wf):
    path, doc = wf
    for _, step in steps_of(doc):
        if "uses" not in step:
            continue
        owner, repo, sha = USES_RE.fullmatch(step["uses"]).groups()
        assert owner in ALLOWED_OWNERS, step["uses"]
        assert PINNED.get(f"{owner}/{repo}") == sha, step["uses"]


def test_m2_setup_python_follows_the_python_version_input(wf):
    path, doc = wf
    for _, step in steps_of(doc):
        if step.get("uses", "").startswith("actions/setup-python@"):
            assert step["with"]["python-version"] == "${{ inputs.python-version }}"


def test_m2_no_secret_expressions_anywhere_in_the_file(wf):
    path, doc = wf
    assert "secrets." not in path.read_text(encoding="utf-8")


def test_m2_upload_name_path_retention_and_overwrite_are_wired(wf):
    path, doc = wf
    up = step_named(doc, UPLOAD_JOB[path], "Upload artifact")["with"]
    assert up["name"] == "${{ steps.name.outputs.name }}"
    assert up["path"] == UPLOAD_PATH[path]
    assert up["if-no-files-found"] == "error"
    assert up["retention-days"] == "${{ inputs.retention-days }}"
    assert up["overwrite"] is True


def test_m2_code_checkout_honours_the_rev_input():
    checkout = load(CODE)["jobs"]["code"]["steps"][0]
    assert checkout["with"]["ref"] == "${{ inputs.rev != '' && inputs.rev || github.sha }}"


def test_m2_ticket_job_if_is_exactly_the_empty_matrix_guard():
    assert load(TASK)["jobs"]["ticket"]["if"] == "needs.select.outputs.count != '0'"


def test_m2_name_step_takes_closed_at_from_check_closed():
    env = step_named(load(TASK), "ticket", "Name")["env"]
    assert env["CLOSED_AT"] == "${{ steps.closed.outputs.closed_at }}"


def test_m2_index_passes_search_repo_from_github_repository():
    run = step_named(load(TASK), "ticket", "Index")["run"]
    assert '--search-repo "$GITHUB_REPOSITORY"' in run


def test_m2_check_closed_only_marks_completed_tickets_closed():
    lines = stripped_lines(step_named(load(TASK), "ticket", "Check closed")["run"])
    assert 'if [ -z "$closed_at" ] || [ "$state" != "COMPLETED" ]; then' in lines
    assert 'echo "closed=true" >> "$GITHUB_OUTPUT"' in lines


def test_l2_check_closed_asks_gh_once():
    run = step_named(load(TASK), "ticket", "Check closed")["run"]
    assert run.count("gh issue view") == 1
    assert "--json closedAt,stateReason" in run


def test_l1_gh_token_is_only_on_the_steps_that_call_gh():
    doc = load(TASK)
    for job_name, job in doc["jobs"].items():
        assert "GH_TOKEN" not in job.get("env", {}), job_name
    gh_steps = {"Select tickets", "Check closed", "Fetch snapshot"}
    for _, step in steps_of(doc):
        assert ("GH_TOKEN" in step.get("env", {})) == (step.get("name") in gh_steps), step.get("name")


def test_l3_config_checkout_names_exactly_one_file():
    with_ = step_named(load(TASK), "ticket", "Checkout config")["with"]
    assert with_["sparse-checkout-cone-mode"] is False
    assert with_["sparse-checkout"] == "/${{ inputs.config }}"


def test_l7_config_path_must_be_repo_relative():
    lines = stripped_lines(step_named(load(TASK), "ticket", "Score and copy config")["run"])
    assert 'case "$CONFIG" in' in lines
    assert any(line.startswith("/*|..|../*|*/..|*/../*)") for line in lines)


def test_m2_actionlint_version_and_checksum_are_literal_in_ci():
    steps = [s for s in load(CI)["jobs"]["test"]["steps"] if s.get("name", "").startswith("Install actionlint")]
    assert len(steps) == 1
    assert steps[0]["env"] == ACTIONLINT_PIN
    verify = [line for line in stripped_lines(steps[0]["run"]) if "sha256sum -c" in line]
    assert verify == ['echo "${ACTIONLINT_SHA256}  ${archive}" | sha256sum -c -']


def test_m2_ci_lint_step_runs_actionlint_and_nothing_else():
    step = step_named(load(CI), "test", "Lint periodic-report workflows")
    assert step["run"] == "actionlint .github/workflows/code-quality-report.yml .github/workflows/task-quality-report.yml"
