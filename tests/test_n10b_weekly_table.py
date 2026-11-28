"""N10b (#62): mcq-report table (mcq-weekly-table) and taskquality first_review_head_stale.

All data is synthetic (acme/widgets). Golden files: tests/data/n10b_weekly_table.{json,md}.
Test names carry the design section they check (DESIGN-N10 §0, §1, §1a).
"""

import datetime
import json
from pathlib import Path

import pytest

from mcqreport.cli import main
from mcqreport.table import build_table, render_md
from taskquality.score import score_ticket
from taskquality.conventions import DEFAULT_CONFIG

DATA_DIR = Path(__file__).resolve().parent / "data"
WINDOW = {"from": "2030-01-01T00:00:00Z", "to": "2030-01-08T00:00:00Z"}
BASE = datetime.datetime(2030, 1, 2, 5, 0, 0, tzinfo=datetime.timezone.utc)
WEEK = 7 * 86400


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pr(num, *, state="merged", merged_at=None, verdicts=1, first_pass=True, fix=0,
        ci_runs=1, ci_green=True, head_stale=False, unparsed=0, post=0):
    """One PR as taskquality-report prs[] carries it (synthetic)."""
    pr = {
        "pr": f"acme/widgets#{num}",
        "state": state,
        "merged_at": _iso(merged_at) if merged_at else None,
        "verdicts": verdicts,
        "first_review_pass": first_pass if verdicts else None,
        "fix_rounds": fix,
        "ci_runs": ci_runs,
        "ci_first_green": ci_green if ci_runs else None,
        "first_review_head_stale": head_stale if state == "merged" and verdicts else None,
        "unparsed_verdict_lines": unparsed,
        "post_merge_verdicts": post,
    }
    return pr


def _report(ticket, prs, *, usage="absent", cycle=None, old=False):
    """A taskquality-report. Metrics are derived from prs[] the way score_ticket aggregates them."""
    merged = [p for p in prs if p["state"] == "merged"]
    cand = [p for p in merged if p["verdicts"]]
    metrics = {
        "prs_merged": len(merged),
        "prs_open": sum(1 for p in prs if p["state"] == "open"),
        "unreviewed_merged_prs": sum(1 for p in merged if p["verdicts"] == 0),
        "prs_without_ci": sum(1 for p in merged if p["ci_runs"] == 0),
        "unparsed_verdict_lines": sum(p["unparsed_verdict_lines"] for p in merged),
        "post_merge_verdicts": sum(p["post_merge_verdicts"] for p in merged),
        "fix_rounds": sum(p["fix_rounds"] for p in cand) if cand else None,
        "review_first_pass": {"num": sum(1 for p in cand if p["first_review_pass"]), "den": len(cand)} if cand else None,
        "ci_first_green": None,
        "cycle_seconds": cycle,
    }
    with_ci = [p for p in merged if p["ci_runs"]]
    if with_ci:
        metrics["ci_first_green"] = {"num": sum(1 for p in with_ci if p["ci_first_green"]), "den": len(with_ci)}
    if not old:
        metrics["first_review_head_stale_prs"] = sum(1 for p in merged if p["first_review_head_stale"])
    if old:
        # a report from before N10b: no Q-8 key, and PRs without ci_runs
        for p in prs:
            p.pop("ci_runs", None)
            p.pop("first_review_head_stale", None)
    report = {
        "kind": "taskquality-report",
        "schema_version": 1,
        "tool_version": "0.5.0",
        "config_digest": "sha256:" + "0" * 64,
        "ticket": ticket,
        "status": "complete" if merged and not any(p["state"] == "open" for p in prs) else "in_progress",
        "metrics": metrics,
        "prs": prs,
        "missing": [],
    }
    if usage != "absent":
        report["usage"] = usage
    return report


USAGE_TWO = {
    "by_model": [],
    "by_role_model": [
        {"model": "model-x", "provider": "vendor", "role": "impl",
         "input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 0, "cache_write_tokens": 1,
         "cost_micro_usd": 5, "weighted_micro_units": 40, "weighted_null_rows": 0},
        {"model": "model-y", "provider": "other", "role": "review",
         "input_tokens": 200, "output_tokens": 20, "cache_read_tokens": 3, "cache_write_tokens": 4,
         "cost_micro_usd": 9, "weighted_micro_units": None, "weighted_null_rows": 1},
    ],
    "totals": {},
}


