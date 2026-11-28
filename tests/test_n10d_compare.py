"""N10d (#64): mcq-report compare over synthetic mcq-weekly-table files.

Tables are written by hand here (the table command is a separate branch). Everything is synthetic.
"""

import copy
import json

import pytest

from mcqreport import __version__
from mcqreport.cli import main
from mcqreport.compare import compare_tables, render_md

COUNT_NAMES = [
    "tickets",
    "prs_merged",
    "review_rounds",
    "fix_rounds",
    "unreviewed_merged_prs",
    "prs_without_ci",
    "unparsed_verdict_lines",
    "post_merge_verdicts",
    "first_review_head_stale_prs",
    "fix_prs_within_7d",
]
RATIO_NAMES = ["review_first_pass", "ci_first_green"]
DIST_NAMES = ["review_rounds_dist", "cycle_seconds_dist"]
FLAG_NAMES = [
    "flags.merged_without_review",
    "flags.merged_without_ci",
    "flags.verdict_format_mismatch",
    "flags_null_prs",
]
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def ratio(num, den):
    return {"num": num, "den": den, "null_rows": 0, "sample_sufficient": den >= 20}


def dist(n, median=None, p90=None):
    return {"n": n, "median": median, "p90": p90, "sample_sufficient": n >= 20}


def summary(**over):
    """A full summary with small, boring values. `over` replaces single keys."""
    base = {
        "tickets": 20,
        "prs_merged": 30,
        "review_rounds": 40,
        "fix_rounds": 10,
        "unreviewed_merged_prs": 1,
        "prs_without_ci": 2,
        "unparsed_verdict_lines": 0,
        "post_merge_verdicts": 3,
        "first_review_head_stale_prs": 4,
        "fix_prs_within_7d": 5,
        "review_first_pass": ratio(12, 20),
        "ci_first_green": ratio(15, 20),
        "review_rounds_dist": dist(20, 2, 3),
        "cycle_seconds_dist": dist(20, 3600, 7200),
    }
    base.update(over)
    return base


def flags(without_review=(), without_ci=(), mismatch=()):
    """Per-PR flag lists as the table writes them. Each entry is one PR (synthetic ids)."""
    return {
        "merged_without_review": [{"ticket": t, "pr": p} for t, p in without_review],
        "merged_without_ci": [{"ticket": t, "pr": p} for t, p in without_ci],
        "verdict_format_mismatch": [{"ticket": t, "pr": p, "state": "open", "lines": n} for t, p, n in mismatch],
    }


def table(summary_obj, rows=None, window=("2030-01-01T00:00:00Z", "2030-01-08T00:00:00Z"), flags_obj=None):
    out = {
        "kind": "mcq-weekly-table",
        "schema_version": 1,
        "tool_version": __version__,
        "window": {"from": window[0], "to": window[1]},
        "rows": rows if rows is not None else [],
        "summary": summary_obj,
        "flags": flags_obj if flags_obj is not None else flags(),
    }
    return out


def row(ticket, digest=DIGEST_A, tool=__version__, closed_at="2030-01-05T00:00:00Z"):
    return {
        "ticket": ticket,
        "status": "complete",
        "tool_version": tool,
        "config_digest": digest,
        "closed_at": closed_at,
    }


def metric(out, name):
    found = [m for m in out["metrics"] if m["name"] == name]
    assert len(found) == 1, name
    return found[0]


def test_N10d_metrics_are_listed_in_fixed_order_for_every_summary_column_then_flags():
    out = compare_tables(table(summary()), table(summary()))
    assert [m["name"] for m in out["metrics"]] == COUNT_NAMES + RATIO_NAMES + DIST_NAMES + FLAG_NAMES


