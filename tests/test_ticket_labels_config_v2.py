"""PR-P2 contracts: ticket_labels in the snapshot, config v2 (started_label, ci_required).

C-P3 fetch collects label events; C-P4 old snapshots score the same; C-P5 started_label;
C-P6 ci_required; C-P7 compatibility rules for config v1/v2. All data is synthetic.
"""

import copy
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from taskquality.cli import main
from taskquality.conventions import DEFAULT_CONFIG
from taskquality.fetch import GRAPHQL_LABEL_QUERY, fetch_snapshot
from taskquality.formats import ToolError, calculate_config_digest, validate_config, validate_snapshot
from taskquality.score import score_ticket

HEAD = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
STATUS = "status:in-progress"


def run_tq(*args):
    return subprocess.run(
        [sys.executable, "-m", "taskquality.cli", *args],
        capture_output=True,
        text=True,
    )


def ci_run(conclusion="success", status="completed"):
    return {
        "run_id": 9002,
        "workflow": "ci",
        "event": "pull_request",
        "head_sha": HEAD,
        "run_attempt": 1,
        "created_at": "2030-01-02T04:41:00Z",
        "status": status,
        "conclusion": conclusion,
    }


def make_pr(**over):
    pr = {
        "id": "acme/widgets#21",
        "title": "Add widget cache",
        "body": "Closes #11",
        "state": "closed",
        "head_sha": HEAD,
        "created_at": "2030-01-02T03:00:00Z",
        "merged_at": "2030-01-02T05:00:00Z",
        "closed_at": "2030-01-02T05:00:00Z",
        "comments": [
            {
                "id": 501,
                "created_at": "2030-01-02T04:00:00Z",
                "first_line": "審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 1111111）",
            }
        ],
        "reviews": [],
        "ci_runs": [ci_run()],
    }
    pr.update(over)
    return pr


def make_snapshot(prs=None, ticket_labels=None):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [make_pr()] if prs is None else prs,
    }
    if ticket_labels is not None:
        snap["ticket_labels"] = ticket_labels
    return snap


LABELS = [
    {"at": "2030-01-02T02:00:00Z", "action": "labeled", "label": STATUS},
    {"at": "2030-01-02T02:30:00Z", "action": "unlabeled", "label": STATUS},
    {"at": "2030-01-02T02:45:00Z", "action": "labeled", "label": STATUS},
]


def make_input(**over):
    data = {"kind": "taskquality-input", "schema_version": 1, "ticket": "acme/widgets#11"}
    data.update(over)
    return data


def v2_config(**extra):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["schema_version"] = 2
    cfg.update(extra)
    return cfg


