from app.compare import compare_runs


def run(key, mode, seconds, created_at, output_hash="h", instruction="do it"):
    return {
        "id": f"{key}-{mode}-{created_at}",
        "key": key,
        "mode": mode,
        "seconds": seconds,
        "created_at": created_at,
        "output_hash": output_hash,
        "instruction": instruction,
    }


def base_runs():
    return [
        run("A", "iwr", 1.0, "2026-01-01T00:00:00"),
        run("A", "baseline", 3.0, "2026-01-01T00:00:01"),
        run("B", "iwr", 2.0, "2026-01-01T00:00:02"),
    ]


def rows_by_key(result):
    return {r["key"]: r for r in result["rows"]}


def test_compare_pairs_and_totals():
    result = compare_runs(base_runs())
    rows = rows_by_key(result)
    assert rows["A"]["speedup"] == 3.0
    assert rows["A"]["identical"] is True
    assert rows["B"]["baseline_seconds"] is None
    assert rows["B"]["speedup"] is None
    assert rows["B"]["identical"] is None
    assert result["totals"] == {"iwr": 1.0, "baseline": 3.0, "speedup": 3.0}


def test_compare_uses_latest_run_per_mode():
    runs = base_runs() + [run("A", "iwr", 0.5, "2026-01-02T00:00:00")]
    rows = rows_by_key(compare_runs(runs))
    assert rows["A"]["iwr_seconds"] == 0.5
    assert rows["A"]["speedup"] == 6.0


def test_compare_no_pairs_has_no_speedup():
    result = compare_runs([run("B", "iwr", 2.0, "2026-01-01T00:00:00")])
    assert result["totals"] == {"iwr": 0.0, "baseline": 0.0, "speedup": None}
