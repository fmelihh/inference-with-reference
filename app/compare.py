def _latest_by_key_mode(runs: list[dict]) -> dict[tuple[str, str], dict]:
    latest: dict[tuple[str, str], dict] = {}
    for run in runs:
        k = (run["key"], run["mode"])
        if k not in latest or run["created_at"] >= latest[k]["created_at"]:
            latest[k] = run
    return latest


def compare_runs(runs: list[dict]) -> dict:
    latest = _latest_by_key_mode(runs)
    keys = sorted({key for key, _ in latest})
    rows = []
    iwr_total = 0.0
    baseline_total = 0.0
    paired = False
    for key in keys:
        iwr = latest.get((key, "iwr"))
        base = latest.get((key, "baseline"))
        both = iwr is not None and base is not None
        newest = max((r for r in (iwr, base) if r), key=lambda r: r["created_at"])
        rows.append(
            {
                "key": key,
                "instruction": newest["instruction"],
                "iwr_seconds": iwr["seconds"] if iwr else None,
                "baseline_seconds": base["seconds"] if base else None,
                "speedup": base["seconds"] / iwr["seconds"] if both else None,
                "identical": iwr["output_hash"] == base["output_hash"] if both else None,
            }
        )
        if both:
            paired = True
            iwr_total += iwr["seconds"]
            baseline_total += base["seconds"]
    return {
        "rows": rows,
        "totals": {
            "iwr": iwr_total,
            "baseline": baseline_total,
            "speedup": baseline_total / iwr_total if paired else None,
        },
    }
