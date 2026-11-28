"""Conventions, default config, ticket reference and verdict matching for taskquality."""

import re
from taskquality.formats import parse_pr_id

DEFAULT_CONFIG = {
    "kind": "taskquality-config",
    "schema_version": 1,
    "ticket_ref_keywords": [
        "closes",
        "close",
        "closed",
        "fixes",
        "fix",
        "fixed",
        "resolves",
        "resolve",
        "resolved",
        "refs",
        "ref",
    ],
    "verdict_sources": ["comments"],
    "github_review_role": "審查",
    "verdict_pattern": r"^(?P<role>\S*審查)：(?P<model>[^\s（）]+)(?:（(?P<note>[^）]*)）)? 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})(?:[；;][^）]*)?）",
    "review_roles": ["審查"],
    "pass_verdicts": ["可以 merge", "通過"],
    "fail_verdicts": ["要修", "要退回", "要退回設計"],
    "rework_keywords": ["修正", "fix", "fixes", "follow-up", "revert"],
    "ci_workflows": None,
    "ci_green_conclusions": ["success", "neutral", "skipped"],
}


def heads_match(h1: str, h2: str) -> bool:
    """Return True if h1 and h2 are prefixes of each other (case-insensitive)."""
    h1_l = h1.lower()
    h2_l = h2.lower()
    return h1_l.startswith(h2_l) or h2_l.startswith(h1_l)


def match_ticket_ref(
    title: str | None,
    body: str | None,
    pr_repo: str,
    ticket: str,
    keywords: list[str],
) -> bool:
    """Check if title or body contains `<keyword>[:]? <ref>` pointing to ticket."""
    ticket_repo, ticket_num = parse_pr_id(ticket)
    text = (title or "") + "\n" + (body or "")
    if not text.strip() or not keywords:
        return False

    kw_pat = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))
    ref_pat = (
        r"(?:https?://[^\s/]+/(?P<url_repo>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)/issues/(?P<url_num>\d+)"
        r"|(?P<full_repo>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)#(?P<full_num>\d+)"
        r"|#(?P<short_num>\d+))"
    )
    pattern = re.compile(
        r"(?i)(?:^|[\s\W]|(?<=[\u4e00-\u9fff]))(?P<kw>" + kw_pat + r")(?::)?\s+" + ref_pat
    )

    for m in pattern.finditer(text):
        if m.group("url_num"):
            repo = m.group("url_repo")
            num = int(m.group("url_num"))
        elif m.group("full_num"):
            repo = m.group("full_repo")
            num = int(m.group("full_num"))
        else:
            repo = pr_repo
            num = int(m.group("short_num"))

        if repo.lower() == ticket_repo.lower() and num == ticket_num:
            return True

    return False


def detect_rework(
    pr: dict,
    ticket_prs: list[dict],
    rework_keywords: list[str],
) -> bool:
    """Detect if PR title or body references an earlier merged PR of the same ticket after a rework keyword."""
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    text = title + "\n" + body
    if not text.strip() or not rework_keywords:
        return False

    pr_repo, _ = parse_pr_id(pr["id"])
    created_at = pr["created_at"]

    kw_pat = "|".join(re.escape(k) for k in sorted(rework_keywords, key=len, reverse=True))
    ref_pat = (
        r"(?:https?://[^\s/]+/(?P<url_repo>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)/pull/(?P<url_num>\d+)"
        r"|(?P<full_repo>[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)#(?P<full_num>\d+)"
        r"|#(?P<short_num>\d+))"
    )
    pattern = re.compile(
        r"(?i)(?:^|[\s\W]|(?<=[\u4e00-\u9fff]))(?P<kw>" + kw_pat + r")(?::)?\s*" + ref_pat
    )

    # Pre-index ticket_prs by lowercase id
    prs_by_id = {p["id"].lower(): p for p in ticket_prs}

    for m in pattern.finditer(text):
        if m.group("url_num"):
            repo = m.group("url_repo")
            num = int(m.group("url_num"))
        elif m.group("full_num"):
            repo = m.group("full_repo")
            num = int(m.group("full_num"))
        else:
            repo = pr_repo
            num = int(m.group("short_num"))

        target_id = f"{repo.lower()}#{num}"
        target_pr = prs_by_id.get(target_id)
        if target_pr and target_pr.get("merged_at"):
            if target_pr["merged_at"] < created_at:
                return True

    return False


VERDICT_LINE_PREFIX_RE = re.compile(r"^\S*審查：")
STRUCTURE_NOTE_MARKERS = ("架構", "結構")