def _twenty_tickets():
    """Twenty synthetic tickets that cover the edge cases the table must handle."""
    reports = []
    for i in range(1, 21):
        ticket = f"acme/widgets#{100 + i}"
        prs = []
        n_prs = 2 if i % 3 == 0 else 1
        for k in range(n_prs):
            num = 200 + i * 10 + k
            merged_at = BASE + datetime.timedelta(days=i, seconds=k * 86400 * (3 if i % 2 else 9))
            if i == 20 and k == 0:
                prs.append(_pr(num, state="open"))
                continue
            verdicts = (i + k) % 4
            if i == 7 and k == 0:
                verdicts = None  # unknown verdicts -> row null
            prs.append(_pr(
                num,
                merged_at=merged_at,
                verdicts=verdicts,
                first_pass=(i % 2 == 0),
                fix=max((verdicts or 0) - 1, 0),
                ci_runs=0 if i % 5 == 0 else 2,
                ci_green=(i % 4 != 0),
                head_stale=(i % 3 == 0),
                unparsed=1 if i == 13 and k == 0 else 0,
            ))
        if i == 4:
            usage = None  # usage null: row usage null, cells show —
        elif i == 8:
            # usage from before weighted units existed
            usage = {"by_role_model": [{k: v for k, v in e.items() if not k.startswith("weighted")}
                                       for e in USAGE_TWO["by_role_model"]]}
        elif i % 4:
            usage = USAGE_TWO
        else:
            usage = {"by_role_model": []}
        cycle = None if i == 20 else i * 3600 * 5
        reports.append(_report(ticket, prs, usage=usage, cycle=cycle, old=(i == 17)))
    return reports


def _population(reports):
    tickets = []
    for n, r in enumerate(reports, start=1):
        closed = None if n % 5 == 1 else f"2030-01-0{1 + n % 7}T12:00:00Z"
        tickets.append({"ticket": r["ticket"], "closed_at": closed, "level": "L1"})
    return {"kind": "mcq-weekly-population", "schema_version": 1, "tickets": tickets}


def _write_dir(path, reports):
    path.mkdir(parents=True, exist_ok=True)
    for r in reports:
        name = r["ticket"].replace("/", "_").replace("#", "-") + ".json"
        (path / name).write_text(json.dumps(r), encoding="utf-8")
    return path


def _cli(capsys, *argv):
    rc = main(list(argv))
    out, err = capsys.readouterr()
    return rc, out, err


def _table_args(reports_dir, out, md=None, population=None):
    args = ["table", "--reports", str(reports_dir), "--from", WINDOW["from"], "--to", WINDOW["to"], "--out", str(out)]
    if md is not None:
        args += ["--md", str(md)]
    if population is not None:
        args += ["--population", str(population)]
    return args


# --- golden: 20 synthetic tickets (§1, §1a) -----------------------------------------

def test_golden_json_and_md_match_bytes(tmp_path, capsys):
    # §1 golden: 20 tickets; JSON and Markdown are compared byte for byte (regenerate with the design above)
    reports_dir = _write_dir(tmp_path / "reports", _twenty_tickets())
    pop = tmp_path / "population.json"
    pop.write_text(json.dumps(_population(_twenty_tickets())), encoding="utf-8")
    out, md = tmp_path / "table.json", tmp_path / "table.md"
    rc, _, err = _cli(capsys, *_table_args(reports_dir, out, md, pop))
    assert rc == 0, err
    assert out.read_bytes() == (DATA_DIR / "n10b_weekly_table.json").read_bytes()
    assert md.read_bytes() == (DATA_DIR / "n10b_weekly_table.md").read_bytes()


def test_output_is_deterministic_and_order_independent(tmp_path, capsys):
    # §1 決定性: same bytes for two runs and for a reversed directory listing order
    reports = _twenty_tickets()
    a = _write_dir(tmp_path / "a", reports)
    b = _write_dir(tmp_path / "b", list(reversed(reports)))
    outs = []
    for d, name in [(a, "a1.json"), (a, "a2.json"), (b, "b.json")]:
        p = tmp_path / name
        rc, _, err = _cli(capsys, *_table_args(d, p))
        assert rc == 0, err
        outs.append(p.read_bytes())
    assert outs[0] == outs[1] == outs[2]


# --- row and summary rules (§1) ------------------------------------------------------

