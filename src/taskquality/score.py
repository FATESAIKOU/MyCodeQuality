"""Calculation of task quality metrics for a ticket."""

from taskquality.conventions import (
    detect_rework,
    extract_verdicts_detailed,
    heads_match,
    match_ticket_ref,
)
from taskquality.formats import (
    calculate_config_digest,
    parse_iso_utc,
    parse_pr_id,
)

from taskquality import SCHEMA_VERSION, __version__ as TOOL_VERSION

TOKEN_KEYS = [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
]


def first_labeled_at(snapshot: dict, label: str) -> str | None:
    """Earliest 'labeled' event time for label in the snapshot, or None if absent (§4.1)."""
    times = [
        ev["at"]
        for ev in snapshot.get("ticket_labels", [])
        if ev["label"] == label and ev["action"] == "labeled"
    ]
    return min(times) if times else None


def _aggregate_usage(items: list, has_weighted: bool) -> tuple[dict, list]:
    """Sum one group of usage items: token keys, plus weighted keys when has_weighted.

    A null or missing value in the group makes that token total null (null means unknown, not 0).
    Returns (values, [(key, reason)]) so the caller decides the missing field name.
    Weighted: the sum of non-null values, or null when none; weighted_null_rows counts
    items whose value is null or absent. Weighted never adds to missing.
    """
    values = {}
    missing = []
    for t_k in TOKEN_KEYS:
        has_null = any(it.get(t_k) is None and t_k in it for it in items)
        has_missing = any(t_k not in it for it in items)
        if has_null:
            values[t_k] = None
            missing.append((t_k, "input_null"))
        elif has_missing:
            values[t_k] = None
            missing.append((t_k, "input_missing"))
        else:
            values[t_k] = sum(it[t_k] for it in items)
    if has_weighted:
        present = [it["weighted_micro_units"] for it in items if it.get("weighted_micro_units") is not None]
        values["weighted_micro_units"] = sum(present) if present else None
        values["weighted_null_rows"] = sum(1 for it in items if it.get("weighted_micro_units") is None)
    return values, missing


def score_warnings(
    snapshot: dict,
    unrecognized_count: int,
    config: dict,
    unparsed_count: int = 0,
) -> list[str]:
    """Advisory hints for the report's `warnings` (§3.0); they never change any other field.

    Sorted and de-duplicated. The conclusion text from GitHub is never echoed back.
    """
    warnings = []
    if unrecognized_count > 0:
        warnings.append(
            f"unrecognized_verdict: {unrecognized_count} verdict line(s) matched the pattern "
            "but the conclusion is in neither pass_verdicts nor fail_verdicts"
        )
    if unparsed_count > 0:
        warnings.append(
            f"unparsed_verdict_lines: {unparsed_count} verdict-like line(s) did not match verdict_pattern"
        )

    # ci_workflows names checked against every ci_run in the snapshot; no runs at all means no hint
    if config["ci_workflows"] is not None:
        seen = {r["workflow"] for p in snapshot.get("prs", []) for r in p.get("ci_runs", [])}
        if seen:
            for name in config["ci_workflows"]:
                if name in seen:
                    continue
                if any(name.lower() == s.lower() for s in seen):
                    warnings.append(f"ci_workflows_unmatched: {name} (case differs from an existing workflow name)")
                else:
                    warnings.append(f"ci_workflows_unmatched: {name}")

    return sorted(set(warnings))


