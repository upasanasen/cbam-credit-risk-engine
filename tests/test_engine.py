import math

import pytest

from cbam_engine import (Assumptions, Borrower, assess_borrower, cost_path, year_cost,
                         evaluate_all_levers, load_loanbook, run_portfolio, portfolio_kpis,
                         scenario_comparison)
from cbam_engine.reference import phase_in, PHASE_IN, PRODUCTS, PRICE_SCENARIOS


def make(**kw) -> Borrower:
    base = dict(borrower_id="T1", name="Test Steel", country="IN", product="steel",
                route="bf_bof_india", eu_export_tonnes=100000, revenue_eur=100e6, ebitda_eur=15e6,
                interest_expense_eur=4e6, total_debt_eur=50e6, ead_eur=20e6, pd_baseline=0.02,
                lgd_baseline=0.45, pass_through_rate=0.0)
    base.update(kw)
    return Borrower(**base)


def test_phase_in_schedule():
    assert phase_in(2025) == 0.0
    assert phase_in(2026) == 0.025
    assert phase_in(2034) == 1.0
    assert phase_in(2040) == 1.0
    assert list(PHASE_IN.values()) == sorted(PHASE_IN.values())


def test_certificate_formula_2034_full_phase_in():
    b = make()
    a = Assumptions(price_scenario="base")
    yc = year_cost(b, a, 2034)
    e = b.direct_intensity  # steel: direct only
    assert yc.embedded_intensity == pytest.approx(e)
    assert yc.benchmark_free == pytest.approx(0.0)
    assert yc.chargeable_intensity == pytest.approx(e)
    expected = e * PRICE_SCENARIOS["base"].path[2034] * b.eu_export_tonnes
    assert yc.gross_cost == pytest.approx(expected)


def test_benchmark_shields_in_2026():
    b = make(route="scrap_eaf")  # 0.30 direct vs 1.288 benchmark
    a = Assumptions()
    yc = year_cost(b, a, 2026)
    assert yc.chargeable_intensity == 0.0
    assert yc.gross_cost == 0.0


def test_indirect_scope_follows_annex_ii():
    a = Assumptions()
    steel = make()
    cement = make(product="cement", route="opc")
    assert year_cost(steel, a, 2030).embedded_intensity == pytest.approx(steel.direct_intensity)
    assert year_cost(cement, a, 2030).embedded_intensity == pytest.approx(
        cement.direct_intensity + cement.indirect_intensity)


def test_pass_through_reduces_borne_cost():
    a = Assumptions()
    full = year_cost(make(pass_through_rate=0.0), a, 2034).borne_cost
    half = year_cost(make(pass_through_rate=0.5), a, 2034).borne_cost
    none = year_cost(make(pass_through_rate=1.0), a, 2034).borne_cost
    assert half == pytest.approx(full / 2)
    assert none == 0.0


def test_domestic_carbon_price_credit():
    a = Assumptions()
    no_credit = year_cost(make(), a, 2034).gross_cost
    credit = year_cost(make(domestic_carbon_price_override=20.0), a, 2034).gross_cost
    price = PRICE_SCENARIOS["base"].path[2034]
    assert credit == pytest.approx(no_credit * (1 - 20.0 / price))
    # credit cannot exceed the certificate price
    assert year_cost(make(domestic_carbon_price_override=500.0), a, 2034).gross_cost == 0.0


def test_pd_monotone_and_bounded():
    a = Assumptions()
    r = assess_borrower(make(), a)
    pds = [c.pd_adj for c in r.credit]
    assert all(p >= make().pd_baseline for p in pds)
    assert all(0 < p < 1 for p in pds)
    assert pds[-1] >= pds[0]


def test_no_exports_no_impact():
    r = assess_borrower(make(eu_export_tonnes=0), Assumptions())
    assert all(c.pd_adj == pytest.approx(c.pd_baseline) for c in r.credit)
    assert r.lifetime_ecl_delta == pytest.approx(0.0, abs=1e-6)
    assert r.risk_flag == "None"


def test_stage2_trigger_on_severe_shock():
    b = make(ebitda_eur=5e6, interest_expense_eur=4e6)  # tiny EBITDA, big exposure
    r = assess_borrower(b, Assumptions())
    assert r.worst_stage == 2
    assert r.risk_flag == "High"


def test_scenarios_ordered():
    a = Assumptions()
    costs = {s: cost_path(make(), Assumptions(price_scenario=s))[-1].gross_cost for s in PRICE_SCENARIOS}
    assert costs["low"] < costs["base"] < costs["high"]


def test_levers_reduce_pd_and_size_loan():
    b = make()
    res = evaluate_all_levers(b, Assumptions())
    assert res
    for lr in res:
        assert lr.pd_2034_after <= lr.pd_2034_before
        assert lr.loan_size_eur == pytest.approx(lr.lever.capex_eur_per_t_capacity * b.eu_export_tonnes)
        assert lr.cumulative_avoided_cost >= 0


def test_sample_loanbook_loads_and_runs():
    bs, errs = load_loanbook("sample_data/loanbook_sample.csv")
    assert not errs
    assert len(bs) == 17
    a = Assumptions()
    res = run_portfolio(bs, a)
    k = portfolio_kpis(res, a)
    assert k["total_ead"] == pytest.approx(sum(b.ead_eur for b in bs))
    assert k["ecl_12m_delta_2034"] > 0
    sc = scenario_comparison(bs, a)
    assert list(sc.scenario) == ["Low", "Base", "High"]
    assert sc.ecl_12m_delta_2034.is_monotonic_increasing


def test_validation_rejects_bad_rows():
    b = make(product="widgets")
    assert b.validate()
    b2 = make(pd_baseline=1.5)
    assert b2.validate()
