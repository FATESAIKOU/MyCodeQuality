"""mcq-weekly run: offline/refetch/reuse, failure isolation, costs, publish protocol, determinism. Fake gh runners only."""

import json
import os
import stat

import mcqweekly.run as run_mod
from mcqreport.common import ToolError
from mcqweekly.cli import main
from mcqweekly.run import incomplete_reasons
from weekly_helpers import GRAPHQL_EMPTY, FROM, TO, fake_table_api, no_gh_runner, ticket_row, write_population

R1 = "acme/alpha"
R2 = "acme/beta"
T1 = f"{R1}#1"
T2 = f"{R2}#2"


class GraphqlRunner:
    """Answers the fetch GraphQL queries with an empty timeline. `fail_ticket` makes one ticket's calls fail."""

    def __init__(self, fail_ticket=None, first_rate_limited=False):
        self.calls = []
        self.fail_ticket = fail_ticket
        self.first_rate_limited = first_rate_limited

    def __call__(self, argv):
        self.calls.append(argv)
        if self.first_rate_limited and len(self.calls) == 1:
            return "HTTP/1.1 429 Too Many Requests\nRetry-After: 1\n\nRate limit exceeded", "", 429
        if self.fail_ticket and f"number={self.fail_ticket}" in argv:
            return "", "gh: boom (HTTP 500)", 1
        return GRAPHQL_EMPTY, "", 0


def pop_file(tmp_path, tickets=(T1,), repos=(R1,), name="population.json", statuses=None):
    rows = [ticket_row(t) for t in tickets]
    return write_population(tmp_path / name, list(repos), rows, statuses=statuses)


def run_main(pop, work, runner, costs=None, extra=(), table_api=None, sleeper=None):
    argv = ["run", "--population", str(pop), "--work", str(work)]
    if costs is not None:
        argv += ["--costs", str(costs)]
    argv += list(extra)
    return main(argv, runner=runner, table_api=table_api or fake_table_api(), sleeper=sleeper)


def read_run(work, n):
    return json.loads((work / "runs" / n / "run.json").read_text(encoding="utf-8"))


def out_current(work):
    return json.loads((work / "out.json").read_text(encoding="utf-8"))["current"]