def extract_verdicts_detailed(
    pr: dict,
    input_prs_override: dict | None,
    config: dict,
) -> dict:
    """Extract review verdicts sequence V and the N37 PR-level counters.

    Returns a dict with:
    - `source`: verdicts_source string
    - `verdicts`: V_list, or None when input explicitly provides verdicts as null
    - `post_merge_verdicts`: review verdicts of a merged PR whose `at` is after `merged_at`
    - `unparsed_verdict_lines`: comment first lines that look like verdict lines
      (`^\\S*審查：`) but do not match verdict_pattern (comments source only)
    - `structure_note_verdicts`: verdict lines dropped because their `note`
      group mentions architecture/structure (only when the pattern has a `note` group)
    """
    pr_id = pr["id"]
    unparsed_verdict_lines = 0
    structure_note_verdicts = 0
    nonstandard_verdict_lines = 0

    if input_prs_override and pr_id in input_prs_override and "verdicts" in input_prs_override[pr_id]:
        verdicts_source = "input"
        raw_v = input_prs_override[pr_id]["verdicts"]
        if raw_v is None:
            V = None
        else:
            # raw_v is a list of dicts: at, role, model, verdict, head
            V = []
            for idx, item in enumerate(raw_v):
                if item.get("role") in config["review_roles"]:
                    V.append({
                        "at": item["at"],
                        "idx": idx,
                        "role": item["role"],
                        "model": item.get("model"),
                        "verdict": item["verdict"],
                        "head": item["head"].lower(),
                    })
            V.sort(key=lambda x: (x["at"], x["idx"]))
    else:
        verdicts_source = "+".join(s for s in ["comments", "reviews"] if s in config["verdict_sources"])
        V = []
        verdict_re = re.compile(config["verdict_pattern"])
        has_note_group = "note" in verdict_re.groupindex

        if "comments" in config["verdict_sources"]:
            for c in pr.get("comments", []):
                line = c.get("first_line") or ""
                m = verdict_re.match(line)
                if m is None:
                    if VERDICT_LINE_PREFIX_RE.match(line):
                        unparsed_verdict_lines += 1
                    continue
                if any(m.group(g) is None for g in ("role", "model", "verdict", "head")):
                    continue
                role = m.group("role")
                if role in config["review_roles"]:
                    if has_note_group:
                        note = m.group("note")
                        if note and any(marker in note for marker in STRUCTURE_NOTE_MARKERS):
                            structure_note_verdicts += 1
                            continue
                    raw_verdict = m.group("verdict").strip()
                    if raw_verdict in config["pass_verdicts"]:
                        v_kind = "pass"
                    elif raw_verdict in config["fail_verdicts"]:
                        v_kind = "fail"
                    else:
                        v_kind = "other"
                    head = m.group("head").lower()
                    head_end = m.end("head")
                    if line[head_end : head_end + 1] in ("；", ";"):
                        nonstandard_verdict_lines += 1
                    V.append({
                        "at": c["created_at"],
                        "source_order": 0,
                        "id": c["id"],
                        "role": role,
                        "model": m.group("model"),
                        "verdict": v_kind,
                        "head": head,
                    })

        if "reviews" in config["verdict_sources"]:
            for r in pr.get("reviews", []):
                st = r.get("state")
                if st == "APPROVED":
                    v_kind = "pass"
                elif st == "CHANGES_REQUESTED":
                    v_kind = "fail"
                else:
                    continue
                role = config["github_review_role"]
                if role in config["review_roles"]:
                    V.append({
                        "at": r["submitted_at"],
                        "source_order": 1,
                        "id": r["id"],
                        "role": role,
                        "model": None,
                        "verdict": v_kind,
                        "head": r["commit_id"].lower(),
                    })

        V.sort(key=lambda x: (x["at"], x["source_order"], x["id"]))

    # N37 decision 3: only verdicts at or before merged_at count; later ones are separate.
    post_merge_verdicts = 0
    merged_at = pr.get("merged_at")
    if V and merged_at is not None:
        kept = [v for v in V if v["at"] <= merged_at]
        post_merge_verdicts = len(V) - len(kept)
        V = kept

    return {
        "source": verdicts_source,
        "verdicts": V,
        "post_merge_verdicts": post_merge_verdicts,
        "structure_note_verdicts": structure_note_verdicts,
        "unparsed_verdict_lines": unparsed_verdict_lines,
        "nonstandard_verdict_lines": nonstandard_verdict_lines,
    }