def test_N10d_flags_count_list_lengths_before_after_and_delta():
    before = table(summary(), flags_obj=flags(without_review=[("acme/widgets#1", 11)], mismatch=[("acme/widgets#1", 12, 2)]))
    after = table(summary(), flags_obj=flags(without_review=[("acme/widgets#1", 11), ("acme/widgets#2", 21)], without_ci=[("acme/widgets#3", 31)]))
    out = compare_tables(before, after)
    assert metric(out, "flags.merged_without_review") == {
        "name": "flags.merged_without_review", "before": 1, "after": 2, "delta": 1,
    }
    assert metric(out, "flags.merged_without_ci") == {
        "name": "flags.merged_without_ci", "before": 0, "after": 1, "delta": 1,
    }
    assert metric(out, "flags.verdict_format_mismatch")["delta"] == -1


def test_N10d_old_table_without_flags_gives_null_counts_not_zero():
    old = table(summary())
    del old["flags"]
    out = compare_tables(old, table(summary(), flags_obj=flags(without_ci=[("acme/widgets#3", 31)])))
    m = metric(out, "flags.merged_without_ci")
    assert m == {"name": "flags.merged_without_ci", "before": None, "after": 1, "delta": None}


def test_N10d_flags_object_missing_one_list_gives_null_for_that_flag_only():
    partial = table(summary(), flags_obj=flags(without_review=[("acme/widgets#1", 11)]))
    del partial["flags"]["verdict_format_mismatch"]
    out = compare_tables(partial, table(summary(), flags_obj=flags(mismatch=[("acme/widgets#4", 41, 3)])))
    assert metric(out, "flags.verdict_format_mismatch")["delta"] is None
    assert metric(out, "flags.merged_without_review")["delta"] == -1


@pytest.mark.parametrize(
    "bad_flags",
    [
        ["not", "an", "object"],
        {"merged_without_review": {"ticket": "acme/widgets#1"}},
        {"flags_null_prs": "3"},
    ],
    ids=["flags-not-object", "flag-not-list", "flags-null-prs-not-count"],
)
def test_N10d_flags_of_the_wrong_shape_are_bad_table(tmp_path, capsys, bad_flags):
    bad = table(summary())
    bad["flags"] = bad_flags
    good = tmp_path / "good.json"
    badp = tmp_path / "bad.json"
    good.write_text(json.dumps(table(summary())), encoding="utf-8")
    badp.write_text(json.dumps(bad), encoding="utf-8")
    rc = main(["compare", str(good), str(badp), "--out", str(tmp_path / "c.json")])
    _, err = capsys.readouterr()
    assert rc == 2
    assert err.startswith("mcq-report: error bad_table: after.flags")


def test_N10d_flags_null_prs_is_a_count_and_null_when_the_key_is_missing():
    before = table(summary(), flags_obj={**flags(), "flags_null_prs": 2})
    after = table(summary(), flags_obj={**flags(), "flags_null_prs": 5})
    assert metric(compare_tables(before, after), "flags_null_prs") == {
        "name": "flags_null_prs", "before": 2, "after": 5, "delta": 3,
    }
    # flags() has no flags_null_prs key: that side is null, not 0.
    assert metric(compare_tables(table(summary()), after), "flags_null_prs") == {
        "name": "flags_null_prs", "before": None, "after": 5, "delta": None,
    }


def test_N10d_counts_give_after_minus_before_and_null_gives_null_delta():
    before = table(summary(prs_merged=30, fix_rounds=None))
    after = table(summary(prs_merged=33, fix_rounds=7))
    out = compare_tables(before, after)
    assert metric(out, "prs_merged") == {"name": "prs_merged", "before": 30, "after": 33, "delta": 3}
    assert metric(out, "fix_rounds") == {"name": "fix_rounds", "before": None, "after": 7, "delta": None}


def test_N10d_ratio_delta_is_exact_string_rounded_half_up():
    # 1/20 - 1/32 = 0.01875 exactly: the fifth decimal is 5, so it rounds up to 0.0188 (no float noise).
    out = compare_tables(
        table(summary(review_first_pass=ratio(1, 32))),
        table(summary(review_first_pass=ratio(1, 20))),
    )
    m = metric(out, "review_first_pass")
    assert m["delta_ratio"] == "0.0188"
    assert m["before"] == {"num": 1, "den": 32}
    assert m["after"] == {"num": 1, "den": 20}
    assert "conclusion" not in m