def test_offline_never_calls_runner(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    code = run_main(pop, work, no_gh_runner, extra=["--offline"])
    assert code == 3
    run = read_run(work, "001")
    assert run["failed"] == [{"ticket": T1, "stage": "fetch", "code": "offline_missing"}]
    assert run["gh_calls"] == 0
    assert out_current(work) == "runs/001"


def test_online_then_reuse_without_gh(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    first = GraphqlRunner()
    assert run_main(pop, work, first) == 0
    assert read_run(work, "001")["fetched"] == 1
    assert read_run(work, "001")["api_pages"] == 2  # timeline + label queries, one page each

    assert run_main(pop, work, no_gh_runner) == 0  # reuse: the runner must not be called
    run = read_run(work, "002")
    assert (run["fetched"], run["reused"], run["gh_calls"]) == (0, 1, 0)
    assert out_current(work) == "runs/002"


def test_refetch_calls_runner(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    run_main(pop, work, GraphqlRunner())
    again = GraphqlRunner()
    assert run_main(pop, work, again, extra=["--refetch"]) == 0
    assert again.calls, "--refetch must call gh"
    assert read_run(work, "002")["fetched"] == 1


def test_refetch_failure_does_not_fall_back_to_old_snapshot(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    run_main(pop, work, GraphqlRunner())
    assert run_main(pop, work, GraphqlRunner(fail_ticket=1), extra=["--refetch"]) == 3
    run = read_run(work, "002")
    assert [f["stage"] for f in run["failed"]] == ["fetch"]
    assert not (work / "runs" / "002" / "reports" / "acme__alpha__1.json").exists()


def test_corrupt_snapshot_is_treated_as_absent(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    run_main(pop, work, GraphqlRunner())
    (work / "snapshots" / "acme__alpha__1.json").write_text("{ not json", encoding="utf-8")
    assert run_main(pop, work, no_gh_runner, extra=["--offline"]) == 3
    assert read_run(work, "002")["failed"][0]["code"] == "offline_missing"
    online = GraphqlRunner()
    assert run_main(pop, work, online) == 0
    assert online.calls and read_run(work, "003")["fetched"] == 1


def test_wider_mode_on_reused_snapshot_is_tightened_and_work_is_private(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    run_main(pop, work, GraphqlRunner())
    snap = work / "snapshots" / "acme__alpha__1.json"
    os.chmod(snap, 0o644)
    assert run_main(pop, work, no_gh_runner) == 0
    assert stat.S_IMODE(os.stat(snap).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(work).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(work / "out.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(work / "runs" / "002" / "table.json").st_mode) == 0o600


def test_snapshot_symlink_is_refused(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    (work / "snapshots").mkdir(parents=True)
    (tmp_path / "elsewhere.json").write_text("{}", encoding="utf-8")
    os.symlink(tmp_path / "elsewhere.json", work / "snapshots" / "acme__alpha__1.json")
    assert run_main(pop, work, no_gh_runner, extra=["--offline"]) == 2


def test_private_work_inside_git_worktree_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    pop = pop_file(tmp_path)
    assert run_main(pop, repo / "w", no_gh_runner, extra=["--offline"]) == 2
    os.symlink(repo / "w", tmp_path / "link")
    assert run_main(pop, tmp_path / "link", no_gh_runner, extra=["--offline"]) == 2


def test_costs_inside_repo_is_refused_and_missing_costs_dir_is_exit_2(tmp_path):
    pop = pop_file(tmp_path)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert run_main(pop, tmp_path / "w", no_gh_runner, costs=repo, extra=["--offline"]) == 2
    assert run_main(pop, tmp_path / "w", no_gh_runner, costs=tmp_path / "nope", extra=["--offline"]) == 2


def test_costs_bad_file_fails_that_ticket_good_file_is_used(tmp_path):
    pop = pop_file(tmp_path, tickets=(T1, T2), repos=(R1, R2))
    work = tmp_path / "w"
    costs = tmp_path / "costs"
    costs.mkdir()
    (costs / "acme__alpha__1.json").write_text(json.dumps({"kind": "taskquality-input", "schema_version": 1, "ticket": T1}), encoding="utf-8")
    (costs / "acme__beta__2.json").write_text(json.dumps({"kind": "taskquality-input", "schema_version": 1, "ticket": "acme/other#9"}), encoding="utf-8")
    assert run_main(pop, work, GraphqlRunner(), costs=costs) == 3
    run = read_run(work, "001")
    assert run["failed"] == [{"ticket": T2, "stage": "cost_input", "code": "ticket_mismatch"}]
    assert (work / "runs" / "001" / "reports" / "acme__alpha__1.json").exists()


def test_score_failure_is_recorded_and_others_continue(tmp_path, monkeypatch):
    pop = pop_file(tmp_path, tickets=(T1, T2), repos=(R1, R2))
    work = tmp_path / "w"
    real = run_mod.score_ticket

    def flaky(snapshot, input_data, config):
        if snapshot["ticket"] == T2:
            raise ToolError("score_boom", "synthetic")
        return real(snapshot, input_data, config)

    monkeypatch.setattr(run_mod, "score_ticket", flaky)
    assert run_main(pop, work, GraphqlRunner()) == 3
    assert read_run(work, "001")["failed"] == [{"ticket": T2, "stage": "score", "code": "score_boom"}]


def test_one_ticket_fetch_failure_does_not_stop_others(tmp_path):
    pop = pop_file(tmp_path, tickets=(T1, T2), repos=(R1, R2))
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner(fail_ticket=2)) == 3
    run = read_run(work, "001")
    assert run["fetched"] == 1
    assert [f["ticket"] for f in run["failed"]] == [T2]


def test_table_failure_is_exit_2_and_out_json_keeps_previous_run(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner()) == 0
    before = (work / "out.json").read_bytes()

    class Broken:
        def build_table(self, *a, **k):
            raise RuntimeError("table exploded")

        def render_md(self, table):
            return ""

    assert run_main(pop, work, no_gh_runner, table_api=Broken()) == 2
    assert (work / "out.json").read_bytes() == before
    assert out_current(work) == "runs/001"


def test_publish_failure_keeps_previous_out_json(tmp_path, monkeypatch):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner()) == 0
    before = (work / "out.json").read_bytes()

    real = run_mod.write_new_file

    def fail_table(path, text):
        if path.name == "table.json":
            raise ToolError("write_failed", "synthetic disk full")
        return real(path, text)

    monkeypatch.setattr(run_mod, "write_new_file", fail_table)
    assert run_main(pop, work, no_gh_runner) == 2
    assert (work / "out.json").read_bytes() == before
    assert not (work / "out.json.tmp").exists()


def test_incomplete_follows_population_status(tmp_path):
    pop = pop_file(tmp_path, tickets=(T1,), repos=(R1, R2), statuses={R2: "list_failed"})
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner()) == 3
    table = json.loads((work / "runs" / "001" / "table.json").read_text(encoding="utf-8"))
    assert table["incomplete"] is True
    assert table["incomplete_reasons"] == [{"repo": R2, "reason": "list_failed"}]
    assert "不完整" in (work / "runs" / "001" / "table.md").read_text(encoding="utf-8")

    pop2 = pop_file(tmp_path, tickets=(T1,), repos=(R1,), name="p2.json", statuses={R1: "truncated"})
    assert run_main(pop2, work, GraphqlRunner()) == 3
    table2 = json.loads((work / "runs" / "002" / "table.json").read_text(encoding="utf-8"))
    assert table2["incomplete_reasons"] == [{"repo": R1, "reason": "truncated"}]


def test_empty_population_still_publishes_a_table(tmp_path):
    pop = write_population(tmp_path / "p.json", [R1], [])
    work = tmp_path / "w"
    assert run_main(pop, work, no_gh_runner) == 0
    table = json.loads((work / "runs" / "001" / "table.json").read_text(encoding="utf-8"))
    assert table["incomplete"] is False and table["incomplete_reasons"] == [] and table["failed_tickets"] == []
    assert out_current(work) == "runs/001"


def test_repo_and_ticket_order_do_not_change_products(tmp_path):
    work = tmp_path / "w"
    pop_a = pop_file(tmp_path, tickets=(T1, T2), repos=(R1, R2), name="a.json")
    pop_b = write_population(tmp_path / "b.json", [R2, R1],
                             [ticket_row(T2), ticket_row(T1)])
    assert run_main(pop_a, work, GraphqlRunner()) == 0
    assert run_main(pop_b, work, no_gh_runner) == 0
    for name in ("reports", "table.json", "table.md"):
        a = (work / "runs" / "001" / name)
        b = (work / "runs" / "002" / name)
        if a.is_dir():
            assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
            for p in a.iterdir():
                assert p.read_bytes() == (b / p.name).read_bytes()
        else:
            assert a.read_bytes() == b.read_bytes(), name


def test_same_inputs_same_bytes_across_runs(tmp_path):
    pop = pop_file(tmp_path, tickets=(T1, T2), repos=(R1, R2))
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner()) == 0
    assert run_main(pop, work, no_gh_runner) == 0
    for name in ("table.json", "table.md"):
        assert (work / "runs" / "001" / name).read_bytes() == (work / "runs" / "002" / name).read_bytes()
    assert (work / "runs" / "001" / "reports" / "acme__alpha__1.json").read_bytes() == \
        (work / "runs" / "002" / "reports" / "acme__alpha__1.json").read_bytes()


def test_rate_limit_waits_and_api_pages_are_recorded(tmp_path):
    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    waits = []
    assert run_main(pop, work, GraphqlRunner(first_rate_limited=True), sleeper=waits.append) == 0
    run = read_run(work, "001")
    assert run["rate_limit_waits"] == 1 and waits == [1]
    assert run["api_pages"] == 3  # the 429 attempt counts as a request


def test_incomplete_reasons_are_totally_ordered_and_deduplicated():
    population = {"repos": [{"repo": "Zed/b", "status": "list_failed"}, {"repo": "acme/a", "status": "truncated"},
                            {"repo": "acme/ok", "status": "ok"}]}
    failed = [
        {"ticket": "acme/a#2", "stage": "score", "code": "x"},
        {"ticket": "acme/a#2", "stage": "fetch", "code": "y"},
        {"ticket": "acme/a#2", "stage": "fetch", "code": "y"},
    ]
    first = incomplete_reasons(population, failed)
    second = incomplete_reasons(
        {"repos": list(reversed(population["repos"]))}, list(reversed(failed))
    )
    assert first == second
    assert first == [
        {"repo": "acme/a", "reason": "truncated"},
        {"repo": "Zed/b", "reason": "list_failed"},
        {"ticket": "acme/a#2", "reason": "fetch:y"},
        {"ticket": "acme/a#2", "reason": "score:x"},
    ]


def test_one_ticket_outside_population_repos_is_usage_error(tmp_path):
    pop = write_population(tmp_path / "p.json", [R1], [ticket_row(T2)])
    assert run_main(pop, tmp_path / "w", no_gh_runner, extra=["--offline"]) == 2


def test_table_module_missing_is_exit_2_with_one_line_error(tmp_path, capsys):
    pop = pop_file(tmp_path)
    argv = ["run", "--population", str(pop), "--work", str(tmp_path / "w"), "--offline"]
    assert main(argv, runner=no_gh_runner) == 2
    assert "table_unavailable" in capsys.readouterr().err


def test_no_pr_text_in_stderr(tmp_path, capsys):
    pop = pop_file(tmp_path)
    run_main(pop, tmp_path / "w", GraphqlRunner(fail_ticket=1))
    err = capsys.readouterr().err
    assert "boom" not in err and "acme" not in err


def test_failure_while_switching_out_json_keeps_previous_pointer(tmp_path, monkeypatch):
    import mcqweekly.fsio as fsio

    pop = pop_file(tmp_path)
    work = tmp_path / "w"
    assert run_main(pop, work, GraphqlRunner()) == 0
    before = (work / "out.json").read_bytes()

    real = fsio.write_new_file

    def fail_pointer(path, text):
        if path.name.startswith("out.json"):
            raise ToolError("write_failed", "synthetic failure while switching the pointer")
        return real(path, text)

    monkeypatch.setattr(fsio, "write_new_file", fail_pointer)
    assert run_main(pop, work, no_gh_runner) == 2
    assert (work / "out.json").read_bytes() == before
    assert out_current(work) == "runs/001"


def test_offline_and_refetch_are_mutually_exclusive_exit_2(tmp_path):
    pop = pop_file(tmp_path)
    assert run_main(pop, tmp_path / "w", no_gh_runner, extra=["--offline", "--refetch"]) == 2
