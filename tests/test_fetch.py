"""Tests for taskquality fetch, GitHub API interactions, and contracts C-F1 through C-F6."""

import copy
import json
from pathlib import Path
import pytest

from taskquality.cli import main
from taskquality.fetch import check_rate_limit, fetch_snapshot
from taskquality.formats import ToolError, read_json_file, validate_snapshot
from taskquality.score import score_ticket
from taskquality.conventions import DEFAULT_CONFIG


# Helper synthetic responses matching §3.1 golden scenario
def make_golden_runner(
    comment_delay: int | None = None,
    order_reversed: bool = False,
    fork_pr_style: bool = True,
):
    """Factory creating an injected mock runner simulating GitHub API responses for acme/widgets#11."""
    # Timeline GraphQL response
    nodes = [
        {
            "__typename": "ConnectedEvent",
            "subject": {
                "__typename": "PullRequest",
                "number": 21,
                "repository": {"nameWithOwner": "acme/widgets"},
            },
        },
        {
            "__typename": "CrossReferencedEvent",
            "source": {
                "__typename": "PullRequest",
                "number": 30,
                "repository": {"nameWithOwner": "acme/widgets"},
            },
        },
    ]
    if order_reversed:
        nodes = list(reversed(nodes))

    graphql_resp = {
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

    # PR #21 details
    pr21_resp = {
        "id": 2100,
        "number": 21,
        "title": "Add widget cache",
        "body": "Closes #11",
        "state": "closed",
        "draft": False,
        "created_at": "2030-01-02T03:00:00Z",
        "merged_at": "2030-01-02T05:00:00Z",
        "closed_at": "2030-01-02T05:00:00Z",
        "head": {
            "sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "ref": "feature-cache",
        },
        "merge_commit_sha": "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }

    # PR #21 comments
    pr21_comments = [
        {
            "id": 501,
            "created_at": "2030-01-02T04:00:00Z",
            "body": "審查：vendor/model-x 結論：要修（head 0000000）\n詳細說明第二行\n第三行",
            "user": {"login": "alice"},
        },
        {
            "id": 502,
            "created_at": "2030-01-02T04:50:00Z",
            "body": "審查：vendor/model-x 結論：可以 merge（head 1111111）",
            "user": {"login": "bob"},
        },
    ]
    if order_reversed:
        pr21_comments = list(reversed(pr21_comments))

    # PR #21 reviews
    pr21_reviews = [
        {
            "id": 601,
            "submitted_at": "2030-01-02T04:55:00Z",
            "state": "APPROVED",
            "commit_id": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "body": "Looks good to me!",
            "user": {"login": "charlie"},
        }
    ]

    # PR #21 commits
    pr21_commits = [
        {"sha": "0000000ccccccccccccccccccccccccccccccccc"},
        {"sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    ]

    # PR #21 actions runs: run 9001 and run 9002
    # In fork_pr_style, pull_requests is empty, matching via head_sha in commits
    pull_reqs_field = [] if fork_pr_style else [{"number": 21}]
    pr21_runs = [
        {
            "id": 9001,
            "name": "ci",
            "event": "pull_request",
            "head_sha": "0000000ccccccccccccccccccccccccccccccccc",
            "run_attempt": 1,
            "created_at": "2030-01-02T03:01:00Z",
            "status": "completed",
            "conclusion": "failure",
            "pull_requests": pull_reqs_field,
        },
        {
            "id": 9002,
            "name": "ci",
            "event": "pull_request",
            "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "run_attempt": 1,
            "created_at": "2030-01-02T04:41:00Z",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": pull_reqs_field,
        },
    ]
    if order_reversed:
        pr21_runs = list(reversed(pr21_runs))

    # PR #30 details
    pr30_resp = {
        "id": 3000,
        "number": 30,
        "title": "Bump deps",
        "body": "see #11",
        "state": "closed",
        "draft": False,
        "created_at": "2030-01-02T03:30:00Z",
        "merged_at": "2030-01-02T03:40:00Z",
        "closed_at": "2030-01-02T03:40:00Z",
        "head": {
            "sha": "4444444eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "ref": "deps-bump",
        },
        "merge_commit_sha": "5555555fffffffffffffffffffffffffffffffff",
    }

    call_counts = {}

    def runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        call_counts[cmd_str] = call_counts.get(cmd_str, 0) + 1

        if "graphql" in argv:
            return json.dumps(graphql_resp), "", 0

        # REST endpoints
        if "/repos/acme/widgets/pulls/21" in cmd_str and "--paginate" not in argv:
            return json.dumps(pr21_resp), "", 0

        if "/repos/acme/widgets/issues/21/comments" in cmd_str:
            return json.dumps(pr21_comments), "", 0

        if "/repos/acme/widgets/pulls/21/reviews" in cmd_str:
            return json.dumps(pr21_reviews), "", 0

        if "/repos/acme/widgets/pulls/21/commits" in cmd_str:
            return json.dumps(pr21_commits), "", 0

        if "/repos/acme/widgets/actions/runs" in cmd_str and ("branch=feature-cache" in cmd_str or "branch=feature%2Dcache" in cmd_str or "branch=" in cmd_str):
            return json.dumps({"workflow_runs": pr21_runs}), "", 0

        if "/repos/acme/widgets/pulls/30" in cmd_str and "--paginate" not in argv:
            return json.dumps(pr30_resp), "", 0

        if "/repos/acme/widgets/issues/30/comments" in cmd_str:
            return "[]", "", 0

        if "/repos/acme/widgets/pulls/30/reviews" in cmd_str:
            return "[]", "", 0

        if "/repos/acme/widgets/pulls/30/commits" in cmd_str:
            return json.dumps([{"sha": "4444444eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}]), "", 0

        if "/repos/acme/widgets/actions/runs" in cmd_str and "branch=deps-bump" in cmd_str:
            return json.dumps({"workflow_runs": []}), "", 0

        raise ValueError(f"unhandled mock gh call: {argv}")

    return runner


def test_c_f1_snapshot_format_and_determinism(tmp_path: Path):
    """C-F1: Injected runner returning synthetic responses generates §3.1 snapshot; arrays sorted deterministically; different response orders yield byte-identical output; fork PR CI matching via commit SHA works."""
    out_file1 = tmp_path / "snap1.json"
    out_file2 = tmp_path / "snap2.json"

    runner1 = make_golden_runner(order_reversed=False, fork_pr_style=True)
    snap1 = fetch_snapshot(
        ticket="acme/widgets#11",
        out_path=out_file1,
        runner=runner1,
    )

    runner2 = make_golden_runner(order_reversed=True, fork_pr_style=True)
    snap2 = fetch_snapshot(
        ticket="acme/widgets#11",
        out_path=out_file2,
        runner=runner2,
    )

    # 1. Byte-identical outputs regardless of upstream response order
    bytes1 = out_file1.read_bytes()
    bytes2 = out_file2.read_bytes()
    assert bytes1 == bytes2

    # 2. Conforms to §3.1 format
    validate_snapshot(snap1)
    assert snap1["kind"] == "taskquality-snapshot"
    assert snap1["schema_version"] == 1
    assert snap1["ticket"] == "acme/widgets#11"
    assert len(snap1["prs"]) == 2

    pr21 = snap1["prs"][0]
    assert pr21["id"] == "acme/widgets#21"
    assert pr21["title"] == "Add widget cache"
    assert pr21["body"] == "Closes #11"
    assert pr21["state"] == "closed"
    assert pr21["draft"] is False
    assert pr21["created_at"] == "2030-01-02T03:00:00Z"
    assert pr21["merged_at"] == "2030-01-02T05:00:00Z"
    assert pr21["closed_at"] == "2030-01-02T05:00:00Z"
    assert pr21["head_sha"] == "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert pr21["merge_commit_sha"] == "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    # Comments: only first_line, sorted by (created_at, id)
    assert len(pr21["comments"]) == 2
    assert pr21["comments"][0] == {
        "id": 501,
        "created_at": "2030-01-02T04:00:00Z",
        "first_line": "審查：vendor/model-x 結論：要修（head 0000000）",
    }
    assert pr21["comments"][1] == {
        "id": 502,
        "created_at": "2030-01-02T04:50:00Z",
        "first_line": "審查：vendor/model-x 結論：可以 merge（head 1111111）",
    }

    # Reviews: no body, sorted by (submitted_at, id)
    assert len(pr21["reviews"]) == 1
    assert pr21["reviews"][0] == {
        "id": 601,
        "submitted_at": "2030-01-02T04:55:00Z",
        "state": "APPROVED",
        "commit_id": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }

    # CI runs: fork PR matched via commit SHA, sorted by (created_at, run_id, run_attempt)
    assert len(pr21["ci_runs"]) == 2
    assert pr21["ci_runs"][0] == {
        "run_id": 9001,
        "workflow": "ci",
        "event": "pull_request",
        "head_sha": "0000000ccccccccccccccccccccccccccccccccc",
        "run_attempt": 1,
        "created_at": "2030-01-02T03:01:00Z",
        "status": "completed",
        "conclusion": "failure",
    }
    assert pr21["ci_runs"][1] == {
        "run_id": 9002,
        "workflow": "ci",
        "event": "pull_request",
        "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "run_attempt": 1,
        "created_at": "2030-01-02T04:41:00Z",
        "status": "completed",
        "conclusion": "success",
    }

    # PR #30
    pr30 = snap1["prs"][1]
    assert pr30["id"] == "acme/widgets#30"
    assert pr30["comments"] == []
    assert pr30["reviews"] == []
    assert pr30["ci_runs"] == []

    # 3. Snapshot can be cleanly consumed by taskquality score
    report = score_ticket(snap1, input_data=None, config=DEFAULT_CONFIG)
    assert report["kind"] == "taskquality-report"
    assert report["ticket"] == "acme/widgets#11"
    assert report["metrics"]["prs_merged"] == 1
    assert report["metrics"]["review_first_pass"] == {"num": 0, "den": 1}


def test_c_f2_pagination_success_and_failure(tmp_path: Path):
    """C-F2: Pagination: runner returns 2 pages -> all collected in snapshot; page 2 failure -> exit 2 incomplete_pagination and --out not left / preserved."""
    out_file = tmp_path / "snap_page.json"
    sentinel_file = tmp_path / "sentinel.json"
    sentinel_content = b'{"sentinel": true}\n'
    sentinel_file.write_bytes(sentinel_content)

    page1_graphql = {
        "data": {
            "repository": {
                "issue": {
                    "timelineItems": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor_p2"},
                        "nodes": [
                            {
                                "__typename": "ConnectedEvent",
                                "subject": {
                                    "__typename": "PullRequest",
                                    "number": 21,
                                    "repository": {"nameWithOwner": "acme/widgets"},
                                },
                            }
                        ],
                    }
                }
            }
        }
    }

    page2_graphql = {
        "data": {
            "repository": {
                "issue": {
                    "timelineItems": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "__typename": "CrossReferencedEvent",
                                "source": {
                                    "__typename": "PullRequest",
                                    "number": 30,
                                    "repository": {"nameWithOwner": "acme/widgets"},
                                },
                            }
                        ],
                    }
                }
            }
        }
    }

    # Success case: 2 pages of GraphQL timeline
    def success_page_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "graphql" in argv:
            if "cursor=cursor_p2" in cmd_str:
                return json.dumps(page2_graphql), "", 0
            return json.dumps(page1_graphql), "", 0
        # Mock other calls using golden runner
        return make_golden_runner()(argv)

    snap = fetch_snapshot("acme/widgets#11", out_file, runner=success_page_runner)
    assert len(snap["prs"]) == 2
    assert {p["id"] for p in snap["prs"]} == {"acme/widgets#21", "acme/widgets#30"}
    assert out_file.exists()

    # Failure case 1: Page 2 of GraphQL fails -> ToolError incomplete_pagination and out file not written
    def fail_p2_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "graphql" in argv:
            if "cursor=cursor_p2" in cmd_str:
                return "", "network error on page 2", 1
            return json.dumps(page1_graphql), "", 0
        return make_golden_runner()(argv)

    non_existent_out = tmp_path / "never_created.json"
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", non_existent_out, runner=fail_p2_runner)
    assert exc_info.value.code == "incomplete_pagination"
    assert not non_existent_out.exists()

    # Failure case 2: Pre-existing file is NOT overwritten when pagination fails
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", sentinel_file, runner=fail_p2_runner)
    assert exc_info.value.code == "incomplete_pagination"
    assert sentinel_file.read_bytes() == sentinel_content


def test_c_f3_rate_limiting(tmp_path: Path):
    """C-F3: Rate limit: runner returns 429 with Retry-After: 1 then 200 -> succeeds, sleeper called once with arg 1; consecutive 4x 429 -> rate_limited, sleeper called 3 times."""
    out_file = tmp_path / "snap_rl.json"
    sleep_calls = []

    def mock_sleeper(seconds: float):
        sleep_calls.append(seconds)

    # 1. 429 then success
    rl_then_ok_calls = 0

    def rl_then_ok_runner(argv: list[str]) -> tuple[str, str, int]:
        nonlocal rl_then_ok_calls
        rl_then_ok_calls += 1
        if rl_then_ok_calls == 1:
            return "HTTP/1.1 429 Too Many Requests\nRetry-After: 1\n\nRate limit exceeded", "", 429
        return make_golden_runner()(argv)

    snap = fetch_snapshot(
        "acme/widgets#11",
        out_file,
        runner=rl_then_ok_runner,
        sleeper=mock_sleeper,
    )
    assert snap["ticket"] == "acme/widgets#11"
    assert sleep_calls == [1]

    # 2. 4 consecutive 429s -> ToolError rate_limited
    sleep_calls.clear()

    def always_rl_runner(argv: list[str]) -> tuple[str, str, int]:
        return "HTTP/1.1 429 Too Many Requests\nRetry-After: 5\n\nRate limit exceeded", "", 429

    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot(
            "acme/widgets#11",
            out_file,
            runner=always_rl_runner,
            sleeper=mock_sleeper,
        )
    assert exc_info.value.code == "rate_limited"
    assert sleep_calls == [5, 5, 5]


def test_c_f4_no_private_info_and_filtered_fields(tmp_path: Path):
    """C-F4: Comments store only first line; review does not store body; snapshot contains no author names, accounts, fetch timestamps."""
    out_file = tmp_path / "snap_filtered.json"
    snap = fetch_snapshot("acme/widgets#11", out_file, runner=make_golden_runner())

    content = out_file.read_text(encoding="utf-8")
    # Verify no author accounts from the mock data leaked into JSON
    assert "alice" not in content
    assert "bob" not in content
    assert "charlie" not in content
    assert "Looks good to me!" not in content
    assert "詳細說明第二行" not in content
    assert "fetched_at" not in content
    assert "user" not in content
    assert "author" not in content

    pr21 = snap["prs"][0]
    # Comments only have id, created_at, first_line
    for c in pr21["comments"]:
        assert set(c.keys()) == {"id", "created_at", "first_line"}
        assert "\n" not in c["first_line"]

    # Reviews only have id, submitted_at, state, commit_id
    for r in pr21["reviews"]:
        assert set(r.keys()) == {"id", "submitted_at", "state", "commit_id"}


def test_c_f5_gh_unavailable_and_not_found(tmp_path: Path):
    """C-F5: gh not found -> gh_unavailable; issue not found -> not_found."""
    out_file = tmp_path / "snap_err.json"

    # 1. gh executable not found
    def missing_gh_runner(argv: list[str]):
        raise FileNotFoundError("gh")

    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file, runner=missing_gh_runner)
    assert exc_info.value.code == "gh_unavailable"

    # 2. Issue not found via GraphQL NOT_FOUND error
    def not_found_graphql_runner(argv: list[str]) -> tuple[str, str, int]:
        resp = {
            "data": {"repository": None},
            "errors": [
                {
                    "type": "NOT_FOUND",
                    "message": "Could not resolve to an Issue with the number of 11.",
                }
            ],
        }
        return json.dumps(resp), "", 0

    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file, runner=not_found_graphql_runner)
    assert exc_info.value.code == "not_found"

    # 3. Explicit PR not found (404)
    def pr_not_found_runner(argv: list[str]) -> tuple[str, str, int]:
        if "graphql" in argv:
            # issue exists, but has no PRs
            return json.dumps({
                "data": {
                    "repository": {
                        "issue": {
                            "timelineItems": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [],
                            }
                        }
                    }
                }
            }), "", 0
        if "/pulls/999" in " ".join(argv):
            return "HTTP/1.1 404 Not Found\n\n{'message': 'Not Found'}", "Not Found", 1
        return make_golden_runner()(argv)

    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot(
            "acme/widgets#11",
            out_file,
            explicit_prs=["acme/widgets#999"],
            runner=pr_not_found_runner,
        )
    assert exc_info.value.code == "not_found"


