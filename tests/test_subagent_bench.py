"""S5.3 runner with a fake provider (no network): pairing of option orders, scoring, resume, error handling, summary."""
import csv
import json

from iris_agent import subagent_bench as B


def _cases():
    return B.load_bench_cases()


def test_option_order_is_paired_across_models_and_variants():
    c = _cases()[0]
    assert B.order_for(c["id"], 3, c["menu"]) == B.order_for(c["id"], 3, c["menu"])
    orders = {tuple(o["id"] for o in B.order_for(c["id"], r, c["menu"])) for r in range(10)}
    assert len(orders) > 1
    s_g, u_g = B.render(c, "guided", B.order_for(c["id"], 0, c["menu"]))
    s_b, u_b = B.render(c, "bare", B.order_for(c["id"], 0, c["menu"]))
    assert u_g == u_b and "Guidance:" in s_g and "Guidance:" not in s_b


def test_run_score_resume_and_summary(tmp_path):
    cases = _cases()
    correct = {c["id"]: next(i for i, k in c["label_of"].items() if k == "correct") for c in cases}
    models = {"always-right": {"provider": "fake", "model": "f", "fake_answers": correct, "tier": "small"},
              "always-stop": {"provider": "fake", "model": "f", "fake_answer": "stop", "tier": "small"}}
    B.run("t", models, cases, ["guided", "bare"], 2, 2, False, out_root=tmp_path)
    n1 = len((tmp_path / "t" / "calls.jsonl").read_text().splitlines())
    B.run("t", models, cases, ["guided", "bare"], 2, 2, False, out_root=tmp_path)       # resume: nothing new
    assert len((tmp_path / "t" / "calls.jsonl").read_text().splitlines()) == n1 == 2 * len(cases) * 2 * 2
    d = B.summarize("t", models, cases, 2, "always-right", out_root=tmp_path)
    rows = {(r["model"], r["variant"], r["split"]): r for r in csv.DictReader(open(d / "S5_3_models.csv"))}
    assert float(rows[("always-right", "guided", "all")]["correct_rate"]) == 1.0
    st = rows[("always-stop", "bare", "all")]
    base = {r["model"]: r for r in csv.DictReader(open(d / "S5_3_baselines.csv")) if r["split"] == "all"}
    assert st["correct_rate"] == base["baseline:always-stop"]["correct_rate"] and float(st["harmful_rate"]) == 0.0
    assert st["mcnemar_vs_reference_b_c_p"].startswith("0/")
    pw = list(csv.DictReader(open(d / "S5_3_pairwise.csv")))
    p0 = next(r for r in pw if r["variant"] == "guided" and r["split"] == "all")
    assert p0["model_a"] == "always-right" and float(p0["diff_correct"]) > 0 and float(p0["mcnemar_p_holm"]) <= 1
    for f in ("S5_3_cases.csv", "S5_3_by_class.csv", "S5_3_calls.csv", "S5_3_summary.md"):
        assert (d / f).is_file()
    calls = [json.loads(x) for x in (tmp_path / "t" / "calls.jsonl").read_text().splitlines()]
    assert all(r["label"] in ("correct", "safe", "harmful") for r in calls)


def test_transport_errors_are_kept_apart_and_retried(tmp_path, monkeypatch):
    cases = _cases()[:2]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    models = {"no-key": {"provider": "openai", "model": "m", "tier": "small"}}
    B.run("e", models, cases, ["guided"], 1, 1, False, out_root=tmp_path)
    calls = [json.loads(x) for x in (tmp_path / "e" / "calls.jsonl").read_text().splitlines()]
    assert {r["label"] for r in calls} == {"error"}
    d = B.summarize("e", models, cases, 1, None, out_root=tmp_path)
    r = next(csv.DictReader(open(d / "S5_3_models.csv")))
    assert r["n_calls"] == "0" and r["transport_errors"] == "2"
    B.run("e", models, cases, ["guided"], 1, 1, True, out_root=tmp_path)          # --retry-errors tries again
    assert len((tmp_path / "e" / "calls.jsonl").read_text().splitlines()) == 4