def test_review_rounds_null_when_a_merged_pr_has_null_verdicts():
    # §1 每列: PR verdicts 為 null → 該列 null
    prs = [_pr(1, merged_at=BASE, verdicts=None), _pr(2, merged_at=BASE, verdicts=2)]
    rows = build_table([_report("acme/widgets#1", prs)], WINDOW)["rows"]
    assert rows[0]["review_rounds"] is None


def test_missing_report_keys_stay_null_never_zero():
    # §1 缺鍵 → 該欄 null，不補 0 (old report without the Q-8 key)
    rep = _report("acme/widgets#2", [_pr(1, merged_at=BASE)], old=True)
    row = build_table([rep], WINDOW)["rows"][0]
    assert row["first_review_head_stale_prs"] is None
    assert row["prs_merged"] == 1


def test_no_usage_gives_null_usage_and_dash_cells():
    # §1 usage 為 null → null；render 顯示 —
    rep = _report("acme/widgets#3", [_pr(1, merged_at=BASE)], usage=None)
    table = build_table([rep], WINDOW)
    assert table["rows"][0]["usage"] is None
    assert table["summary"]["usage_by_role_model"] is None
    md = render_md(table)
    data_line = [line for line in md.splitlines() if line.startswith("| acme/widgets#3")][0]
    assert data_line.split("|")[2].strip() == "—"


def test_no_merged_pr_gives_null_review_rounds_and_fix_prs():
    # §1 沒有已合併 PR → fix_prs_within_7d 與 review_rounds 為 null
    rep = _report("acme/widgets#4", [_pr(1, state="open")])
    row = build_table([rep], WINDOW)["rows"][0]
    assert row["fix_prs_within_7d"] is None
    assert row["review_rounds"] is None


def test_q9_window_includes_exactly_seven_days_and_excludes_seven_days_plus_one_second():
    # §1 Q-9 邊界: 剛好 7 天（含）算；7 天＋1 秒不算；與最早合併同時的不算（「之後」）
    prs = [
        _pr(1, merged_at=BASE),
        _pr(2, merged_at=BASE),  # same time as earliest: not after it
        _pr(3, merged_at=BASE + datetime.timedelta(seconds=WEEK)),  # exactly 7 days: counted
        _pr(4, merged_at=BASE + datetime.timedelta(seconds=WEEK + 1)),  # 7 days + 1 second: not counted
    ]
    row = build_table([_report("acme/widgets#5", prs)], WINDOW)["rows"][0]
    assert row["fix_prs_within_7d"] == 1


def test_sample_sufficient_is_false_at_19_and_true_at_20():
    # §1 sample_sufficient: den 19 → false, 20 → true (and median/p90 null below 20)
    def build(n):
        reps = [_report(f"acme/widgets#{100 + i}", [_pr(1000 + i, merged_at=BASE, verdicts=1, first_pass=True)])
                for i in range(n)]
        return build_table(reps, WINDOW)["summary"]

    s19, s20 = build(19), build(20)
    assert s19["review_first_pass"]["den"] == 19 and s19["review_first_pass"]["sample_sufficient"] is False
    assert s20["review_first_pass"]["den"] == 20 and s20["review_first_pass"]["sample_sufficient"] is True
    assert s19["review_rounds_dist"]["median"] is None and s19["review_rounds_dist"]["p90"] is None
    assert s20["review_rounds_dist"]["median"] == 1 and s20["review_rounds_dist"]["p90"] == 1


def test_nearest_rank_percentiles_are_integers():
    # §1 分布欄：最近秩法，取第 ceil(p×n) 個
    reps = []
    for i in range(20):
        reps.append(_report(f"acme/widgets#{100 + i}", [_pr(1000 + i, merged_at=BASE, verdicts=i + 1)]))
    dist = build_table(reps, WINDOW)["summary"]["review_rounds_dist"]
    # values 1..20: median = 10th value, p90 = 18th value
    assert dist == {"n": 20, "median": 10, "p90": 18, "sample_sufficient": True}


