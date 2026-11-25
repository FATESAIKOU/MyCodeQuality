"""PR-P3 contracts: mcq-report index (C-P8), artifact names (C-P9), and select (C-P11).

All data is synthetic (acme/widgets, #11 and friends). gh output is simulated with JSON built here.
Every test name carries its contract ID.
"""

import datetime
import hashlib
import json
import time

import pytest

from mcqreport.cli import main
from mcqreport.names import code_name, task_name
from mcqreport.selection import LIST_LIMIT, select_tickets

REPO = "acme/widgets"
NOW = "2030-01-09T00:00:00Z"
CLOSED = "2030-01-02T05:00:00Z"
REV = "3333333" + "d" * 33  # 40 lowercase hex characters


def run(capsys, *argv):
    rc = main(list(argv))
    out, err = capsys.readouterr()
    return rc, out, err


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def issue(number, closed_at=CLOSED, state="COMPLETED"):
    return {"number": number, "closedAt": closed_at, "stateReason": state}


def pages(*artifact_lists):
    """`gh api --paginate --slurp` output: one page object per element."""
    return [{"total_count": 0, "artifacts": [{"name": n, "expired": e} for n, e in arts]} for arts in artifact_lists]


def final_name(number, day="20300102", digest="abcdef12"):
    return f"mcq-task--acme.widgets--i{number}--{day}--final--{digest}"


def select_cli(capsys, tmp_path, event, *, issues=None, artifacts=None, extra=()):
    argv = ["select", "--event", event, "--repo", REPO, "--now", NOW, *extra]
    if issues is not None:
        argv += ["--gh-issues", write_json(tmp_path / "issues.json", issues)]
    if artifacts is not None:
        argv += ["--gh-artifacts", write_json(tmp_path / "artifacts.json", artifacts)]
    return run(capsys, *argv)


# --- C-P8 mcq-report index ---------------------------------------------------------


@pytest.fixture
def task_files(tmp_path):
    files = {
        "taskquality-snapshot.json": {"kind": "taskquality-snapshot", "schema_version": 1, "ticket": "acme/widgets#11"},
        "taskquality-report.json": {"kind": "taskquality-report", "schema_version": 1, "status": "complete"},
        "taskquality-config.json": {"kind": "taskquality-config", "schema_version": 1},
    }
    paths = []
    for name, obj in files.items():
        paths.append(write_json(tmp_path / name, obj))
    return tmp_path, paths


