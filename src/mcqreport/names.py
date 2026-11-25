"""Artifact names (design §5.2). Names only use [A-Za-z0-9._-].

Code:  mcq-code--<owner>.<repo>--<target>--<YYYYMMDD>--<rev 7>
Task:  mcq-task--<owner>.<repo>--i<N>--<YYYYMMDD>--<final|prov>--<snapshot sha256 8>
"""

import datetime
import hashlib
import re

from mcqreport.common import ToolError, check_days, parse_utc

REPO_RE = re.compile(r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)")
TICKET_RE = re.compile(r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)#([1-9][0-9]{0,8})")
SAFE_RE = re.compile(r"[A-Za-z0-9._-]+")
REV_RE = re.compile(r"[0-9a-f]{7,40}")


def split_repo(repo) -> tuple[str, str]:
    """owner/repo → (owner, repo). Bad form is a bad_repo tool error."""
    m = REPO_RE.fullmatch(repo) if isinstance(repo, str) else None
    if not m:
        raise ToolError("bad_repo", f"repo must be OWNER/REPO: {repo!r}")
    return m.group(1), m.group(2)


def repo_slug(repo) -> str:
    """owner.repo, lowercase. Owners never contain a dot, so the first dot is unambiguous."""
    owner, name = split_repo(repo)
    return f"{owner}.{name}".lower()


def split_ticket(ticket) -> tuple[str, str, int]:
    m = TICKET_RE.fullmatch(ticket) if isinstance(ticket, str) else None
    if not m:
        raise ToolError("bad_ticket", f"ticket must be OWNER/REPO#N: {ticket!r}")
    return m.group(1), m.group(2), int(m.group(3))


def check_target(target) -> str:
    """A target is one path-free name part: [A-Za-z0-9._-]+, and not the bare '.' or '..'."""
    if not isinstance(target, str) or not SAFE_RE.fullmatch(target) or target in (".", ".."):
        raise ToolError("bad_name_part", f"target may only contain [A-Za-z0-9._-] and is not '.' or '..': {target!r}")
    return target


def code_name(repo, target, committed_at, rev) -> str:
    slug = repo_slug(repo)
    check_target(target)
    if not isinstance(rev, str) or not REV_RE.fullmatch(rev):
        raise ToolError("bad_rev", f"rev must be 7-40 lowercase hex characters: {rev!r}")
    day = parse_utc(committed_at, "committed_at").strftime("%Y%m%d")
    return f"mcq-code--{slug}--{target}--{day}--{rev[:7]}"


def is_final(closed_at: datetime.datetime, run_at: datetime.datetime, status, missing_reasons, settle_days: int) -> bool:
    """final = settled for settle_days, report not in_progress, and no ci_incomplete left."""
    if status == "in_progress" or "ci_incomplete" in missing_reasons:
        return False
    return run_at - closed_at >= datetime.timedelta(days=settle_days)


def task_name(ticket, closed_at, run_at, status, missing_reasons, snapshot: bytes, settle_days: int) -> str:
    owner, name, number = split_ticket(ticket)
    slug = f"{owner}.{name}".lower()
    check_days(settle_days, "settle-days", 0)
    closed = parse_utc(closed_at, "closed_at")
    run = parse_utc(run_at, "run_at")
    state = "final" if is_final(closed, run, status, missing_reasons, settle_days) else "prov"
    digest = hashlib.sha256(snapshot).hexdigest()[:8]
    return f"mcq-task--{slug}--i{number}--{closed.strftime('%Y%m%d')}--{state}--{digest}"


def task_prefix(repo, number: int) -> str:
    """The fixed part of a task name for one ticket. The trailing '--' keeps i1 and i11 apart."""
    return f"mcq-task--{repo_slug(repo)}--i{number}--"