def test_usage_by_role_model_sums_and_counts_weighted_nulls():
    # §1 usage_by_role_model: token keys sum; weighted sum of non-null plus weighted_null_rows
    a = _report("acme/widgets#7", [_pr(1, merged_at=BASE)], usage=USAGE_TWO)
    b = _report("acme/widgets#8", [_pr(2, merged_at=BASE)], usage=USAGE_TWO)
    total = build_table([a, b], WINDOW)["summary"]["usage_by_role_model"]
    entry = [e for e in total if e["model"] == "model-x"][0]
    assert entry["input_tokens"] == 200
    assert entry["weighted_micro_units"] == 80
    assert entry["weighted_null_rows"] == 0
    other = [e for e in total if e["model"] == "model-y"][0]
    assert other["weighted_micro_units"] is None
    assert other["weighted_null_rows"] == 2


# --- taskquality: first_review_head_stale and ci_runs (§0, §1a) ---------------------

HEAD = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _tq_snapshot(*, state_merged=True, head_sha=HEAD, comments=None):
    pr = {
        "id": "acme/widgets#21",
        "title": "Add widget cache",
        "body": "Closes #11",
        "state": "closed",
        "created_at": "2030-01-02T03:00:00Z",
        "merged_at": "2030-01-02T05:00:00Z" if state_merged else None,
        "closed_at": "2030-01-02T05:00:00Z",
        "comments": comments or [],
        "reviews": [],
        "ci_runs": [],
    }
    if head_sha is not None:
        pr["head_sha"] = head_sha
    return {"kind": "taskquality-snapshot", "schema_version": 1, "ticket": "acme/widgets#11", "prs": [pr]}


def _comment(head, verdict="pass"):
    return {"id": 1, "created_at": "2030-01-02T04:00:00Z",
            "first_line": f"審查：vendor/model-x 結論：{verdict}（head {head}）"}


def _tq_pr(snapshot):
    rep = score_ticket(snapshot, None, _tq_config())
    return rep["prs"][0], rep["metrics"]


def _tq_config():
    return DEFAULT_CONFIG


def test_first_review_head_stale_true_when_first_verdict_head_differs():
    # §0: merged, V[0].head is not a prefix of head_sha → true
    snap = _tq_snapshot(comments=[_comment("0000000")])
    pr, metrics = _tq_pr(snap)
    assert pr["first_review_head_stale"] is True
    assert metrics["first_review_head_stale_prs"] == 1


def test_first_review_head_stale_false_when_first_verdict_head_matches():
    # §0: V[0].head is a prefix of head_sha → false
    snap = _tq_snapshot(comments=[_comment("1111111")])
    pr, metrics = _tq_pr(snap)
    assert pr["first_review_head_stale"] is False
    assert metrics["first_review_head_stale_prs"] == 0


def test_first_review_head_stale_null_when_not_merged():
    # §0: 未合併 → null
    snap = _tq_snapshot(state_merged=False, comments=[_comment("0000000")])
    pr, metrics = _tq_pr(snap)
    assert pr["first_review_head_stale"] is None
    assert metrics["first_review_head_stale_prs"] == 0


def test_first_review_head_stale_null_without_verdicts_or_head_sha():
    # §0: V 為空或 None、快照無 head_sha → null
    pr, _ = _tq_pr(_tq_snapshot(comments=[]))
    assert pr["first_review_head_stale"] is None
    pr, _ = _tq_pr(_tq_snapshot(comments=[_comment("0000000")], head_sha=None))
    assert pr["first_review_head_stale"] is None


def test_ci_runs_counts_the_same_runs_as_prs_without_ci():
    # §1a: ci_runs is the count of CI runs after the same filter as prs_without_ci (0 → counted there)
    pr, metrics = _tq_pr(_tq_snapshot(comments=[_comment("1111111")]))
    assert pr["ci_runs"] == 0
    assert metrics["prs_without_ci"] == 1


# --- flags (§1a) ----------------------------------------------------------------------

def test_flags_list_merged_without_review_and_ci_and_format_mismatch():
    # §1a: merged_without_review, merged_without_ci, verdict_format_mismatch (all PRs), sorted by (ticket, pr)
    prs = [
        _pr(1, merged_at=BASE, verdicts=0, ci_runs=0),
        _pr(2, state="open", verdicts=1, unparsed=2),
        _pr(3, merged_at=BASE, verdicts=None, ci_runs=2),
    ]
    flags = build_table([_report("acme/widgets#9", prs)], WINDOW)["flags"]
    assert flags["merged_without_review"] == [{"ticket": "acme/widgets#9", "pr": "acme/widgets#1"}]
    assert flags["merged_without_ci"] == [{"ticket": "acme/widgets#9", "pr": "acme/widgets#1"}]
    assert flags["verdict_format_mismatch"] == [
        {"ticket": "acme/widgets#9", "pr": "acme/widgets#2", "state": "open", "lines": 2}
    ]
    # PR 3 has null verdicts: not listed; it is counted in flags_null_prs
    assert flags["flags_null_prs"] == 1