def index_args(paths, out, *, report="task"):
    args = ["index", "--report", report, "--repo", REPO, "--qmetrics-ref", "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "--python-version", "3.12", "--out", str(out)]
    for p in paths:
        args += ["--file", p]
    if report == "task":
        args += ["--ticket", "acme/widgets#11", "--search-repo", REPO]
    else:
        args += ["--rev", REV, "--target", "main"]
    return args


def test_c_p8_same_files_same_index_bytes(capsys, task_files):
    tmp_path, paths = task_files
    out1, out2 = tmp_path / "i1.json", tmp_path / "i2.json"
    assert run(capsys, *index_args(paths, out1))[0] == 0
    assert run(capsys, *index_args(list(reversed(paths)), out2))[0] == 0
    assert out1.read_bytes() == out2.read_bytes()


def test_c_p8_task_search_repos_sorted_and_code_null(capsys, tmp_path, task_files):
    _, paths = task_files
    out = tmp_path / "index.json"
    args = index_args(paths, out)
    at = args.index("--search-repo")
    del args[at : at + 2]
    args += ["--search-repo", "acme/zeta", "--search-repo", "acme/alpha"]
    assert run(capsys, *args)[0] == 0
    index = json.loads(out.read_text(encoding="utf-8"))
    assert index["search_repos"] == ["acme/alpha", "acme/zeta"]
    assert index["report"] == "task" and index["rev"] is None and index["target"] is None

    code_out = tmp_path / "code-index.json"
    code_paths = [paths[0]]
    assert run(capsys, *index_args(code_paths, code_out, report="code"))[0] == 0
    code_index = json.loads(code_out.read_text(encoding="utf-8"))
    assert code_index["search_repos"] is None and code_index["ticket"] is None
    assert code_index["rev"] == REV and code_index["target"] == "main"


def test_c_p8_files_sorted_by_name_with_sha256_and_kind_from_file(capsys, tmp_path, task_files):
    _, paths = task_files
    out = tmp_path / "index.json"
    assert run(capsys, *index_args(paths, out))[0] == 0
    index = json.loads(out.read_text(encoding="utf-8"))
    names = [f["name"] for f in index["files"]]
    assert names == ["taskquality-config.json", "taskquality-report.json", "taskquality-snapshot.json"]
    for entry in index["files"]:
        data = (tmp_path / entry["name"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        parsed = json.loads(data.decode("utf-8"))
        assert entry["kind"] == parsed["kind"]
        assert entry["schema_version"] == parsed["schema_version"]


def test_c_p8_not_json_or_no_kind_exit2(capsys, tmp_path, task_files):
    _, paths = task_files
    bad = tmp_path / "broken.json"
    bad.write_text("not json", encoding="utf-8")
    rc, _, err = run(capsys, *index_args([str(bad)], tmp_path / "x.json"))
    assert rc == 2 and "bad_json" in err

    nokind = write_json(tmp_path / "nokind.json", {"schema_version": 1})
    rc, _, err = run(capsys, *index_args([nokind], tmp_path / "y.json"))
    assert rc == 2 and "bad_file" in err


def test_c_p8_index_bytes_are_sorted_keys_json(capsys, tmp_path, task_files):
    _, paths = task_files
    out = tmp_path / "index.json"
    assert run(capsys, *index_args(paths, out))[0] == 0
    text = out.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def test_c_p8_same_file_listed_twice_exit2(capsys, tmp_path, task_files):
    _, paths = task_files
    rc, _, err = run(capsys, *index_args(paths + [paths[0]], tmp_path / "dup.json"))
    assert rc == 2 and "duplicate file name" in err


def test_c_p8_index_name_cannot_be_listed_exit2(capsys, tmp_path, task_files):
    _, paths = task_files
    clash = write_json(tmp_path / "index.json", {"kind": "x", "schema_version": 1})
    rc, _, err = run(capsys, *index_args([clash], tmp_path / "out.json"))
    assert rc == 2 and "bad_file" in err


def test_c_p8_index_has_no_time_or_run_fields(capsys, tmp_path, task_files):
    _, paths = task_files
    out = tmp_path / "index.json"
    assert run(capsys, *index_args(paths, out))[0] == 0
    index = json.loads(out.read_text(encoding="utf-8"))
    assert set(index) == {
        "kind", "schema_version", "report", "repo", "ticket", "rev", "target",
        "qmetrics_ref", "python_version", "search_repos", "files",
    }
    assert index["kind"] == "mcq-report-index" and index["schema_version"] == 1
    text = out.read_text(encoding="utf-8")
    for banned in ("run_id", "created_at", "event", "generated"):
        assert banned not in text


# --- C-P9 artifact names -----------------------------------------------------------


def test_c_p9_code_name_example(capsys):
    assert code_name("Acme/Widgets", "main", "2030-01-02T23:59:59Z", REV) == "mcq-code--acme.widgets--main--20300102--3333333"


def test_c_p9_code_name_via_cli(capsys):
    rc, out, _ = run(capsys, "name", "code", "--repo", "Acme/Widgets", "--target", "main", "--committed-at", "2030-01-02T23:59:59Z", "--rev", REV)
    assert rc == 0
    assert out == "mcq-code--acme.widgets--main--20300102--3333333\n"


def test_c_p9_task_final_after_settle(capsys, tmp_path):
    snapshot = b'{"kind": "taskquality-snapshot"}\n'
    name = task_name("acme/widgets#11", CLOSED, "2030-01-05T00:00:00Z", "complete", [], snapshot, 2)
    digest = hashlib.sha256(snapshot).hexdigest()[:8]
    assert name == f"mcq-task--acme.widgets--i11--20300102--final--{digest}"


def test_c_p9_task_final_exactly_at_settle_boundary(tmp_path):
    name = task_name("acme/widgets#11", CLOSED, "2030-01-04T05:00:00Z", "complete", [], b"{}", 2)
    assert "--final--" in name


def test_c_p9_task_prov_one_second_before_settle(tmp_path):
    name = task_name("acme/widgets#11", CLOSED, "2030-01-04T04:59:59Z", "complete", [], b"{}", 2)
    assert "--prov--" in name


def test_c_p9_task_prov_before_settle(tmp_path):
    snapshot = b"{}"
    name = task_name("acme/widgets#11", CLOSED, "2030-01-02T06:00:00Z", "complete", [], snapshot, 2)
    assert "--prov--" in name and "--final--" not in name


def test_c_p9_task_prov_when_in_progress_or_ci_incomplete(tmp_path):
    snapshot = b"{}"
    in_progress = task_name("acme/widgets#11", CLOSED, "2030-01-05T00:00:00Z", "in_progress", [], snapshot, 2)
    assert "--prov--" in in_progress
    ci = task_name("acme/widgets#11", CLOSED, "2030-01-05T00:00:00Z", "complete", ["ci_incomplete"], snapshot, 2)
    assert "--prov--" in ci


def test_c_p9_task_name_from_report_file_via_cli(capsys, tmp_path):
    report = write_json(tmp_path / "report.json", {"kind": "taskquality-report", "schema_version": 1, "status": "complete", "missing": [{"field": "ci_first_green", "reason": "ci_incomplete"}]})
    snap = tmp_path / "snap.json"
    snap.write_bytes(b"{}")
    rc, out, _ = run(capsys, "name", "task", "--ticket", "acme/widgets#11", "--closed-at", CLOSED, "--run-at", "2030-01-05T00:00:00Z", "--report", report, "--snapshot", str(snap))
    assert rc == 0
    assert "--prov--" in out


def test_c_p9_target_with_other_chars_exit2(capsys):
    rc, out, err = run(capsys, "name", "code", "--repo", REPO, "--target", "feature/x", "--committed-at", "2030-01-02T23:59:59Z", "--rev", REV)
    assert rc == 2 and out == "" and "bad_name_part" in err


def test_c_p9_names_only_safe_characters(capsys):
    name = code_name(REPO, "release-1.2_x", "2030-01-02T23:59:59Z", REV)
    assert all(c.isalnum() or c in "._-" for c in name)


# --- C-P11 select ------------------------------------------------------------------


def test_c_p11_not_planned_not_selected(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11, state="NOT_PLANNED"), issue(12)], artifacts=pages([]))
    result = json.loads(out)
    assert rc == 0 and result["tickets"] == [12]
    assert result["skipped_not_completed"] == [11]


def test_c_p11_before_window_not_selected(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11, closed_at="2030-01-01T23:59:59Z"), issue(12)], artifacts=pages([]), extra=["--backfill-days", "7"])
    result = json.loads(out)
    assert result["tickets"] == [12] and result["truncated"] == [] and 11 not in result["skipped_not_completed"]


