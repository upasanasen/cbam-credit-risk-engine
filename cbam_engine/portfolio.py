"""Portfolio aggregation and loan-book I/O."""
from __future__ import annotations

import io
from dataclasses import fields
from typing import Dict, List, Tuple

import pandas as pd

from .models import Borrower, Assumptions
from .credit import assess_borrower, BorrowerResult
from .reference import PRICE_SCENARIOS

REQUIRED_COLUMNS = [
    "borrower_id", "name", "country", "product", "route", "eu_export_tonnes",
    "revenue_eur", "ebitda_eur", "interest_expense_eur", "total_debt_eur",
    "ead_eur", "pd_baseline", "lgd_baseline",
]
OPTIONAL_COLUMNS = [
    "collateral_value_eur", "maturity_years", "direct_intensity_override",
    "indirect_intensity_override", "pass_through_rate",
    "domestic_carbon_price_override", "rating_internal", "sector_note",
]


def load_loanbook(source) -> Tuple[List[Borrower], List[str]]:
    """Read a CSV/XLSX path or file-like object into Borrower records."""
    if hasattr(source, "read") or str(source).lower().endswith(".csv"):
        df = pd.read_csv(source)
    else:
        df = pd.read_excel(source)
    return dataframe_to_borrowers(df)


def dataframe_to_borrowers(df: pd.DataFrame) -> Tuple[List[Borrower], List[str]]:
    errors: List[str] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return [], [f"Missing required columns: {', '.join(missing)}"]
    valid_fields = {f.name for f in fields(Borrower)}
    borrowers: List[Borrower] = []
    for _, row in df.iterrows():
        kwargs = {}
        for k, v in row.items():
            if k not in valid_fields:
                continue
            if pd.isna(v):
                continue
            kwargs[k] = v
        for k in ("borrower_id", "name", "country", "product", "route", "rating_internal", "sector_note"):
            if k in kwargs:
                kwargs[k] = str(kwargs[k])
        try:
            b = Borrower(**kwargs)
        except TypeError as exc:
            errors.append(f"Row {row.get('borrower_id', '?')}: {exc}")
            continue
        errs = b.validate()
        if errs:
            errors.extend(errs)
        else:
            borrowers.append(b)
    return borrowers, errors


def run_portfolio(borrowers: List[Borrower], a: Assumptions) -> List[BorrowerResult]:
    return [assess_borrower(b, a) for b in borrowers]


def results_table(results: List[BorrowerResult]) -> pd.DataFrame:
    return pd.DataFrame([r.summary() for r in results])


def year_table(results: List[BorrowerResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        for yc, cc in zip(r.costs, r.credit):
            rows.append({
                "borrower_id": r.borrower.borrower_id, "name": r.borrower.name,
                "sector": r.borrower.product, "country": r.borrower.country,
                "year": yc.year, "cbam_factor": yc.cbam_factor, "eua_price": yc.eua_price,
                "gross_cost": yc.gross_cost, "borne_cost": yc.borne_cost,
                "cost_to_ebitda": yc.cost_to_ebitda, "pd_adj": cc.pd_adj,
                "lgd_adj": cc.lgd_adj, "ecl_adj": cc.ecl_adj, "ecl_delta": cc.ecl_delta,
                "stage": cc.stage, "ead_eur": r.borrower.ead_eur,
            })
    return pd.DataFrame(rows)


def portfolio_kpis(results: List[BorrowerResult], a: Assumptions) -> Dict[str, float]:
    if not results:
        return {}
    tbl = results_table(results)
    yt = year_table(results)
    ead = tbl["ead_eur"].sum()
    y34 = yt[yt.year == a.horizon_end]
    y30 = yt[yt.year == 2030] if 2030 in yt.year.values else y34
    stage2_ead = y34.loc[y34.stage == 2, "ead_eur"].sum()
    return {
        "total_ead": ead,
        "borrowers": len(results),
        "ead_cbam_exposed": tbl.loc[tbl.eu_export_tonnes > 0, "ead_eur"].sum(),
        "gross_cbam_cost_2030": y30["gross_cost"].sum(),
        "gross_cbam_cost_2034": y34["gross_cost"].sum(),
        "borne_cbam_cost_2034": y34["borne_cost"].sum(),
        "ecl_12m_baseline": y34["ecl_adj"].sum() - y34["ecl_delta"].sum(),
        "ecl_12m_2034": y34["ecl_adj"].sum(),
        "ecl_12m_delta_2034": y34["ecl_delta"].sum(),
        "lifetime_ecl_delta": tbl["lifetime_ecl_delta"].sum(),
        "stage2_ead_2034": stage2_ead,
        "stage2_share": stage2_ead / ead if ead else 0.0,
        "high_risk_ead": tbl.loc[tbl.risk_flag == "High", "ead_eur"].sum(),
        "wavg_pd_baseline": (tbl.pd_baseline * tbl.ead_eur).sum() / ead if ead else 0.0,
        "wavg_pd_2034": (tbl.pd_2034 * tbl.ead_eur).sum() / ead if ead else 0.0,
        "capital_at_risk": tbl["capital_at_risk"].sum(),
    }


def sector_table(results: List[BorrowerResult], a: Assumptions) -> pd.DataFrame:
    yt = year_table(results)
    y = yt[yt.year == a.horizon_end]
    g = y.groupby("sector").agg(
        borrowers=("borrower_id", "count"), ead_eur=("ead_eur", "sum"),
        gross_cost_2034=("gross_cost", "sum"), borne_cost_2034=("borne_cost", "sum"),
        ecl_delta_2034=("ecl_delta", "sum"),
        stage2_ead=("ead_eur", lambda s: s[y.loc[s.index, "stage"] == 2].sum()),
    ).reset_index()
    g["ecl_delta_bps_of_ead"] = g.ecl_delta_2034 / g.ead_eur * 1e4
    return g.sort_values("ecl_delta_2034", ascending=False)


def scenario_comparison(borrowers: List[Borrower], base: Assumptions) -> pd.DataFrame:
    rows = []
    for code in PRICE_SCENARIOS:
        a = Assumptions(**{**base.to_dict(), "price_scenario": code})
        res = run_portfolio(borrowers, a)
        k = portfolio_kpis(res, a)
        rows.append({"scenario": PRICE_SCENARIOS[code].name, **k})
    return pd.DataFrame(rows)


def template_csv() -> str:
    cols = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    buf = io.StringIO()
    pd.DataFrame(columns=cols).to_csv(buf, index=False)
    return buf.getvalue()