def test_flags_null_prs_counts_old_report_without_ci_runs():
    # §1a: a merged PR without ci_runs (old report) is not listed and counts as flags_null_prs
    rep = _report("acme/widgets#10", [_pr(1, merged_at=BASE)], old=True)
    flags = build_table([rep], WINDOW)["flags"]
    assert flags["merged_without_ci"] == []
    assert flags["flags_null_prs"] == 1


# --- closed_at and population (§1a) ---------------------------------------------------

def test_closed_at_comes_from_population_and_is_null_without_it(tmp_path, capsys):
    # §1a: closed_at per row from --population; without it, null
    reps = _write_dir(tmp_path / "r", [_report("acme/widgets#31", [_pr(1, merged_at=BASE)])])
    pop = tmp_path / "pop.json"
    pop.write_text(json.dumps({"kind": "mcq-weekly-population", "schema_version": 1,
                               "tickets": [{"ticket": "acme/widgets#31", "closed_at": "2030-01-03T00:00:00Z", "level": "L1"}]}),
                   encoding="utf-8")
    out = tmp_path / "t.json"
    rc, _, err = _cli(capsys, *_table_args(reps, out, population=pop))
    assert rc == 0, err
    assert json.loads(out.read_text())["rows"][0]["closed_at"] == "2030-01-03T00:00:00Z"
    rc, _, _ = _cli(capsys, *_table_args(reps, out))
    assert json.loads(out.read_text())["rows"][0]["closed_at"] is None


def test_population_with_wrong_kind_exits_2(tmp_path, capsys):
    reps = _write_dir(tmp_path / "r", [_report("acme/widgets#32", [_pr(1, merged_at=BASE)])])
    pop = tmp_path / "pop.json"
    pop.write_text(json.dumps({"kind": "mcq-weekly-table", "schema_version": 1, "tickets": []}), encoding="utf-8")
    rc, _, err = _cli(capsys, *_table_args(reps, tmp_path / "t.json", population=pop))
    assert rc == 2
    assert err.startswith("mcq-report: error bad_population:")


# --- CLI errors (§1) ----------------------------------------------------------------

@pytest.mark.parametrize("case, code", [
    ("missing_dir", "bad_reports_dir"),
    ("wrong_kind", "bad_report"),
    ("bad_json", "bad_json"),
    ("duplicate", "duplicate_ticket"),
])
def test_cli_errors_exit_2_with_one_line(tmp_path, capsys, case, code):
    reps = tmp_path / "r"
    reps.mkdir()
    if case == "wrong_kind":
        (reps / "a.json").write_text(json.dumps({"kind": "taskquality-snapshot"}), encoding="utf-8")
    elif case == "bad_json":
        (reps / "a.json").write_text("{not json", encoding="utf-8")
    elif case == "duplicate":
        for name in ["a.json", "b.json"]:
            (reps / name).write_text(json.dumps(_report("acme/widgets#40", [_pr(1, merged_at=BASE)])), encoding="utf-8")
    target = tmp_path / "missing" if case == "missing_dir" else reps
    rc, out, err = _cli(capsys, *_table_args(target, tmp_path / "t.json"))
    assert rc == 2 and out == ""
    assert err.startswith(f"mcq-report: error {code}: ")
    assert err.count("\n") == 1


def test_costs_is_not_supported_yet_exits_2(tmp_path, capsys):
    # §1: --costs is reserved for #63
    reps = _write_dir(tmp_path / "r", [_report("acme/widgets#41", [_pr(1, merged_at=BASE)])])
    rc, _, err = _cli(capsys, *_table_args(reps, tmp_path / "t.json"), "--costs", str(tmp_path))
    assert rc == 2
    assert err == "mcq-report: error not_supported: --costs is not supported yet\n"