def test_N10d_ratio_negative_delta_keeps_sign_and_rounds_down_repeating_thirds():
    # 14/21 (2/3) to 7/21 (1/3): delta -0.3333...
    out = compare_tables(
        table(summary(ci_first_green=ratio(14, 21))),
        table(summary(ci_first_green=ratio(7, 21))),
    )
    assert metric(out, "ci_first_green")["delta_ratio"] == "-0.3333"


def test_N10d_ratio_negative_half_rounds_away_from_zero():
    # 8/160 -> 5/160: delta is exactly -3/160 = -0.01875; the fifth decimal is 5, so it rounds away from zero.
    out = compare_tables(
        table(summary(review_first_pass=ratio(8, 160))),
        table(summary(review_first_pass=ratio(5, 160))),
    )
    assert metric(out, "review_first_pass")["delta_ratio"] == "-0.0188"


def test_N10d_tiny_negative_delta_rounds_to_zero_without_minus_sign():
    # 19999/400000 -> 20000/400000 is -1/400000 = -0.0000025, which rounds to 0; no "-0.0000".
    out = compare_tables(
        table(summary(ci_first_green=ratio(20000, 400000))),
        table(summary(ci_first_green=ratio(19999, 400000))),
    )
    assert metric(out, "ci_first_green")["delta_ratio"] == "0.0000"


def test_N10d_ratio_zero_delta_has_no_minus_sign():
    out = compare_tables(
        table(summary(ci_first_green=ratio(10, 20))),
        table(summary(ci_first_green=ratio(10, 20))),
    )
    assert metric(out, "ci_first_green")["delta_ratio"] == "0.0000"


@pytest.mark.parametrize(
    ("before_den", "after_den"),
    [(19, 20), (20, 19), (19, 19)],
    ids=["before-19", "after-19", "both-19"],
)
def test_N10d_ratio_below_20_on_either_side_is_null_with_conclusion(before_den, after_den):
    out = compare_tables(
        table(summary(review_first_pass=ratio(1, before_den))),
        table(summary(review_first_pass=ratio(1, after_den))),
    )
    m = metric(out, "review_first_pass")
    assert m["delta_ratio"] is None
    assert m["conclusion"] == "sample_insufficient"
    assert m["before"] == {"num": 1, "den": before_den}


def test_N10d_ratio_den_20_on_both_sides_is_the_first_sufficient_sample():
    out = compare_tables(
        table(summary(ci_first_green=ratio(10, 20))),
        table(summary(ci_first_green=ratio(15, 20))),
    )
    assert metric(out, "ci_first_green")["delta_ratio"] == "0.2500"


def test_N10d_distribution_delta_needs_n_20_on_both_sides():
    out = compare_tables(
        table(summary(review_rounds_dist=dist(19, 2, 3))),
        table(summary(review_rounds_dist=dist(20, 4, 6))),
    )
    m = metric(out, "review_rounds_dist")
    assert m["delta_median"] is None and m["delta_p90"] is None
    assert m["conclusion"] == "sample_insufficient"
    assert m["before"] == {"n": 19, "median": 2, "p90": 3}


def test_N10d_distribution_with_enough_samples_gives_median_and_p90_delta():
    out = compare_tables(
        table(summary(cycle_seconds_dist=dist(20, 3600, 7200))),
        table(summary(cycle_seconds_dist=dist(25, 1800, 9000))),
    )
    m = metric(out, "cycle_seconds_dist")
    assert m["delta_median"] == -1800
    assert m["delta_p90"] == 1800
    assert "conclusion" not in m


def test_N10d_distribution_null_median_gives_null_delta_without_conclusion():
    out = compare_tables(
        table(summary(review_rounds_dist=dist(20, None, None))),
        table(summary(review_rounds_dist=dist(20, 2, 3))),
    )
    m = metric(out, "review_rounds_dist")
    assert m["delta_median"] is None and m["delta_p90"] is None
    assert "conclusion" not in m