def test_c_f6_search_repo_filtering_and_explicit_pr(tmp_path: Path):
    """C-F6: --search-repo filters candidate PRs from other repos; --pr explicitly specified PR always included."""
    out_file = tmp_path / "snap_c_f6.json"

    # GraphQL timeline returns PRs from acme/widgets and other/repo
    def multi_repo_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "graphql" in argv:
            return json.dumps({
                "data": {
                    "repository": {
                        "issue": {
                            "timelineItems": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "__typename": "ConnectedEvent",
                                        "subject": {
                                            "__typename": "PullRequest",
                                            "number": 21,
                                            "repository": {"nameWithOwner": "acme/widgets"},
                                        },
                                    },
                                    {
                                        "__typename": "ConnectedEvent",
                                        "subject": {
                                            "__typename": "PullRequest",
                                            "number": 50,
                                            "repository": {"nameWithOwner": "other/repo"},
                                        },
                                    },
                                ],
                            }
                        }
                    }
                }
            }), "", 0

        if "/repos/other/repo/pulls/88" in cmd_str:
            return json.dumps({
                "id": 8800,
                "number": 88,
                "title": "Explicit PR from other repo",
                "body": "Fixes acme/widgets#11",
                "state": "closed",
                "draft": False,
                "created_at": "2030-01-02T02:00:00Z",
                "merged_at": "2030-01-02T02:30:00Z",
                "closed_at": "2030-01-02T02:30:00Z",
                "head": {"sha": "8888888888888888888888888888888888888888", "ref": "other-fix"},
                "merge_commit_sha": "9999999999999999999999999999999999999999",
            }), "", 0

        if "/repos/other/repo/issues/88/comments" in cmd_str:
            return "[]", "", 0
        if "/repos/other/repo/pulls/88/reviews" in cmd_str:
            return "[]", "", 0
        if "/repos/other/repo/pulls/88/commits" in cmd_str:
            return json.dumps([{"sha": "8888888888888888888888888888888888888888"}]), "", 0
        if "/repos/other/repo/actions/runs" in cmd_str:
            return json.dumps({"workflow_runs": []}), "", 0

        return make_golden_runner()(argv)

    # When search_repos=["acme/widgets"]:
    # other/repo#50 is excluded from candidate PRs
    # but other/repo#88 is explicitly given via explicit_prs, so it MUST be included!
    snap = fetch_snapshot(
        ticket="acme/widgets#11",
        out_path=out_file,
        search_repos=["acme/widgets"],
        explicit_prs=["other/repo#88"],
        runner=multi_repo_runner,
    )

    pr_ids = [p["id"] for p in snap["prs"]]
    assert "acme/widgets#21" in pr_ids
    assert "other/repo#50" not in pr_ids  # Filtered out by search_repo!
    assert "other/repo#88" in pr_ids      # Explicitly included!