def score_ticket(snapshot: dict, input_data: dict | None, config: dict) -> dict:
    """Score a ticket snapshot against input and config according to §4."""
    ticket = snapshot["ticket"]
    config_digest = calculate_config_digest(config)
    ci_required = config.get("ci_required", True)

    # 1. Ticket PRs vs Excluded PRs
    ticket_prs_raw = []
    excluded_prs = []
    for pr in snapshot.get("prs", []):
        pr_id = pr["id"]
        pr_repo, _ = parse_pr_id(pr_id)
        if match_ticket_ref(
            pr.get("title"),
            pr.get("body"),
            pr_repo,
            ticket,
            config["ticket_ref_keywords"],
        ):
            ticket_prs_raw.append(pr)
        else:
            excluded_prs.append({"pr": pr_id, "reason": "no_ticket_ref"})

    ticket_prs_raw.sort(key=lambda p: parse_pr_id(p["id"]))
    excluded_prs.sort(key=lambda x: parse_pr_id(x["pr"]))

    input_prs_override = input_data.get("prs") if input_data else None

    # 2. Per-PR calculation
    pr_results = []
    pr_missing_map = {}
    unrecognized_count = 0

    for pr in ticket_prs_raw:
        pr_id = pr["id"]
        missing_dict = {}

        # State
        if pr.get("merged_at") is not None:
            state = "merged"
        elif pr.get("state") == "open":
            state = "open"
        else:
            state = "closed_unmerged"

        # Verdicts & Review Metrics
        v_info = extract_verdicts_detailed(pr, input_prs_override, config)
        verdicts_source = v_info["source"]
        V = v_info["verdicts"]
        pr_post_merge = v_info["post_merge_verdicts"]
        pr_structure_note = v_info["structure_note_verdicts"]
        pr_unparsed = v_info["unparsed_verdict_lines"]
        pr_nonstandard = v_info["nonstandard_verdict_lines"]
        if V:
            unrecognized_count += sum(1 for v in V if v["verdict"] == "other")
        if V is None:
            verdicts = None
            first_review_pass = None
            fix_rounds = None
            re_reviews = None
            approved_head_stale = None
            missing_dict["verdicts"] = "input_null"
            missing_dict["first_review_pass"] = "input_null"
            missing_dict["fix_rounds"] = "input_null"
            missing_dict["re_reviews"] = "input_null"
            missing_dict["approved_head_stale"] = "input_null"
        elif len(V) == 0:
            verdicts = 0
            first_review_pass = None
            fix_rounds = None
            re_reviews = None
            approved_head_stale = None
            missing_dict["first_review_pass"] = "no_verdict"
            missing_dict["fix_rounds"] = "no_verdict"
            missing_dict["re_reviews"] = "no_verdict"
            missing_dict["approved_head_stale"] = "no_verdict"
        else:
            verdicts = len(V)
            # first_review_pass
            v1 = V[0]
            if v1["verdict"] == "other":
                first_review_pass = None
                missing_dict["first_review_pass"] = "unrecognized_verdict"
            else:
                first_review_pass = (v1["verdict"] == "pass")

            # fix_rounds
            if any(v["verdict"] == "other" for v in V):
                fix_rounds = None
                missing_dict["fix_rounds"] = "unrecognized_verdict"
            else:
                fix_rounds = sum(1 for v in V if v["verdict"] == "fail")

            # re_reviews
            cnt = 0
            for i in range(1, len(V)):
                if not heads_match(V[i]["head"], V[i - 1]["head"]):
                    cnt += 1
            re_reviews = cnt

            # approved_head_stale
            last_v = V[-1]
            if last_v["verdict"] == "other":
                approved_head_stale = None
                missing_dict["approved_head_stale"] = "unrecognized_verdict"
            elif last_v["verdict"] == "fail":
                approved_head_stale = False
            else:
                head_sha = (pr.get("head_sha") or "").lower()
                approved_head_stale = not head_sha.startswith(last_v["head"])

        # CI Runs
        raw_runs = pr.get("ci_runs", [])
        ci_runs = [r for r in raw_runs if r.get("run_attempt") == 1]
        if config["ci_workflows"] is not None:
            ci_runs = [r for r in ci_runs if r.get("workflow") in config["ci_workflows"]]

        if len(ci_runs) == 0:
            ci_first_head = None
            ci_first_green = None
            missing_dict["ci_first_green"] = "no_ci_runs"
        else:
            ci_runs.sort(key=lambda r: (r["created_at"], r["run_id"], r["run_attempt"]))
            ci_first_head = ci_runs[0]["head_sha"]
            first_head_runs = [r for r in ci_runs if r["head_sha"] == ci_first_head]
            green_set = set(config["ci_green_conclusions"])

            if any(r.get("status") == "completed" and r.get("conclusion") not in green_set for r in first_head_runs):
                ci_first_green = False
            elif all(r.get("status") == "completed" and r.get("conclusion") in green_set for r in first_head_runs):
                ci_first_green = True
            else:
                ci_first_green = None
                missing_dict["ci_first_green"] = "ci_incomplete"

        # Rework
        if input_prs_override and pr_id in input_prs_override and "rework" in input_prs_override[pr_id]:
            rework_source = "input"
            rework = input_prs_override[pr_id]["rework"]
            if rework is None:
                missing_dict["rework"] = "input_null"
        else:
            rework_source = "derived"
            rework = detect_rework(pr, ticket_prs_raw, config["rework_keywords"])

        pr_missing_map[pr_id] = missing_dict
        pr_results.append({
            "approved_head_stale": approved_head_stale,
            "ci_first_green": ci_first_green,
            "ci_first_head": ci_first_head,
            "created_at": pr["created_at"],
            "first_review_pass": first_review_pass,
            "fix_rounds": fix_rounds,
            "merged_at": pr.get("merged_at"),
            "nonstandard_verdict_lines": pr_nonstandard,
            "post_merge_verdicts": pr_post_merge,
            "pr": pr_id,
            "re_reviews": re_reviews,
            "rework": rework,
            "rework_source": rework_source,
            "state": state,
            "structure_note_verdicts": pr_structure_note,
            "unparsed_verdict_lines": pr_unparsed,
            "verdicts": verdicts,
            "verdicts_source": verdicts_source,
        })

    pr_results.sort(key=lambda p: parse_pr_id(p["pr"]))

    # 3. Metrics aggregation
    metric_missing = {}
    prs_merged = sum(1 for p in pr_results if p["state"] == "merged")
    prs_open = sum(1 for p in pr_results if p["state"] == "open")
    prs_closed_unmerged = sum(1 for p in pr_results if p["state"] == "closed_unmerged")
    unreviewed_merged_prs = sum(
        1 for p in pr_results if p["state"] == "merged" and p["verdicts"] == 0
    )
    prs_without_ci = sum(
        1 for p in pr_results if p["state"] == "merged" and p["ci_first_head"] is None
    )

    merged_prs = [p for p in pr_results if p["state"] == "merged"]
    candidate_merged = [p for p in merged_prs if p["verdicts"] != 0]

    # review_first_pass
    if len(merged_prs) == 0:
        review_first_pass = None
        metric_missing["review_first_pass"] = {"no_merged_pr"}
    elif len(candidate_merged) == 0:
        review_first_pass = None
        metric_missing["review_first_pass"] = {"no_verdict"}
    elif any(p["first_review_pass"] is None for p in candidate_merged):
        review_first_pass = None
        metric_missing["review_first_pass"] = {
            pr_missing_map[p["pr"]]["first_review_pass"]
            for p in candidate_merged
            if p["first_review_pass"] is None and "first_review_pass" in pr_missing_map[p["pr"]]
        }
    else:
        num = sum(1 for p in candidate_merged if p["first_review_pass"] is True)
        den = len(candidate_merged)
        review_first_pass = {"num": num, "den": den}

    # fix_rounds
    if len(merged_prs) == 0:
        fix_rounds = None
        metric_missing["fix_rounds"] = {"no_merged_pr"}
    elif len(candidate_merged) == 0:
        fix_rounds = None
        metric_missing["fix_rounds"] = {"no_verdict"}
    elif any(p["fix_rounds"] is None for p in candidate_merged):
        fix_rounds = None
        metric_missing["fix_rounds"] = {
            pr_missing_map[p["pr"]]["fix_rounds"]
            for p in candidate_merged
            if p["fix_rounds"] is None and "fix_rounds" in pr_missing_map[p["pr"]]
        }
    else:
        fix_rounds = sum(p["fix_rounds"] for p in candidate_merged)

    # re_reviews
    if len(merged_prs) == 0:
        re_reviews = None
        metric_missing["re_reviews"] = {"no_merged_pr"}
    elif len(candidate_merged) == 0:
        re_reviews = None
        metric_missing["re_reviews"] = {"no_verdict"}
    elif any(p["re_reviews"] is None for p in candidate_merged):
        re_reviews = None
        metric_missing["re_reviews"] = {
            pr_missing_map[p["pr"]]["re_reviews"]
            for p in candidate_merged
            if p["re_reviews"] is None and "re_reviews" in pr_missing_map[p["pr"]]
        }
    else:
        re_reviews = sum(p["re_reviews"] for p in candidate_merged)

    # approved_head_stale
    if len(merged_prs) == 0:
        approved_head_stale = None
        metric_missing["approved_head_stale"] = {"no_merged_pr"}
    elif len(candidate_merged) == 0:
        approved_head_stale = None
        metric_missing["approved_head_stale"] = {"no_verdict"}
    elif any(p["approved_head_stale"] is None for p in candidate_merged):
        approved_head_stale = None
        metric_missing["approved_head_stale"] = {
            pr_missing_map[p["pr"]]["approved_head_stale"]
            for p in candidate_merged
            if p["approved_head_stale"] is None and "approved_head_stale" in pr_missing_map[p["pr"]]
        }
    else:
        approved_head_stale = sum(1 for p in candidate_merged if p["approved_head_stale"] is True)

    # ci_first_green
    if any(p["ci_first_green"] is None and pr_missing_map[p["pr"]].get("ci_first_green") == "ci_incomplete" for p in merged_prs):
        ci_first_green = None
        metric_missing["ci_first_green"] = {"ci_incomplete"}
    else:
        evaluated_ci = [p for p in merged_prs if p["ci_first_green"] is not None]
        if len(evaluated_ci) == 0:
            ci_first_green = None
            metric_missing["ci_first_green"] = {"no_merged_pr"} if len(merged_prs) == 0 else {"no_ci_runs"}
        else:
            num = sum(1 for p in evaluated_ci if p["ci_first_green"] is True)
            den = len(evaluated_ci)
            ci_first_green = {"num": num, "den": den}

    # rework_prs
    if any(p["rework"] is None for p in pr_results):
        rework_prs = None
        metric_missing["rework_prs"] = {
            pr_missing_map[p["pr"]]["rework"]
            for p in pr_results
            if p["rework"] is None and "rework" in pr_missing_map[p["pr"]]
        }
    else:
        rework_prs = sum(1 for p in pr_results if p["rework"] is True)

    # cycle_seconds & cycle_basis
    started_label = config.get("started_label")
    label_started_at = first_labeled_at(snapshot, started_label) if started_label else None
    if input_data and input_data.get("started_at"):
        cycle_basis = "input_started_at"
        start_ts = input_data["started_at"]
    elif label_started_at is not None:
        cycle_basis = "ticket_label"
        start_ts = label_started_at
    elif ticket_prs_raw:
        cycle_basis = "first_pr_created"
        start_ts = min(p["created_at"] for p in ticket_prs_raw)
    else:
        cycle_basis = None
        start_ts = None

    if prs_open > 0:
        cycle_seconds = None
        metric_missing["cycle_seconds"] = {"pr_open"}
    elif prs_merged == 0:
        cycle_seconds = None
        metric_missing["cycle_seconds"] = {"no_merged_pr"}
    else:
        latest_merged_at = max(p["merged_at"] for p in merged_prs)
        dt_start = parse_iso_utc(start_ts)
        dt_end = parse_iso_utc(latest_merged_at)
        diff = int((dt_end - dt_start).total_seconds())
        if diff < 0:
            cycle_seconds = None
            metric_missing["cycle_seconds"] = {"bad_interval"}
        else:
            cycle_seconds = diff

    metrics = {
        "approved_head_stale": approved_head_stale,
        "ci_first_green": ci_first_green,
        "cycle_basis": cycle_basis,
        "cycle_seconds": cycle_seconds,
        "fix_rounds": fix_rounds,
        "nonstandard_verdict_lines": sum(p["nonstandard_verdict_lines"] for p in merged_prs),
        "post_merge_verdicts": sum(p["post_merge_verdicts"] for p in merged_prs),
        "prs_closed_unmerged": prs_closed_unmerged,
        "prs_merged": prs_merged,
        "prs_open": prs_open,
        "prs_without_ci": prs_without_ci,
        "re_reviews": re_reviews,
        "review_first_pass": review_first_pass,
        "rework_prs": rework_prs,
        "structure_note_verdicts": sum(p["structure_note_verdicts"] for p in merged_prs),
        "unparsed_verdict_lines": sum(p["unparsed_verdict_lines"] for p in merged_prs),
        "unreviewed_merged_prs": unreviewed_merged_prs,
    }

    # 4. Status
    if len(ticket_prs_raw) == 0:
        status = "no_prs"
    elif prs_open > 0:
        status = "in_progress"
    elif prs_merged == 0:
        status = "no_merged_pr"
    else:
        status = "complete"

    # 5. Clean
    clean_reasons = set()
    if status != "complete":
        clean = None
        clean_reasons.add("pr_open" if status == "in_progress" else "no_merged_pr")
    else:
        # Conditions 1-7: True, False, or (None, reasons_set)
        c1 = (unreviewed_merged_prs == 0)
        # ci_required false: condition 2 does not apply (§6).
        c2 = (prs_without_ci == 0) if ci_required else True

        if review_first_pass is None:
            # den == 0 means unreviewed_merged_prs > 0 (handled by c1)
            c3 = False if c1 is False else (None, metric_missing.get("review_first_pass", set()))
        else:
            c3 = (review_first_pass["num"] == review_first_pass["den"])

        if fix_rounds is None:
            c4 = False if c1 is False else (None, metric_missing.get("fix_rounds", set()))
        else:
            c4 = (fix_rounds == 0)

        if approved_head_stale is None:
            c5 = False if c1 is False else (None, metric_missing.get("approved_head_stale", set()))
        else:
            c5 = (approved_head_stale == 0)

        if ci_first_green is None:
            if not ci_required and metric_missing.get("ci_first_green") == {"no_ci_runs"}:
                # No CI run on any merged PR and CI is not required: nothing to fail.
                c6 = True
            else:
                c6 = False if c2 is False else (None, metric_missing.get("ci_first_green", set()))
        else:
            c6 = (ci_first_green["num"] == ci_first_green["den"])

        if rework_prs is None:
            c7 = (None, metric_missing.get("rework_prs", set()))
        else:
            c7 = (rework_prs == 0)

        all_conds = [c1, c2, c3, c4, c5, c6, c7]
        if any(c is False for c in all_conds):
            clean = False
        elif all(c is True for c in all_conds):
            clean = True
        else:
            clean = None
            for c in all_conds:
                if isinstance(c, tuple) and c[0] is None and c[1]:
                    clean_reasons.update(c[1])

    # 6. Usage and Counters
    counters_missing = []
    if input_data is None or "counters" not in input_data:
        counters = None
        counters_missing.append(("counters", "input_missing"))
    elif input_data["counters"] is None:
        counters = None
        counters_missing.append(("counters", "input_null"))
    else:
        counters = input_data["counters"]
        for k, v in counters.items():
            if v is None:
                counters_missing.append((f"counters.{k}", "input_null"))

    usage_missing = []
    if input_data is None or "usage" not in input_data:
        usage = None
        usage_missing.append(("usage", "input_missing"))
    elif input_data["usage"] is None:
        usage = None
        usage_missing.append(("usage", "input_null"))
    else:
        raw_usage = input_data["usage"]
        # weighted keys appear in every report only when some item carries the key
        has_weighted = any("weighted_micro_units" in item for item in raw_usage)
        groups = {}
        role_groups = {}
        for item in raw_usage:
            k = (item["provider"], item["model"])
            groups.setdefault(k, []).append(item)
            rk = (item["role"], item["provider"], item["model"])
            role_groups.setdefault(rk, []).append(item)

        totals, total_missing = _aggregate_usage(raw_usage, has_weighted)
        for t_k, reason in total_missing:
            usage_missing.append((f"usage.totals.{t_k}", reason))

        by_model = []
        for (provider, model) in sorted(groups.keys()):
            items = groups[(provider, model)]
            entry = {"model": model, "provider": provider}
            values, missing = _aggregate_usage(items, has_weighted)
            entry.update(values)
            for t_k, reason in missing:
                usage_missing.append((f"usage.by_model[{provider},{model}].{t_k}", reason))
            by_model.append(entry)

        # Same null rules as by_model, but no missing items: by_model and totals already report them.
        by_role_model = []
        for (role, provider, model) in sorted(role_groups.keys()):
            entry = {"model": model, "provider": provider, "role": role}
            values, _ = _aggregate_usage(role_groups[(role, provider, model)], has_weighted)
            entry.update(values)
            by_role_model.append(entry)

        usage = {"by_model": by_model, "by_role_model": by_role_model, "totals": totals}

    # 7. Missing items list
    missing_items = []
    # PR fields
    for p in pr_results:
        pr_id = p["pr"]
        m_map = pr_missing_map.get(pr_id, {})
        for field in [
            "verdicts",
            "first_review_pass",
            "fix_rounds",
            "re_reviews",
            "approved_head_stale",
            "ci_first_green",
            "rework",
        ]:
            if p[field] is None and field in m_map:
                missing_items.append({"field": f"prs[{pr_id}].{field}", "reason": m_map[field]})

    # Metrics fields (exclude cycle_basis)
    for m_field, val in metrics.items():
        if m_field == "cycle_basis":
            continue
        if val is None and m_field in metric_missing:
            for r_reason in metric_missing[m_field]:
                missing_items.append({"field": f"metrics.{m_field}", "reason": r_reason})

    # Usage missing
    for f_name, r_reason in usage_missing:
        missing_items.append({"field": f_name, "reason": r_reason})

    # Counters missing
    for f_name, r_reason in counters_missing:
        missing_items.append({"field": f_name, "reason": r_reason})

    # Clean missing
    if clean is None:
        for r_reason in clean_reasons:
            missing_items.append({"field": "clean", "reason": r_reason})

    # Deduplicate and sort missing
    seen = set()
    deduped_missing = []
    for m in missing_items:
        key = (m["field"], m["reason"])
        if key not in seen:
            seen.add(key)
            deduped_missing.append(m)

    deduped_missing.sort(key=lambda x: (x["field"], x["reason"]))

    return {
        "clean": clean,
        "config_digest": config_digest,
        "counters": counters,
        "excluded_prs": excluded_prs,
        "kind": "taskquality-report",
        "metrics": metrics,
        "missing": deduped_missing,
        "prs": pr_results,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "ticket": ticket,
        "tool_version": TOOL_VERSION,
        "usage": usage,
        "warnings": score_warnings(
            snapshot,
            unrecognized_count,
            config,
            metrics["unparsed_verdict_lines"],
        ),
    }