def test_N10d_digest_and_tool_version_differences_are_warned_not_refused():
    before = table(summary(), rows=[row("acme/widgets#1", DIGEST_A, "0.4.2")])
    after = table(summary(), rows=[row("acme/widgets#2", DIGEST_B, __version__)])
    out = compare_tables(before, after)
    assert out["warnings"] == ["config_digest_differs", "tool_version_differs"]
    assert metric(out, "prs_merged")["delta"] == 0


def test_N10d_incomplete_table_gives_a_warning_for_its_side_only():
    before = table(summary())
    before["incomplete"] = True
    after = table(summary())
    after["incomplete"] = False
    assert compare_tables(before, after)["warnings"] == ["before_incomplete"]


def test_N10d_both_incomplete_gives_both_warnings_sorted_with_digest_warnings():
    before = table(summary(), rows=[row("acme/widgets#1", DIGEST_A)])
    before["incomplete"] = True
    after = table(summary(), rows=[row("acme/widgets#1", DIGEST_B)])
    after["incomplete"] = True
    assert compare_tables(before, after)["warnings"] == [
        "after_incomplete", "before_incomplete", "config_digest_differs",
    ]


def test_N10d_markdown_says_when_a_table_is_incomplete():
    before = table(summary())
    before["incomplete"] = True
    md = render_md(compare_tables(before, table(summary())))
    lines = md.splitlines()
    assert "> 注意：週表不完整（before_incomplete）" in lines
    assert "新舊不可直接比" not in md


def test_N10d_same_digest_and_version_gives_no_warning():
    before = table(summary(), rows=[row("acme/widgets#1"), row("acme/widgets#2")])
    after = table(summary(), rows=[row("acme/widgets#3")])
    assert compare_tables(before, after)["warnings"] == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda t: t.update(kind="mcq-weekly-compare"), "bad_kind"),
        (lambda t: t.update(schema_version=2), "bad_schema_version"),
        (lambda t: t.update(schema_version=True), "bad_schema_version"),
        (lambda t: t["summary"].pop("prs_merged"), "bad_table"),
        (lambda t: t["summary"].update(ci_first_green=None), "bad_table"),
        (lambda t: t.update(rows=[1]), "bad_table"),
    ],
    ids=["kind", "schema-2", "schema-bool", "missing-column", "ratio-null", "row-not-object"],
)
def test_N10d_wrong_table_is_exit_2_with_one_line_error(tmp_path, capsys, mutate, code):
    bad = table(summary())
    mutate(bad)
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(table(summary())), encoding="utf-8")
    after.write_text(json.dumps(bad), encoding="utf-8")
    rc = main(["compare", str(before), str(after), "--out", str(tmp_path / "c.json")])
    out, err = capsys.readouterr()
    assert rc == 2
    assert out == ""
    assert err.startswith(f"mcq-report: error {code}: after")
    assert err.count("\n") == 1
    assert not (tmp_path / "c.json").exists()


