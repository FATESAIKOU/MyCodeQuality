"""Calculation of task quality metrics for a ticket."""

from taskquality.conventions import (
    detect_rework,
    extract_verdicts,
    heads_match,
    match_ticket_ref,
)
from taskquality.formats import (
    calculate_config_digest,
    parse_iso_utc,
    parse_pr_id,
)

TOOL_VERSION = "0.3.0"
SCHEMA_VERSION = 1

TOKEN_KEYS = [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
]


def score_ticket(snapshot: dict, input_data: dict | None, config: dict) -> dict:
    """Score a ticket snapshot against input and config according to §4."""
    ticket = snapshot["ticket"]
    config_digest = calculate_config_digest(config)

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
        verdicts_source, V = extract_verdicts(pr, input_prs_override, config)
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
            "pr": pr_id,
            "re_reviews": re_reviews,
            "rework": rework,
            "rework_source": rework_source,
            "state": state,
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
        metric_missing["review_first_pass"] = "no_merged_pr"
    elif len(candidate_merged) == 0:
        review_first_pass = None
        metric_missing["review_first_pass"] = "no_verdict"
    elif any(p["first_review_pass"] is None for p in candidate_merged):
        review_first_pass = None
        null_p = next(p for p in candidate_merged if p["first_review_pass"] is None)
        metric_missing["review_first_pass"] = pr_missing_map[null_p["pr"]]["first_review_pass"]
    else:
        num = sum(1 for p in candidate_merged if p["first_review_pass"] is True)
        den = len(candidate_merged)
        review_first_pass = {"num": num, "den": den}

    # fix_rounds
    if len(merged_prs) == 0:
        fix_rounds = None
        metric_missing["fix_rounds"] = "no_merged_pr"
    elif len(candidate_merged) == 0:
        fix_rounds = None
        metric_missing["fix_rounds"] = "no_verdict"
    elif any(p["fix_rounds"] is None for p in candidate_merged):
        fix_rounds = None
        null_p = next(p for p in candidate_merged if p["fix_rounds"] is None)
        metric_missing["fix_rounds"] = pr_missing_map[null_p["pr"]]["fix_rounds"]
    else:
        fix_rounds = sum(p["fix_rounds"] for p in candidate_merged)

    # re_reviews
    if len(merged_prs) == 0:
        re_reviews = None
        metric_missing["re_reviews"] = "no_merged_pr"
    elif len(candidate_merged) == 0:
        re_reviews = None
        metric_missing["re_reviews"] = "no_verdict"
    elif any(p["re_reviews"] is None for p in candidate_merged):
        re_reviews = None
        null_p = next(p for p in candidate_merged if p["re_reviews"] is None)
        metric_missing["re_reviews"] = pr_missing_map[null_p["pr"]]["re_reviews"]
    else:
        re_reviews = sum(p["re_reviews"] for p in candidate_merged)

    # approved_head_stale
    if len(merged_prs) == 0:
        approved_head_stale = None
        metric_missing["approved_head_stale"] = "no_merged_pr"
    elif len(candidate_merged) == 0:
        approved_head_stale = None
        metric_missing["approved_head_stale"] = "no_verdict"
    elif any(p["approved_head_stale"] is None for p in candidate_merged):
        approved_head_stale = None
        null_p = next(p for p in candidate_merged if p["approved_head_stale"] is None)
        metric_missing["approved_head_stale"] = pr_missing_map[null_p["pr"]]["approved_head_stale"]
    else:
        approved_head_stale = sum(1 for p in candidate_merged if p["approved_head_stale"] is True)

    # ci_first_green
    if any(p["ci_first_green"] is None and pr_missing_map[p["pr"]].get("ci_first_green") == "ci_incomplete" for p in merged_prs):
        ci_first_green = None
        metric_missing["ci_first_green"] = "ci_incomplete"
    else:
        evaluated_ci = [p for p in merged_prs if p["ci_first_green"] is not None]
        if len(evaluated_ci) == 0:
            ci_first_green = None
            metric_missing["ci_first_green"] = "no_merged_pr" if len(merged_prs) == 0 else "no_ci_runs"
        else:
            num = sum(1 for p in evaluated_ci if p["ci_first_green"] is True)
            den = len(evaluated_ci)
            ci_first_green = {"num": num, "den": den}

    # rework_prs
    if any(p["rework"] is None for p in pr_results):
        rework_prs = None
        metric_missing["rework_prs"] = "input_null"
    else:
        rework_prs = sum(1 for p in pr_results if p["rework"] is True)

    # cycle_seconds & cycle_basis
    if input_data and input_data.get("started_at"):
        cycle_basis = "input_started_at"
        start_ts = input_data["started_at"]
    elif ticket_prs_raw:
        cycle_basis = "first_pr_created"
        start_ts = min(p["created_at"] for p in ticket_prs_raw)
    else:
        cycle_basis = None
        start_ts = None

    if prs_open > 0:
        cycle_seconds = None
        metric_missing["cycle_seconds"] = "pr_open"
    elif prs_merged == 0:
        cycle_seconds = None
        metric_missing["cycle_seconds"] = "no_merged_pr"
    else:
        latest_merged_at = max(p["merged_at"] for p in merged_prs)
        dt_start = parse_iso_utc(start_ts)
        dt_end = parse_iso_utc(latest_merged_at)
        diff = int((dt_end - dt_start).total_seconds())
        if diff < 0:
            cycle_seconds = None
            metric_missing["cycle_seconds"] = "bad_interval"
        else:
            cycle_seconds = diff

    metrics = {
        "approved_head_stale": approved_head_stale,
        "ci_first_green": ci_first_green,
        "cycle_basis": cycle_basis,
        "cycle_seconds": cycle_seconds,
        "fix_rounds": fix_rounds,
        "prs_closed_unmerged": prs_closed_unmerged,
        "prs_merged": prs_merged,
        "prs_open": prs_open,
        "prs_without_ci": prs_without_ci,
        "re_reviews": re_reviews,
        "review_first_pass": review_first_pass,
        "rework_prs": rework_prs,
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
    clean_reasons = []
    if status != "complete":
        clean = None
        clean_reasons.append("pr_open" if status == "in_progress" else "no_merged_pr")
    else:
        # Conditions 1-7: True, False, or (None, reason)
        c1 = (unreviewed_merged_prs == 0)
        c2 = (prs_without_ci == 0)

        if review_first_pass is None:
            # den == 0 means unreviewed_merged_prs > 0 (handled by c1)
            c3 = False if c1 is False else (None, metric_missing.get("review_first_pass"))
        else:
            c3 = (review_first_pass["num"] == review_first_pass["den"])

        if fix_rounds is None:
            c4 = False if c1 is False else (None, metric_missing.get("fix_rounds"))
        else:
            c4 = (fix_rounds == 0)

        if approved_head_stale is None:
            c5 = False if c1 is False else (None, metric_missing.get("approved_head_stale"))
        else:
            c5 = (approved_head_stale == 0)

        if ci_first_green is None:
            c6 = False if c2 is False else (None, metric_missing.get("ci_first_green"))
        else:
            c6 = (ci_first_green["num"] == ci_first_green["den"])

        if rework_prs is None:
            c7 = (None, metric_missing.get("rework_prs"))
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
                    if c[1] not in clean_reasons:
                        clean_reasons.append(c[1])

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
        groups = {}
        for item in raw_usage:
            k = (item["provider"], item["model"])
            groups.setdefault(k, []).append(item)

        totals = {}
        for t_k in TOKEN_KEYS:
            has_null = any(item.get(t_k) is None and t_k in item for item in raw_usage)
            has_missing = any(t_k not in item for item in raw_usage)
            if has_null:
                totals[t_k] = None
                usage_missing.append((f"usage.totals.{t_k}", "input_null"))
            elif has_missing:
                totals[t_k] = None
                usage_missing.append((f"usage.totals.{t_k}", "input_missing"))
            else:
                totals[t_k] = sum(item[t_k] for item in raw_usage)

        by_model = []
        for (provider, model) in sorted(groups.keys()):
            items = groups[(provider, model)]
            entry = {"model": model, "provider": provider}
            for t_k in TOKEN_KEYS:
                has_null = any(it.get(t_k) is None and t_k in it for it in items)
                has_missing = any(t_k not in it for it in items)
                if has_null:
                    entry[t_k] = None
                    usage_missing.append((f"usage.by_model[{provider},{model}].{t_k}", "input_null"))
                elif has_missing:
                    entry[t_k] = None
                    usage_missing.append((f"usage.by_model[{provider},{model}].{t_k}", "input_missing"))
                else:
                    entry[t_k] = sum(it[t_k] for it in items)
            by_model.append(entry)

        usage = {"by_model": by_model, "totals": totals}

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
            missing_items.append({"field": f"metrics.{m_field}", "reason": metric_missing[m_field]})

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
        "warnings": [],
    }
