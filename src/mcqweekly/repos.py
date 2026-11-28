"""Repo list input: `{"kind":"mcq-weekly-repos","schema_version":1,"repos":["owner/name", ...]}`."""

from mcqreport.common import ToolError, read_json_file
from taskquality.formats import parse_pr_id
from mcqweekly.errors import TOOL_ERRORS


def is_v1(value) -> bool:
    return type(value) is int and value == 1


def check_repo(repo, code: str = "bad_repos") -> str:
    """Same OWNER/REPO rule as taskquality: anything parse_pr_id accepts as the repo part of a ticket."""
    if not isinstance(repo, str):
        raise ToolError(code, f"repo must be a string: {repo!r}")
    try:
        owner_repo, _ = parse_pr_id(repo + "#1", code)
    except TOOL_ERRORS:
        raise ToolError(code, f"repo must be OWNER/REPO: {repo!r}") from None
    if owner_repo.count("/") != 1:
        raise ToolError(code, f"repo must be OWNER/REPO: {repo!r}")
    return repo


def canonical_repos(repos: list[str]) -> list[str]:
    """Validate, reject case-insensitive duplicates, sort by lowercase name."""
    seen: dict[str, str] = {}
    for repo in repos:
        check_repo(repo)
        key = repo.lower()
        if key in seen:
            raise ToolError("bad_repos", f"duplicate repo (case-insensitive): {repo!r}")
        seen[key] = repo
    return sorted(seen.values(), key=str.lower)


def load_repos(path: str) -> list[str]:
    data = read_json_file(path, "repos")
    if not isinstance(data, dict):
        raise ToolError("bad_repos", "repos file must be a JSON object")
    if data.get("kind") != "mcq-weekly-repos" or not is_v1(data.get("schema_version")):
        raise ToolError("bad_repos", "repos file must have kind='mcq-weekly-repos' and schema_version=1")
    repos = data.get("repos")
    if not isinstance(repos, list) or not repos:
        raise ToolError("bad_repos", "repos must be a non-empty list")
    return canonical_repos(repos)