def timeline_page(nodes):
    return {
        "data": {
            "repository": {
                "issue": {
                    "timelineItems": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def label_page(nodes, has_next=False, cursor=None):
    return {
        "data": {
            "repository": {
                "issue": {
                    "timelineItems": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def labeled(at, label=STATUS):
    return {"__typename": "LabeledEvent", "createdAt": at, "label": {"name": label}}


def unlabeled(at, label=STATUS):
    return {"__typename": "UnlabeledEvent", "createdAt": at, "label": {"name": label}}


def fetch_runner(label_pages):
    """Injected runner: timeline query has no PRs; label query answers from label_pages in order."""
    label_calls = []

    def runner(argv):
        cmd = " ".join(argv)
        if "LABELED_EVENT" in cmd:
            label_calls.append(argv)
            page = label_pages[len(label_calls) - 1]
            return json.dumps(page), "", 0
        return json.dumps(timeline_page([])), "", 0

    return runner, label_calls


# C-P3: fetch collects LabeledEvent/UnlabeledEvent into ticket_labels.
def test_C_P3_fetch_collects_label_events_sorted(tmp_path):
    nodes = [labeled("2030-01-02T02:45:00Z"), unlabeled("2030-01-02T02:30:00Z"), labeled("2030-01-02T02:00:00Z")]
    runner, _ = fetch_runner([label_page(nodes)])
    out = tmp_path / "snap.json"

    snap = fetch_snapshot("acme/widgets#11", out, runner=runner)

    assert snap["ticket_labels"] == [
        {"at": "2030-01-02T02:00:00Z", "action": "labeled", "label": STATUS},
        {"at": "2030-01-02T02:30:00Z", "action": "unlabeled", "label": STATUS},
        {"at": "2030-01-02T02:45:00Z", "action": "labeled", "label": STATUS},
    ]
    validate_snapshot(snap)


def test_C_P3_fetch_label_order_does_not_change_bytes(tmp_path):
    forward = [labeled("2030-01-02T02:00:00Z"), unlabeled("2030-01-02T02:30:00Z"), labeled("2030-01-02T02:45:00Z")]
    runner1, _ = fetch_runner([label_page(forward)])
    runner2, _ = fetch_runner([label_page(list(reversed(forward)))])
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"

    fetch_snapshot("acme/widgets#11", out1, runner=runner1)
    fetch_snapshot("acme/widgets#11", out2, runner=runner2)

    assert out1.read_bytes() == out2.read_bytes()


def test_C_P3_fetch_no_label_events_gives_empty_list(tmp_path):
    runner, _ = fetch_runner([label_page([])])
    snap = fetch_snapshot("acme/widgets#11", tmp_path / "snap.json", runner=runner)
    assert snap["ticket_labels"] == []


def test_C_P3_label_events_carry_no_actor(tmp_path):
    # The query must not ask for who did it, and the output must not contain an operator field.
    assert "actor" not in GRAPHQL_LABEL_QUERY
    assert "login" not in GRAPHQL_LABEL_QUERY
    runner, _ = fetch_runner([label_page([labeled("2030-01-02T02:00:00Z")])])
    out = tmp_path / "snap.json"
    fetch_snapshot("acme/widgets#11", out, runner=runner)
    text = out.read_text(encoding="utf-8")
    assert "actor" not in text
    assert "login" not in text
    for ev in json.loads(text)["ticket_labels"]:
        assert set(ev) == {"at", "action", "label"}


def test_C_P3_label_query_pages_like_timeline(tmp_path):
    page1 = label_page([labeled("2030-01-02T02:00:00Z")], has_next=True, cursor="c2")
    page2 = label_page([unlabeled("2030-01-02T02:30:00Z")])
    runner, calls = fetch_runner([page1, page2])

    snap = fetch_snapshot("acme/widgets#11", tmp_path / "snap.json", runner=runner)

    assert len(calls) == 2
    assert any("cursor=c2" in part for part in calls[1])
    assert [ev["action"] for ev in snap["ticket_labels"]] == ["labeled", "unlabeled"]


def test_C_P3_label_page_two_failure_is_incomplete_pagination(tmp_path):
    page1 = label_page([labeled("2030-01-02T02:00:00Z")], has_next=True, cursor="c2")

    def runner(argv):
        cmd = " ".join(argv)
        if "LABELED_EVENT" in cmd:
            if "cursor=c2" in cmd:
                return "", "network error", 1
            return json.dumps(page1), "", 0
        return json.dumps(timeline_page([])), "", 0

    out = tmp_path / "never.json"
    with pytest.raises(ToolError) as exc:
        fetch_snapshot("acme/widgets#11", out, runner=runner)
    assert exc.value.code == "incomplete_pagination"
    assert not out.exists()


def test_C_P3_label_query_rate_limit_uses_shared_retry(tmp_path):
    sleeps = []
    state = {"n": 0}

    def runner(argv):
        if "LABELED_EVENT" in " ".join(argv):
            state["n"] += 1
            if state["n"] == 1:
                return json.dumps({"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}), "", 0
            return json.dumps(label_page([labeled("2030-01-02T02:00:00Z")])), "", 0
        return json.dumps(timeline_page([])), "", 0

    snap = fetch_snapshot("acme/widgets#11", tmp_path / "snap.json", runner=runner, sleeper=sleeps.append)
    assert sleeps == [60]
    assert len(snap["ticket_labels"]) == 1


def test_C_P3_cli_fetch_uses_only_the_fake_gh_on_path(tmp_path, monkeypatch, capsys):
    # A recording fake gh shadows the real one on PATH; the real gh is never executed.
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log = tmp_path / "gh.log"
    timeline = tmp_path / "timeline.json"
    labels = tmp_path / "labels.json"
    timeline.write_text(json.dumps(timeline_page([])))
    labels.write_text(json.dumps(label_page([labeled("2030-01-02T02:00:00Z")])))
    fake = fakebin / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'%s %s\\n\' "$1" "$2" >> "$FAKE_GH_LOG"\n'
        'case "$*" in\n'
        '  *LABELED_EVENT*) cat "$FAKE_GH_LABELS" ;;\n'
        '  *) cat "$FAKE_GH_TIMELINE" ;;\n'
        "esac\n"
    )
    os.chmod(fake, 0o755)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_LABELS", str(labels))
    monkeypatch.setenv("FAKE_GH_TIMELINE", str(timeline))
    out = tmp_path / "snap.json"

    rc = main(["fetch", "--ticket", "acme/widgets#11", "--out", str(out)])

    assert rc == 0
    assert log.read_text().splitlines() == ["api graphql", "api graphql"]
    assert json.loads(out.read_text())["ticket_labels"][0]["label"] == STATUS


# C-P3 (snapshot validation): ticket_labels is optional and shape-checked.
def test_C_P3_snapshot_ticket_labels_is_optional_and_validated():
    validate_snapshot(make_snapshot())
    validate_snapshot(make_snapshot(ticket_labels=LABELS))

    bad_action = make_snapshot(ticket_labels=[{"at": "2030-01-02T02:00:00Z", "action": "assigned", "label": STATUS}])
    with pytest.raises(ToolError) as exc:
        validate_snapshot(bad_action)
    assert exc.value.code == "snapshot_bad_shape"

    bad_label = make_snapshot(ticket_labels=[{"at": "2030-01-02T02:00:00Z", "action": "labeled", "label": ""}])
    with pytest.raises(ToolError) as exc:
        validate_snapshot(bad_label)
    assert exc.value.code == "snapshot_bad_shape"

    not_list = make_snapshot()
    not_list["ticket_labels"] = None
    with pytest.raises(ToolError) as exc:
        validate_snapshot(not_list)
    assert exc.value.code == "snapshot_bad_shape"

    bad_at = make_snapshot(ticket_labels=[{"at": "yesterday", "action": "labeled", "label": STATUS}])
    with pytest.raises(ToolError) as exc:
        validate_snapshot(bad_at)
    assert exc.value.code == "bad_time"


# C-P4: old snapshots (no ticket_labels) and new ones score the same under a v1 config.
def test_C_P4_ticket_labels_do_not_change_v1_score_bytes(tmp_path):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps(make_snapshot()))
    new.write_text(json.dumps(make_snapshot(ticket_labels=LABELS)))

    r_old = run_tq("score", "--snapshot", str(old), "--json")
    r_new = run_tq("score", "--snapshot", str(new), "--json")

    assert r_old.returncode == 0, r_old.stderr
    assert r_new.returncode == 0, r_new.stderr
    assert r_old.stdout == r_new.stdout
    assert json.loads(r_new.stdout)["metrics"]["cycle_basis"] == "first_pr_created"


# C-P5: started_label (v2 config) chooses the start time.
def test_C_P5_input_started_at_beats_label():
    cfg = v2_config(started_label=STATUS)
    report = score_ticket(make_snapshot(ticket_labels=LABELS), make_input(started_at="2030-01-02T01:00:00Z"), cfg)
    assert report["metrics"]["cycle_basis"] == "input_started_at"
    assert report["metrics"]["cycle_seconds"] == 14400


def test_C_P5_earliest_labeled_event_is_used():
    cfg = v2_config(started_label=STATUS)
    report = score_ticket(make_snapshot(ticket_labels=LABELS), None, cfg)
    assert report["metrics"]["cycle_basis"] == "ticket_label"
    # 05:00 merged minus 02:00 first labeled (not the 02:45 re-label, not the 02:30 unlabel)
    assert report["metrics"]["cycle_seconds"] == 10800


def test_C_P5_missing_label_falls_back_to_first_pr_created():
    cfg = v2_config(started_label="status:other")
    report = score_ticket(make_snapshot(ticket_labels=LABELS), None, cfg)
    assert report["metrics"]["cycle_basis"] == "first_pr_created"
    assert report["metrics"]["cycle_seconds"] == 7200


def test_C_P5_snapshot_without_field_falls_back_to_first_pr_created():
    cfg = v2_config(started_label=STATUS)
    report = score_ticket(make_snapshot(), None, cfg)
    assert report["metrics"]["cycle_basis"] == "first_pr_created"
    assert report["metrics"]["cycle_seconds"] == 7200


def test_C_P5_label_after_merge_is_bad_interval():
    late = [{"at": "2030-01-03T00:00:00Z", "action": "labeled", "label": STATUS}]
    cfg = v2_config(started_label=STATUS)
    report = score_ticket(make_snapshot(ticket_labels=late), None, cfg)
    assert report["metrics"]["cycle_basis"] == "ticket_label"
    assert report["metrics"]["cycle_seconds"] is None
    assert {"field": "metrics.cycle_seconds", "reason": "bad_interval"} in report["missing"]


def test_C_P5_started_label_is_valid_v2_config():
    validate_config(v2_config(started_label=STATUS))


# C-P6: ci_required false (v2 config).
def _clean_with(cfg, prs):
    return score_ticket(make_snapshot(prs=prs), None, cfg)


def test_C_P6_no_ci_run_is_clean_when_ci_not_required():
    cfg = v2_config(ci_required=False)
    report = _clean_with(cfg, [make_pr(ci_runs=[])])
    assert report["clean"] is True
    assert report["metrics"]["prs_without_ci"] == 1
    assert report["metrics"]["ci_first_green"] is None
    assert {"field": "metrics.ci_first_green", "reason": "no_ci_runs"} in report["missing"]


def test_C_P6_no_ci_run_is_not_clean_under_default_ci_required():
    report = _clean_with(copy.deepcopy(DEFAULT_CONFIG), [make_pr(ci_runs=[])])
    assert report["clean"] is False
    assert report["metrics"]["prs_without_ci"] == 1


def test_C_P6_ci_incomplete_stays_unknown_when_ci_not_required():
    cfg = v2_config(ci_required=False)
    report = _clean_with(cfg, [make_pr(ci_runs=[ci_run(conclusion=None, status="in_progress")])])
    assert report["clean"] is None
    assert {"field": "clean", "reason": "ci_incomplete"} in report["missing"]


def test_C_P6_ci_failure_is_still_not_clean_when_ci_not_required():
    cfg = v2_config(ci_required=False)
    report = _clean_with(cfg, [make_pr(ci_runs=[ci_run(conclusion="failure")])])
    assert report["clean"] is False


def test_C_P6_ci_required_true_matches_absent_key():
    cfg = v2_config(ci_required=True)
    prs = [make_pr(ci_runs=[])]
    assert _clean_with(cfg, prs)["clean"] is False
    assert _clean_with(copy.deepcopy(DEFAULT_CONFIG), prs)["clean"] is False


# C-P7: compatibility and config version rules.
def test_C_P7_v1_config_with_ci_required_is_bad_shape(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["ci_required"] = False
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(make_snapshot()))

    r = run_tq("score", "--snapshot", str(snap), "--config", str(p))

    assert r.returncode == 2
    assert r.stdout == ""
    assert "taskquality: error config_bad_shape:" in r.stderr


def test_C_P7_v1_config_with_started_label_is_bad_shape():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["started_label"] = STATUS
    with pytest.raises(ToolError) as exc:
        validate_config(cfg)
    assert exc.value.code == "config_bad_shape"


def test_C_P7_v2_config_missing_v1_required_key_is_bad_shape():
    cfg = v2_config()
    del cfg["ci_workflows"]
    with pytest.raises(ToolError) as exc:
        validate_config(cfg)
    assert exc.value.code == "config_bad_shape"


def test_C_P7_v2_config_digest_differs_from_v1():
    v1 = copy.deepcopy(DEFAULT_CONFIG)
    v2 = v2_config()
    assert calculate_config_digest(v1) != calculate_config_digest(v2)


def test_C_P7_v2_rejects_bad_new_key_types():
    for bad in ({"ci_required": "no"}, {"ci_required": 0}, {"started_label": ""}, {"started_label": 5}):
        with pytest.raises(ToolError) as exc:
            validate_config(v2_config(**bad))
        assert exc.value.code == "config_bad_shape", bad


def test_C_P7_unknown_schema_version_is_bad_shape():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["schema_version"] = 3
    with pytest.raises(ToolError) as exc:
        validate_config(cfg)
    assert exc.value.code == "config_bad_shape"


def test_C_P7_v2_config_without_new_keys_scores_like_v1_except_digest():
    snap = make_snapshot()
    r1 = score_ticket(snap, None, copy.deepcopy(DEFAULT_CONFIG))
    r2 = score_ticket(snap, None, v2_config())
    assert r1["metrics"] == r2["metrics"]
    assert r1["clean"] == r2["clean"]
    assert r1["config_digest"] != r2["config_digest"]


def test_C_P7_unknown_key_still_ignored_in_v1(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["x_unknown"] = 1
    validate_config(cfg)
    assert calculate_config_digest(cfg) == calculate_config_digest(copy.deepcopy(DEFAULT_CONFIG))


def test_C_P7_v2_new_keys_are_part_of_the_digest():
    # Recognized keys: a v2 config that sets a new key must not share a digest with one that does not.
    base = v2_config()
    assert calculate_config_digest(v2_config(ci_required=False)) != calculate_config_digest(base)
    assert calculate_config_digest(v2_config(started_label=STATUS)) != calculate_config_digest(base)
    assert calculate_config_digest(v2_config(ci_required=True)) != calculate_config_digest(base)


def test_C_P3_label_query_requests_both_event_types():
    # Without UnlabeledEvent the 'unlabeled' side of started_label history silently disappears.
    assert "itemTypes: [LABELED_EVENT, UNLABELED_EVENT]" in GRAPHQL_LABEL_QUERY
    assert "... on UnlabeledEvent" in GRAPHQL_LABEL_QUERY


# C-P3 (ordering): events that share one second must not depend on the order gh returned them.
def test_C_P3_same_second_events_order_does_not_change_bytes(tmp_path):
    same = [
        labeled("2030-01-02T02:00:00Z", STATUS),
        labeled("2030-01-02T02:00:00Z", "status:other"),
        unlabeled("2030-01-02T02:00:00Z", STATUS),
    ]
    outputs = set()
    for i, order in enumerate(itertools.permutations(same)):
        runner, _ = fetch_runner([label_page(list(order))])
        out = tmp_path / f"{i}.json"
        fetch_snapshot("acme/widgets#11", out, runner=runner)
        outputs.add(out.read_bytes())
    assert len(outputs) == 1


# C-P5: only labeled events start the cycle; an earlier unlabeled event does not.
def test_C_P5_unlabeled_before_first_labeled_does_not_start_cycle():
    early_unlabel = [
        {"at": "2030-01-02T01:00:00Z", "action": "unlabeled", "label": STATUS},
        {"at": "2030-01-02T02:00:00Z", "action": "labeled", "label": STATUS},
    ]
    cfg = v2_config(started_label=STATUS)
    report = score_ticket(make_snapshot(ticket_labels=early_unlabel), None, cfg)
    assert report["metrics"]["cycle_basis"] == "ticket_label"
    # 05:00 merged minus 02:00 first labeled (not 01:00 unlabeled)
    assert report["metrics"]["cycle_seconds"] == 10800


# C-P3 (fetch robustness): non-object JSON and a vanished issue are ToolErrors, not AttributeError.
@pytest.mark.parametrize("body", ["[]", "null"])
def test_C_P3_label_query_non_object_json_is_gh_failed(tmp_path, body):
    def runner(argv):
        if "LABELED_EVENT" in " ".join(argv):
            return body, "", 0
        return json.dumps(timeline_page([])), "", 0

    out = tmp_path / "never.json"
    with pytest.raises(ToolError) as exc:
        fetch_snapshot("acme/widgets#11", out, runner=runner)
    assert exc.value.code == "gh_failed"
    assert not out.exists()


@pytest.mark.parametrize("body", ["[]", "null"])
def test_C_P3_label_page_two_non_object_json_is_incomplete_pagination(tmp_path, body):
    page1 = label_page([labeled("2030-01-02T02:00:00Z")], has_next=True, cursor="c2")

    def runner(argv):
        cmd = " ".join(argv)
        if "LABELED_EVENT" in cmd:
            return (body, "", 0) if "cursor=c2" in cmd else (json.dumps(page1), "", 0)
        return json.dumps(timeline_page([])), "", 0

    out = tmp_path / "never.json"
    with pytest.raises(ToolError) as exc:
        fetch_snapshot("acme/widgets#11", out, runner=runner)
    assert exc.value.code == "incomplete_pagination"
    assert not out.exists()


def test_C_P3_label_page_two_issue_gone_is_incomplete_pagination(tmp_path):
    page1 = label_page([labeled("2030-01-02T02:00:00Z")], has_next=True, cursor="c2")
    gone = {"data": {"repository": {"issue": None}}}

    def runner(argv):
        cmd = " ".join(argv)
        if "LABELED_EVENT" in cmd:
            return json.dumps(gone if "cursor=c2" in cmd else page1), "", 0
        return json.dumps(timeline_page([])), "", 0

    out = tmp_path / "never.json"
    with pytest.raises(ToolError) as exc:
        fetch_snapshot("acme/widgets#11", out, runner=runner)
    assert exc.value.code == "incomplete_pagination"
    assert not out.exists()


def test_C_P3_label_page_one_issue_missing_is_not_found(tmp_path):
    runner, _ = fetch_runner([{"data": {"repository": {"issue": None}}}])
    with pytest.raises(ToolError) as exc:
        fetch_snapshot("acme/widgets#11", tmp_path / "never.json", runner=runner)
    assert exc.value.code == "not_found"


def test_C_P3_cli_non_object_label_json_is_one_stderr_line_exit_2(tmp_path, monkeypatch, capsys):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    timeline = tmp_path / "timeline.json"
    labels = tmp_path / "labels.json"
    timeline.write_text(json.dumps(timeline_page([])))
    labels.write_text("[]")
    fake = fakebin / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *LABELED_EVENT*) cat "$FAKE_GH_LABELS" ;;\n'
        '  *) cat "$FAKE_GH_TIMELINE" ;;\n'
        "esac\n"
    )
    os.chmod(fake, 0o755)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LABELS", str(labels))
    monkeypatch.setenv("FAKE_GH_TIMELINE", str(timeline))

    rc = main(["fetch", "--ticket", "acme/widgets#11", "--out", str(tmp_path / "snap.json")])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == "taskquality: error gh_failed: GraphQL label query returned a non-object JSON value\n"