def test_N10d_unreadable_or_bad_json_is_exit_2(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(table(summary())), encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    rc = main(["compare", str(broken), str(good), "--out", str(tmp_path / "c.json")])
    _, err = capsys.readouterr()
    assert rc == 2
    assert err.startswith("mcq-report: error bad_json: before")


def test_N10d_output_is_deterministic_json_and_markdown(tmp_path, capsys):
    before = table(summary(), rows=[row("acme/widgets#1"), row("acme/widgets#2")])
    after = table(summary(prs_merged=31), rows=[row("acme/widgets#3", DIGEST_B)])
    pb, pa = tmp_path / "b.json", tmp_path / "a.json"
    pb.write_text(json.dumps(before), encoding="utf-8")
    pa.write_text(json.dumps(after), encoding="utf-8")
    outputs = []
    for i in range(2):
        out_json, out_md = tmp_path / f"c{i}.json", tmp_path / f"c{i}.md"
        assert main(["compare", str(pb), str(pa), "--out", str(out_json), "--md", str(out_md)]) == 0
        outputs.append((out_json.read_bytes(), out_md.read_bytes()))
    assert outputs[0] == outputs[1]
    assert outputs[0][0].endswith(b"}\n")
    assert b"\r" not in outputs[0][0] and b"\r" not in outputs[0][1]


def test_N10d_compare_object_has_kind_versions_windows_and_counts():
    before = table(summary(), rows=[row("acme/widgets#1")])
    after = table(summary(), rows=[row("acme/widgets#1"), row("acme/widgets#2")],
                  window=("2030-01-08T00:00:00Z", "2030-01-15T00:00:00Z"))
    out = compare_tables(before, after)
    assert out["kind"] == "mcq-weekly-compare"
    assert out["schema_version"] == 1
    assert out["tool_version"] == __version__
    assert out["before"] == {"window": before["window"], "tickets": 20}
    assert out["after"]["window"] == after["window"]


def test_N10d_markdown_one_metric_per_row_with_sample_wording_and_dashes():
    before = table(summary(prs_merged=None, review_first_pass=ratio(1, 19)))
    after = table(summary(prs_merged=32, review_first_pass=ratio(4, 20)))
    md = render_md(compare_tables(before, after))
    lines = md.splitlines()
    assert "| prs_merged | — | 32 | — |  |" in lines
    assert "| review_first_pass | 1/19 | 4/20 | — | 樣本不足，不下結論 |" in lines
    assert "| ci_first_green | 15/20 | 15/20 | 0.0000 |  |" in lines
    assert "| review_rounds_dist | 中位 2、p90 3（n=20） | 中位 2、p90 3（n=20） | 中位 +0、p90 +0 |  |" in lines
    assert "| flags.merged_without_ci | 0 | 0 | +0 |  |" in lines


def test_N10d_markdown_flag_counts_are_rows_too():
    before = table(summary(), flags_obj=flags(without_ci=[("acme/widgets#1", 11)]))
    after = table(summary(), flags_obj=flags(without_ci=[]))
    md = render_md(compare_tables(before, after))
    assert "| flags.merged_without_ci | 1 | 0 | -1 |  |" in md.splitlines()


def test_N10d_markdown_warns_when_not_directly_comparable():
    before = table(summary(), rows=[row("acme/widgets#1", DIGEST_A)])
    after = table(summary(), rows=[row("acme/widgets#1", DIGEST_B)])
    md = render_md(compare_tables(before, after))
    assert "新舊不可直接比（config_digest_differs）" in md


def test_N10d_cli_writes_json_and_md_for_a_twenty_ticket_table(tmp_path, capsys):
    rows_before = [row(f"acme/widgets#{i}") for i in range(1, 21)]
    rows_after = [row(f"acme/widgets#{i}") for i in range(21, 41)]
    before = table(summary(), rows=rows_before)
    after = table(
        summary(prs_merged=36, review_first_pass=ratio(16, 20), cycle_seconds_dist=dist(20, 1800, 5400)),
        rows=rows_after,
        window=("2030-01-08T00:00:00Z", "2030-01-15T00:00:00Z"),
    )
    pb, pa = tmp_path / "before.json", tmp_path / "after.json"
    pb.write_text(json.dumps(before), encoding="utf-8")
    pa.write_text(json.dumps(after), encoding="utf-8")
    out_json, out_md = tmp_path / "compare.json", tmp_path / "compare.md"
    rc = main(["compare", str(pb), str(pa), "--out", str(out_json), "--md", str(out_md)])
    out, err = capsys.readouterr()
    assert rc == 0 and out == "" and err == ""
    got = json.loads(out_json.read_text(encoding="utf-8"))
    assert metric(got, "prs_merged")["delta"] == 6
    assert metric(got, "review_first_pass")["delta_ratio"] == "0.2000"  # 12/20 -> 16/20
    assert metric(got, "cycle_seconds_dist")["delta_median"] == -1800
    assert got["warnings"] == []
    assert out_md.read_text(encoding="utf-8") == render_md(got)


def test_N10d_source_does_not_read_the_clock_or_network():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "src" / "mcqreport" / "compare.py").read_text(encoding="utf-8")
    for banned in ("import time", "datetime", "import socket", "urllib", "subprocess"):
        assert banned not in src