def test_c_p11_closed_exactly_at_window_start_selected(capsys, tmp_path):
    # NOW 2030-01-09 minus 7 days is 2030-01-02T00:00:00Z
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11, closed_at="2030-01-02T00:00:00Z")], artifacts=pages([]), extra=["--backfill-days", "7"])
    assert json.loads(out)["tickets"] == [11]


def test_c_p11_existing_final_skipped(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11), issue(12)], artifacts=pages([(final_name(11), False)]))
    result = json.loads(out)
    assert result["tickets"] == [12]
    assert result["skipped_final"] == [11]


def test_c_p11_prov_artifact_still_selected(capsys, tmp_path):
    prov = "mcq-task--acme.widgets--i11--20300102--prov--abcdef12"
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11)], artifacts=pages([(prov, False)]))
    result = json.loads(out)
    assert result["tickets"] == [11] and result["skipped_final"] == []


def test_c_p11_expired_final_not_counted(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11)], artifacts=pages([(final_name(11), True)]))
    result = json.loads(out)
    assert result["tickets"] == [11] and result["skipped_final"] == []


def test_c_p11_final_of_other_ticket_prefix_not_matched(capsys, tmp_path):
    # i1 must not match i11; a different repo must not match either
    other_repo = "mcq-task--acme.other--i11--20300102--final--abcdef12"
    ticket_one = "mcq-task--acme.widgets--i1--20300102--final--abcdef12"
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11), issue(1)], artifacts=pages([(other_repo, False), (ticket_one, False)]))
    result = json.loads(out)
    assert result["tickets"] == [11] and result["skipped_final"] == [1]


def test_c_p11_sort_by_closed_at_then_number(capsys, tmp_path):
    issues = [issue(20, "2030-01-03T00:00:00Z"), issue(14, "2030-01-02T12:00:00Z"), issue(13, "2030-01-02T12:00:00Z"), issue(19, "2030-01-02T09:00:00Z")]
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=issues, artifacts=pages([]))
    assert json.loads(out)["tickets"] == [19, 13, 14, 20]


def test_c_p11_input_descending_order_output_by_closed_at(capsys, tmp_path):
    # gh lists by number descending; the older ticket has the larger number
    issues = [issue(30, "2030-01-02T01:00:00Z"), issue(20, "2030-01-02T02:00:00Z"), issue(10, "2030-01-02T00:30:00Z")]
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=issues, artifacts=pages([]))
    assert json.loads(out)["tickets"] == [10, 30, 20]


def test_c_p11_max_tickets_truncates_newest(capsys, tmp_path):
    issues = [issue(100 + i, f"2030-01-02T{i:02d}:00:00Z") for i in range(21)]
    rc, out, err = select_cli(capsys, tmp_path, "schedule", issues=issues, artifacts=pages([]), extra=["--max-tickets", "20"])
    result = json.loads(out)
    assert rc == 0
    assert result["tickets"] == [100 + i for i in range(20)]
    assert result["truncated"] == [120]
    assert "::warning::" in err and "120" in err


def test_c_p11_max_tickets_over_cap_exit2(capsys, tmp_path):
    rc, out, err = select_cli(capsys, tmp_path, "schedule", issues=[issue(11)], artifacts=pages([]), extra=["--max-tickets", "257"])
    assert rc == 2 and out == ""


