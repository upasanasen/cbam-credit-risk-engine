import pytest

from cbam_engine import (Assumptions, Borrower, Shipment, TFAssumptions, assess_shipment,
                         load_shipments, run_shipments, tf_kpis, climate_multiplier)
from cbam_engine.reference import cbam_factor, phase_in
from cbam_engine.trade_finance import default_markup, default_value


def ship(**kw) -> Shipment:
    base = dict(shipment_id="S1", borrower_id="B1", counterparty="EU Buyer", instrument="receivables_discounting",
                product="steel", route="bf_bof_india", country="IN", tonnes=10000, invoice_value_eur=5.5e6,
                import_year=2028, declared_intensity=2.55, verification_status="verified",
                contract_clause="indexed_certificate", advance_rate=0.8)
    base.update(kw)
    return Shipment(**base)


def test_cbam_factor_is_share_remaining():
    assert cbam_factor(2026) == pytest.approx(0.975)
    assert cbam_factor(2030) == pytest.approx(0.515)
    assert cbam_factor(2034) == pytest.approx(0.0)
    assert cbam_factor(2028) + phase_in(2028) == pytest.approx(1.0)


def test_default_markups():
    assert default_markup("steel", 2026) == 0.10
    assert default_markup("steel", 2027) == 0.20
    assert default_markup("cement", 2030) == 0.30
    assert default_markup("urea", 2028) == 0.01
    assert default_markup("ammonia", 2026) == 0.01


def test_published_default_used_for_india_steel():
    v, prov = default_value("steel", "IN", "bf_bof_india")
    assert v == pytest.approx(4.270)
    assert prov.startswith("published")
    v2, prov2 = default_value("cement", "IN", "clinker")
    assert prov2.startswith("estimated")


def test_unverified_uses_default_with_markup():
    r = assess_shipment(ship(verification_status="none"), TFAssumptions())
    assert r.intensity_declared_used == pytest.approx(4.270 * 1.30)
    assert r.exposure_declared == pytest.approx(r.exposure_default)


def test_verification_reduces_dilution():
    a = TFAssumptions()
    unverified = assess_shipment(ship(verification_status="none"), a)
    verified = assess_shipment(ship(), a)
    assert verified.dilution < unverified.dilution
    assert verified.borrowing_base_carbon > unverified.borrowing_base_carbon


def test_pre_verified_buffer():
    a = TFAssumptions(pre_verified_buffer=0.10)
    r = assess_shipment(ship(verification_status="pre_verified"), a)
    assert r.intensity_declared_used == pytest.approx(2.55 * 1.10)


def test_clause_share_scales_dilution():
    a = TFAssumptions()
    full = assess_shipment(ship(contract_clause="indexed_certificate"), a).dilution
    fixed = assess_shipment(ship(contract_clause="fixed_price"), a).dilution
    assert fixed == pytest.approx(full * 0.30)


def test_borrowing_base_never_negative_and_bounded():
    r = assess_shipment(ship(verification_status="none", invoice_value_eur=1e5), TFAssumptions())
    assert r.eligible_receivable >= 0
    assert r.borrowing_base_carbon <= r.borrowing_base_plain


def test_import_loan_reserve_and_lc_flag():
    a = TFAssumptions(reserve_cover=1.25)
    imp = assess_shipment(ship(instrument="import_loan"), a)
    assert imp.funded_reserve == pytest.approx(1.25 * imp.exposure_declared)
    assert imp.borrowing_base_plain == 0.0
    lc = assess_shipment(ship(instrument="letter_of_credit", lc_requires_emissions_doc=True), a)
    assert lc.lc_discrepancy_risk.startswith("High")


def test_stress_at_least_base():
    r = assess_shipment(ship(), TFAssumptions(stress_price=100.0))
    assert r.exposure_stress >= r.exposure_declared


def test_sample_ledger_runs():
    sh, errs = load_shipments("sample_data/shipments_sample.csv")
    assert not errs and len(sh) == 12
    k = tf_kpis(run_shipments(sh, TFAssumptions()))
    assert k["borrowing_base_carbon"] < k["borrowing_base_plain"]
    assert k["exposure_default"] >= k["exposure_declared"]
    assert k["value_of_verification"] > 0


def test_climate_multiplier():
    b = Borrower(borrower_id="B", name="n", country="IN", product="steel", route="bf_bof_india",
                 eu_export_tonnes=100000, revenue_eur=60e6, ebitda_eur=10e6, interest_expense_eur=3e6,
                 total_debt_eur=40e6, ead_eur=20e6, pd_baseline=0.02, lgd_baseline=0.45,
                 collateral_value_eur=15e6, pass_through_rate=0.0)
    cm = climate_multiplier(b, Assumptions(), 2030, alpha=1.0, cap=3.0)
    assert 1.0 < cm.multiplier <= 3.0
    assert cm.provision_with_multiplier == pytest.approx(cm.ecl_base * cm.multiplier)
    assert cm.collateral_top_up == pytest.approx(max(0, 20e6 * cm.multiplier - 15e6))
    b0 = Borrower(**{**b.__dict__, "eu_export_tonnes": 0})
    assert climate_multiplier(b0, Assumptions(), 2030).multiplier == 1.0
