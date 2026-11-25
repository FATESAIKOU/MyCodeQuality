"""index.json for one artifact (design §5.3).

Contains only the file hashes and deterministic parameters: no run id, no clock, no trigger event.
"""

import hashlib
import os

from mcqreport.common import ToolError, read_json_bytes
from mcqreport.names import REV_RE, split_repo, split_ticket

INDEX_NAME = "index.json"


def build_index(
    report: str,
    *,
    repo: str,
    qmetrics_ref: str,
    python_version: str,
    file_paths: list[str],
    rev: str | None = None,
    target: str | None = None,
    ticket: str | None = None,
    search_repos: list[str] | None = None,
) -> dict:
    if report not in ("code", "task"):
        raise ToolError("bad_arguments", f"report must be code or task: {report!r}")
    split_repo(repo)
    for field, value in (("qmetrics_ref", qmetrics_ref), ("python_version", python_version)):
        if not isinstance(value, str) or not value:
            raise ToolError("bad_arguments", f"{field} must be a non-empty string")

    if report == "code":
        if ticket is not None or search_repos:
            raise ToolError("bad_arguments", "code index takes --rev and --target, not --ticket or --search-repo")
        if rev is None or target is None:
            raise ToolError("bad_arguments", "code index needs --rev and --target")
        if not REV_RE.fullmatch(rev):
            raise ToolError("bad_rev", f"rev must be 7-40 lowercase hex characters: {rev!r}")
        if not target:
            raise ToolError("bad_arguments", "target must not be empty")
        ticket_value, search_value = None, None
    else:
        if rev is not None or target is not None:
            raise ToolError("bad_arguments", "task index takes --ticket and --search-repo, not --rev or --target")
        if ticket is None:
            raise ToolError("bad_arguments", "task index needs --ticket")
        split_ticket(ticket)
        for item in search_repos or []:
            split_repo(item)
        ticket_value = ticket
        search_value = sorted(search_repos or [])

    files = []
    seen = set()
    for path in file_paths:
        name = os.path.basename(path)
        if name == INDEX_NAME:
            raise ToolError("bad_file", f"{INDEX_NAME} cannot be listed in files")
        if name in seen:
            raise ToolError("bad_file", f"duplicate file name: {name}")
        seen.add(name)
        with open(path, "rb") as fh:
            data = fh.read()
        parsed = read_json_bytes(data, name)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("kind"), str):
            raise ToolError("bad_file", f"{name} has no kind")
        if "schema_version" not in parsed:
            raise ToolError("bad_file", f"{name} has no schema_version")
        files.append(
            {
                "name": name,
                "kind": parsed["kind"],
                "schema_version": parsed["schema_version"],
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    files.sort(key=lambda f: f["name"])

    return {
        "kind": "mcq-report-index",
        "schema_version": 1,
        "report": report,
        "repo": repo,
        "ticket": ticket_value,
        "rev": rev,
        "target": target,
        "qmetrics_ref": qmetrics_ref,
        "python_version": python_version,
        "search_repos": search_value,
        "files": files,
    }