def test_c_p11_manual_bad_token_exit2(capsys):
    rc, out, err = run(capsys, "select", "--event", "workflow_dispatch", "--repo", REPO, "--now", NOW, "--tickets", "11 x")
    assert rc == 2 and out == ""


def test_c_p11_manual_dedupes_and_sorts(capsys):
    rc, out, _ = run(capsys, "select", "--event", "workflow_dispatch", "--repo", REPO, "--now", NOW, "--tickets", "12 11 11")
    result = json.loads(out)
    assert rc == 0 and result["tickets"] == [11, 12]


def test_c_p11_manual_257_tickets_exit2(capsys):
    tickets = " ".join(str(n) for n in range(1, 258))
    rc, out, err = run(capsys, "select", "--event", "workflow_dispatch", "--repo", REPO, "--now", NOW, "--tickets", tickets)
    assert rc == 2 and out == ""


def test_c_p11_manual_not_truncated_by_max_tickets(capsys):
    tickets = " ".join(str(n) for n in range(1, 31))
    rc, out, _ = run(capsys, "select", "--event", "workflow_dispatch", "--repo", REPO, "--now", NOW, "--tickets", tickets, "--max-tickets", "5")
    result = json.loads(out)
    assert len(result["tickets"]) == 30 and result["truncated"] == []


def test_c_p11_full_page_of_issue_list_exit2(capsys, tmp_path):
    issues = [issue(n) for n in range(1, LIST_LIMIT + 1)]
    rc, out, err = select_cli(capsys, tmp_path, "schedule", issues=issues, artifacts=pages([]))
    assert rc == 2 and out == "" and "list_may_be_truncated" in err


def test_c_p11_artifacts_must_be_slurped_array(capsys, tmp_path):
    concatenated = tmp_path / "artifacts.json"
    concatenated.write_text('{"artifacts": []}\n{"artifacts": []}\n', encoding="utf-8")
    issues_path = write_json(tmp_path / "issues.json", [issue(11)])
    rc, out, err = run(capsys, "select", "--event", "schedule", "--repo", REPO, "--now", NOW, "--gh-issues", issues_path, "--gh-artifacts", str(concatenated))
    assert rc == 2 and out == ""


def test_c_p11_two_slurped_pages_merged(capsys, tmp_path):
    # the final artifact is on the second page, so it must still be seen
    arts = pages([(final_name(12), False)], [(final_name(13), False)])
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11), issue(12), issue(13)], artifacts=arts)
    result = json.loads(out)
    assert result["tickets"] == [11] and result["skipped_final"] == [12, 13]


def test_c_p11_issues_event_completed_and_not_planned(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "issues", issues=issue(11), artifacts=pages([]))
    assert rc == 0 and json.loads(out)["tickets"] == [11]

    rc, out, _ = select_cli(capsys, tmp_path, "issues", issues=issue(11, state="NOT_PLANNED"), artifacts=pages([]))
    result = json.loads(out)
    assert rc == 0 and result["tickets"] == [] and result["skipped_not_completed"] == [11]


def test_c_p11_issues_event_ignores_existing_final(capsys, tmp_path):
    rc, out, _ = select_cli(capsys, tmp_path, "issues", issues=issue(11), artifacts=pages([(final_name(11), False)]))
    result = json.loads(out)
    assert result["tickets"] == [11] and result["skipped_final"] == []


def test_c_p11_unknown_event_exit2(capsys, tmp_path):
    rc, out, err = run(capsys, "select", "--event", "pull_request", "--repo", REPO, "--now", NOW, "--gh-issues", "x", "--gh-artifacts", "x")
    assert rc == 2 and out == ""


def test_c_p11_no_clock_is_read(capsys, tmp_path, monkeypatch):
    class NoClock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("datetime.now must not be called")

        @classmethod
        def utcnow(cls):
            raise AssertionError("datetime.utcnow must not be called")

        @classmethod
        def today(cls):
            raise AssertionError("datetime.today must not be called")

    def no_time(*_a, **_k):
        raise AssertionError("time must not be read")

    monkeypatch.setattr(datetime, "datetime", NoClock)
    monkeypatch.setattr(time, "time", no_time)
    monkeypatch.setattr(time, "time_ns", no_time)
    rc, out, _ = select_cli(capsys, tmp_path, "schedule", issues=[issue(11)], artifacts=pages([]))
    assert rc == 0 and json.loads(out)["tickets"] == [11]


def test_c_p11_select_function_is_pure_of_its_inputs():
    result = select_tickets(
        "schedule",
        repo=REPO,
        now=NOW,
        gh_issues=[issue(11), issue(12)],
        gh_artifacts=pages([]),
    )
    assert result == {"tickets": [11, 12], "truncated": [], "skipped_final": [], "skipped_not_completed": []}