def test_cli_fetch_bad_arguments_and_out_unwritable(tmp_path: Path, monkeypatch, capsys):
    """Test CLI error handling: bad arguments, invalid ticket / PR, unwritable out path, and successful CLI run."""
    monkeypatch.setattr("taskquality.fetch.default_runner", make_golden_runner())

    # 1. Invalid ticket format
    code = main(["fetch", "--ticket", "invalid_ticket", "--out", str(tmp_path / "out.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert "error bad_arguments:" in err

    # 2. Invalid PR format
    code = main(["fetch", "--ticket", "acme/widgets#11", "--pr", "not_a_pr", "--out", str(tmp_path / "out.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert "error bad_arguments:" in err

    # 3. Invalid search-repo format
    code = main(["fetch", "--ticket", "acme/widgets#11", "--search-repo", "not_a_repo", "--out", str(tmp_path / "out.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert "error bad_arguments:" in err

    # 4. Out path is an existing directory
    out_dir = tmp_path / "dir_as_out"
    out_dir.mkdir()
    code = main(["fetch", "--ticket", "acme/widgets#11", "--out", str(out_dir)])
    assert code == 2
    err = capsys.readouterr().err
    assert "error out_unwritable:" in err

    # 5. Successful CLI run
    success_out = tmp_path / "cli_success.json"
    code = main(["fetch", "--ticket", "acme/widgets#11", "--out", str(success_out)])
    assert code == 0
    assert success_out.exists()
    snap = json.loads(success_out.read_text(encoding="utf-8"))
    assert snap["ticket"] == "acme/widgets#11"


# --- Tests for BRIEF-11b2-fix requirements (Items 1, 2, 3, 5) ---


def test_item1_check_rate_limit_code_zero_ignores_429_and_403(tmp_path: Path):
    """Item 1: check_rate_limit must not treat 429/403 in stdout as rate limit when code == 0; no sleep, no retry."""
    # 1. Unit tests on check_rate_limit
    assert check_rate_limit(stdout='{"body": "Fixes #429 and #403", "id": 429}', stderr="", code=0) == (False, None, None)
    assert check_rate_limit(stdout='429 403\nRetry-After: 60', stderr="warning 429", code=0) == (False, None, None)
    assert check_rate_limit(stdout='x-ratelimit-reset: 9999999999\n429\n403', stderr="", code=0) == (False, None, None)

    # 2. End-to-end fetch_snapshot where PR body/comment/id contain standalone 429 and 403 numbers
    sleep_calls = []

    def mock_sleeper(seconds: float):
        sleep_calls.append(seconds)

    golden = make_golden_runner()

    def code_zero_with_numbers_runner(argv: list[str]) -> tuple[str, str, int]:
        out, err, code = golden(argv)
        # Inject standalone 429 and 403 into PR body and comments
        if "/repos/acme/widgets/pulls/21" in " ".join(argv) and "--paginate" not in argv:
            data = json.loads(out)
            data["title"] = "Fix issue 429"
            data["body"] = "Resolves #429 and addresses 403 vulnerability"
            return json.dumps(data), err, 0
        if "/repos/acme/widgets/issues/21/comments" in " ".join(argv):
            data = json.loads(out)
            data.append({
                "id": 429,
                "created_at": "2030-01-02T04:15:00Z",
                "body": "Comment mentions error 429 and HTTP 403 code",
                "user": {"login": "eve"},
            })
            return json.dumps(data), err, 0
        return out, err, code

    out_file = tmp_path / "snap_code0.json"
    snap = fetch_snapshot(
        ticket="acme/widgets#11",
        out_path=out_file,
        runner=code_zero_with_numbers_runner,
        sleeper=mock_sleeper,
    )
    validate_snapshot(snap)
    assert len(sleep_calls) == 0  # Crucial: did NOT sleep or retry
    assert snap["prs"][0]["title"] == "Fix issue 429"
    assert "429 and addresses 403" in snap["prs"][0]["body"]
    comment_ids = [c["id"] for c in snap["prs"][0]["comments"]]
    assert 429 in comment_ids


def test_item2_run_attempt_supplement_and_ci_runs_sorting(tmp_path: Path):
    """Item 2: run_attempt > 1 fetches /actions/runs/{id}/attempts/{k} and sorts ci_runs by (created_at, run_id, run_attempt)."""
    attempt_endpoint_calls = []

    def multi_attempt_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "/repos/acme/widgets/actions/runs/9001/attempts/" in cmd_str:
            attempt_endpoint_calls.append(cmd_str)
            # Return attempt 1 for run 9001
            att1 = {
                "id": 9001,
                "name": "ci",
                "event": "pull_request",
                "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "run_attempt": 1,
                "created_at": "2030-01-02T03:00:00Z",
                "status": "completed",
                "conclusion": "failure",
            }
            return json.dumps(att1), "", 0

        if "/repos/acme/widgets/actions/runs" in cmd_str:
            # Workflow runs list returns:
            # Run 9001 currently at attempt 2 (created at 03:30)
            # Run 9002 at attempt 1 (created at 03:15)
            runs = [
                {
                    "id": 9001,
                    "name": "ci",
                    "event": "pull_request",
                    "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "run_attempt": 2,
                    "created_at": "2030-01-02T03:30:00Z",
                    "status": "completed",
                    "conclusion": "success",
                    "pull_requests": [{"number": 21}],
                },
                {
                    "id": 9002,
                    "name": "ci",
                    "event": "pull_request",
                    "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "run_attempt": 1,
                    "created_at": "2030-01-02T03:15:00Z",
                    "status": "completed",
                    "conclusion": "failure",
                    "pull_requests": [{"number": 21}],
                },
            ]
            return json.dumps({"workflow_runs": runs}), "", 0

        return make_golden_runner()(argv)

    out_file = tmp_path / "snap_attempts.json"
    snap = fetch_snapshot(
        ticket="acme/widgets#11",
        out_path=out_file,
        runner=multi_attempt_runner,
    )
    validate_snapshot(snap)

    # 1. Verify attempt endpoint was called
    assert any("/actions/runs/9001/attempts/1" in c for c in attempt_endpoint_calls)

    # 2. Verify all attempts are collected in ci_runs
    pr21 = snap["prs"][0]
    ci_runs = pr21["ci_runs"]
    assert len(ci_runs) == 3

    # 3. Verify deterministic sorting: (created_at, run_id, run_attempt)
    # 03:00 -> run 9001, attempt 1
    # 03:15 -> run 9002, attempt 1
    # 03:30 -> run 9001, attempt 2
    assert ci_runs[0]["run_id"] == 9001
    assert ci_runs[0]["run_attempt"] == 1
    assert ci_runs[0]["created_at"] == "2030-01-02T03:00:00Z"
    assert ci_runs[0]["conclusion"] == "failure"

    assert ci_runs[1]["run_id"] == 9002
    assert ci_runs[1]["run_attempt"] == 1
    assert ci_runs[1]["created_at"] == "2030-01-02T03:15:00Z"
    assert ci_runs[1]["conclusion"] == "failure"

    assert ci_runs[2]["run_id"] == 9001
    assert ci_runs[2]["run_attempt"] == 2
    assert ci_runs[2]["created_at"] == "2030-01-02T03:30:00Z"
    assert ci_runs[2]["conclusion"] == "success"

    # 4. Verify score_ticket works with supplemented attempts
    report = score_ticket(snap, input_data=None, config=DEFAULT_CONFIG)
    assert report["kind"] == "taskquality-report"


def test_item2_rate_limit_403_and_x_ratelimit_reset_with_time_func_and_cap(tmp_path: Path):
    """Item 2: 403 + x-ratelimit-reset branch with injected time_func and 60-second single sleep cap."""
    # Subcase A: x-ratelimit-reset 25 seconds ahead -> sleep 25s, then succeeds
    sleep_calls = []

    def mock_sleeper(seconds: float):
        sleep_calls.append(seconds)

    current_simulated_time = 1_000_000.0

    def mock_time_func() -> float:
        return current_simulated_time

    attempt_count = 0

    def rl_403_runner(argv: list[str]) -> tuple[str, str, int]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            err_msg = "HTTP/1.1 403 Forbidden\nx-ratelimit-reset: 1000025\n\nRate limit exceeded"
            return "", err_msg, 403
        return make_golden_runner()(argv)

    out_file1 = tmp_path / "snap_rl_403.json"
    snap1 = fetch_snapshot(
        "acme/widgets#11",
        out_file1,
        runner=rl_403_runner,
        sleeper=mock_sleeper,
        time_func=mock_time_func,
    )
    assert snap1["ticket"] == "acme/widgets#11"
    assert sleep_calls == [25]  # 1000025 - 1000000 = 25s

    # Subcase B: x-ratelimit-reset 120 seconds ahead -> sleep capped at 60s
    sleep_calls.clear()
    attempt_count = 0

    def rl_403_cap_runner(argv: list[str]) -> tuple[str, str, int]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            err_msg = "HTTP/1.1 403 Forbidden\nx-ratelimit-reset: 1000120\n\nRate limit exceeded"
            return "", err_msg, 403
        return make_golden_runner()(argv)

    out_file2 = tmp_path / "snap_rl_cap.json"
    snap2 = fetch_snapshot(
        "acme/widgets#11",
        out_file2,
        runner=rl_403_cap_runner,
        sleeper=mock_sleeper,
        time_func=mock_time_func,
    )
    assert snap2["ticket"] == "acme/widgets#11"
    assert sleep_calls == [60]  # min(120, 60) = 60s

    # Subcase C: consecutive 403 + x-ratelimit-reset -> rate_limited error after 3 retries
    sleep_calls.clear()

    def always_403_runner(argv: list[str]) -> tuple[str, str, int]:
        return "", "HTTP/1.1 403 Forbidden\nx-ratelimit-reset: 1000080\n\nRate limit", 403

    out_file3 = tmp_path / "snap_rl_fail.json"
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot(
            "acme/widgets#11",
            out_file3,
            runner=always_403_runner,
            sleeper=mock_sleeper,
            time_func=mock_time_func,
        )
    assert exc_info.value.code == "rate_limited"
    assert sleep_calls == [60, 60, 60]  # capped at 60s each retry


def test_item3_rest_paginate_multiple_chunks_collected(tmp_path: Path):
    """Item 3: REST --paginate concatenates multiple JSON arrays and {"workflow_runs": [...]} chunks into snapshot."""
    # Chunked comments: two arrays
    chunk1_comments = [
        {"id": 501, "created_at": "2030-01-02T04:00:00Z", "body": "First page comment", "user": {"login": "alice"}}
    ]
    chunk2_comments = [
        {"id": 502, "created_at": "2030-01-02T04:30:00Z", "body": "Second page comment", "user": {"login": "bob"}}
    ]
    paginated_comments_raw = f"{json.dumps(chunk1_comments)}\n{json.dumps(chunk2_comments)}"

    # Chunked workflow runs: two {"workflow_runs": [...]} objects
    run1 = {
        "id": 9001,
        "name": "ci",
        "event": "pull_request",
        "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "run_attempt": 1,
        "created_at": "2030-01-02T03:01:00Z",
        "status": "completed",
        "conclusion": "failure",
        "pull_requests": [{"number": 21}],
    }
    run2 = {
        "id": 9002,
        "name": "ci",
        "event": "pull_request",
        "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "run_attempt": 1,
        "created_at": "2030-01-02T04:41:00Z",
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [{"number": 21}],
    }
    paginated_runs_raw = f"{json.dumps({'workflow_runs': [run1]})}\n{json.dumps({'workflow_runs': [run2]})}"

    def paginate_chunks_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "/repos/acme/widgets/issues/21/comments" in cmd_str:
            return paginated_comments_raw, "", 0
        if "/repos/acme/widgets/actions/runs" in cmd_str and "branch=feature-cache" in cmd_str:
            return paginated_runs_raw, "", 0
        return make_golden_runner()(argv)

    out_file = tmp_path / "snap_paginated_chunks.json"
    snap = fetch_snapshot("acme/widgets#11", out_file, runner=paginate_chunks_runner)
    validate_snapshot(snap)

    pr21 = snap["prs"][0]
    # Verify both comments collected
    assert len(pr21["comments"]) == 2
    assert pr21["comments"][0]["id"] == 501
    assert pr21["comments"][1]["id"] == 502

    # Verify both workflow runs collected
    assert len(pr21["ci_runs"]) == 2
    assert pr21["ci_runs"][0]["run_id"] == 9001
    assert pr21["ci_runs"][1]["run_id"] == 9002


def test_item3_rest_paginate_truncated_and_bad_json_fails(tmp_path: Path):
    """Item 3: Truncated or malformed JSON in paginated output raises incomplete_pagination and --out is not created/modified."""
    # 1. Truncated comments output
    def truncated_comments_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "/repos/acme/widgets/issues/21/comments" in cmd_str:
            # Chunk 1 ok, chunk 2 truncated
            return '[{"id": 501, "created_at": "2030-01-02T04:00:00Z", "body": "ok"}]\n[{"id": 502', "", 0
        return make_golden_runner()(argv)

    out_file1 = tmp_path / "never_created_comments.json"
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file1, runner=truncated_comments_runner)
    assert exc_info.value.code == "incomplete_pagination"
    assert not out_file1.exists()

    # Pre-existing file is preserved
    sentinel_file = tmp_path / "sentinel_comments.json"
    sentinel_content = b'{"preserved": true}\n'
    sentinel_file.write_bytes(sentinel_content)
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", sentinel_file, runner=truncated_comments_runner)
    assert exc_info.value.code == "incomplete_pagination"
    assert sentinel_file.read_bytes() == sentinel_content

    # 2. Truncated workflow runs output
    def truncated_runs_runner(argv: list[str]) -> tuple[str, str, int]:
        cmd_str = " ".join(argv)
        if "/repos/acme/widgets/actions/runs" in cmd_str and "branch=feature-cache" in cmd_str:
            return '{"workflow_runs": [{"id": 9001}]}\n{"workflow_runs": [', "", 0
        return make_golden_runner()(argv)

    out_file2 = tmp_path / "never_created_runs.json"
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file2, runner=truncated_runs_runner)
    assert exc_info.value.code == "incomplete_pagination"
    assert not out_file2.exists()


def test_item5_fetch_snapshot_direct_bad_explicit_prs(tmp_path: Path):
    """Item 5: fetch_snapshot directly called with invalid explicit_prs or search_repos raises bad_arguments."""
    out_file = tmp_path / "snap_unused.json"

    # 1. Invalid PR format string
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file, explicit_prs=["invalid_pr_string"])
    assert exc_info.value.code == "bad_arguments"

    # 2. Non-string PR identifier
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file, explicit_prs=[123])
    assert exc_info.value.code == "bad_arguments"

    # 3. Invalid search-repo format
    with pytest.raises(ToolError) as exc_info:
        fetch_snapshot("acme/widgets#11", out_file, search_repos=["no_slash_repo"])
    assert exc_info.value.code == "bad_arguments"