def test_render_md_escapes_pipe_in_model_name():
    # Markdown table cells must not break on '|' in a model name
    usage = {"by_role_model": [{"model": "m|x", "provider": "v", "role": "impl", "input_tokens": 1,
                                "output_tokens": 1, "cache_read_tokens": 0, "cache_write_tokens": 0,
                                "cost_micro_usd": 0}]}
    md = render_md(build_table([_report("acme/widgets#42", [_pr(1, merged_at=BASE)], usage=usage)], WINDOW))
    assert "v/m\\|x" in md


def test_incomplete_is_false_and_empty_by_default_and_true_with_reasons():
    # DESIGN §1a (07:45Z): top level always has incomplete and incomplete_reasons
    plain = build_table([], WINDOW)
    assert plain["incomplete"] is False and plain["incomplete_reasons"] == []
    reasons = [
        {"ticket": "acme/widgets#9", "reason": "fetch_failed"},
        {"repo": "acme/other", "reason": "search_failed"},
    ]
    marked = build_table([], WINDOW, incomplete_reasons=reasons)
    assert marked["incomplete"] is True
    # sorted by repo-or-ticket, then reason
    assert marked["incomplete_reasons"] == [reasons[1], reasons[0]]


# --- §7 第 4 點（PM 追加 3）：weighted 規則與 usage_null_rows -----------------------

def _entry(model, weighted=None, null_items=0, **extra):
    """One by_role_model entry; weighted=ABSENT means the key is not carried (report from before #61)."""
    e = {"model": model, "provider": "vendor", "role": "impl", "input_tokens": 1, "output_tokens": 1,
         "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_micro_usd": 1}
    if weighted is not ABSENT:
        e["weighted_micro_units"] = weighted
        e["weighted_null_rows"] = null_items
    e.update(extra)
    return e


ABSENT = object()


def test_weighted_keys_appear_when_any_participating_entry_has_them():
    # 追加 3：只要任何參與列有 weighted 鍵，就輸出；沒有鍵的項目算進 weighted_null_rows
    with_key = _report("acme/widgets#51", [_pr(1, merged_at=BASE)], usage={"by_role_model": [_entry("m", 10)]})
    without = _report("acme/widgets#52", [_pr(2, merged_at=BASE)],
                      usage={"by_role_model": [_entry("m", ABSENT)]})
    entry = build_table([with_key, without], WINDOW)["summary"]["usage_by_role_model"][0]
    assert entry["weighted_micro_units"] == 10
    assert entry["weighted_null_rows"] == 1  # the entry without the key counts as one null row


def test_weighted_sum_is_null_only_when_every_present_value_is_null():
    # 追加 3：全部 null 才 null；非 null 之和照加
    all_null = _report("acme/widgets#53", [_pr(1, merged_at=BASE)], usage={"by_role_model": [_entry("m", None, 2)]})
    other_null = _report("acme/widgets#54", [_pr(2, merged_at=BASE)], usage={"by_role_model": [_entry("m", None, 3)]})
    entry = build_table([all_null, other_null], WINDOW)["summary"]["usage_by_role_model"][0]
    assert entry["weighted_micro_units"] is None
    assert entry["weighted_null_rows"] == 5
    mixed = build_table([all_null, _report("acme/widgets#55", [_pr(3, merged_at=BASE)],
                                           usage={"by_role_model": [_entry("m", 7, 0)]})], WINDOW)
    assert mixed["summary"]["usage_by_role_model"][0]["weighted_micro_units"] == 7


def test_no_weighted_keys_anywhere_means_no_weighted_keys_in_summary():
    rep = _report("acme/widgets#56", [_pr(1, merged_at=BASE)], usage={"by_role_model": [_entry("m", ABSENT)]})
    entry = build_table([rep], WINDOW)["summary"]["usage_by_role_model"][0]
    assert "weighted_micro_units" not in entry and "weighted_null_rows" not in entry


def test_usage_null_rows_counts_rows_without_usage():
    # 追加 3：usage 為 null 的列數；沒有任何 usage → usage_by_role_model null，usage_null_rows 仍記
    reps = [_report("acme/widgets#57", [_pr(1, merged_at=BASE)], usage=None),
            _report("acme/widgets#58", [_pr(2, merged_at=BASE)], usage={"by_role_model": []})]
    summary = build_table(reps, WINDOW)["summary"]
    assert summary["usage_null_rows"] == 1
    assert summary["usage_by_role_model"] == []
    none = build_table([reps[0]], WINDOW)["summary"]
    assert none["usage_by_role_model"] is None and none["usage_null_rows"] == 1
