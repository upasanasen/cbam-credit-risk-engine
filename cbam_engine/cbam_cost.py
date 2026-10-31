"""CBAM certificate cost at borrower level.

Obligation per tonne of product (Reg. 2023/956 Art. 22 and Art. 31):

    certificates_per_t = max(0, E_embedded - B * (1 - CF_y)) - carbon_price_paid / P_y

where
    E_embedded  = direct intensity (+ indirect, where in scope)
    B           = EU free-allocation benchmark for the product
    CF_y        = CBAM factor in year y (share of free allocation withdrawn)
    P_y         = CBAM certificate price (quarterly average EUA price)

The deduction for a carbon price effectively paid in the country of origin
(Art. 9) is applied as a per-tonne-CO2 credit against the certificate price.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .models import Borrower, Assumptions
from .reference import PRODUCTS, PRICE_SCENARIOS, cbam_factor


@dataclass
class YearCost:
    year: int
    cbam_factor: float
    eua_price: float
    embedded_intensity: float          # tCO2 per t in CBAM scope
    benchmark_free: float              # B * (1 - CF)
    chargeable_intensity: float        # tCO2 per t subject to certificates
    certificates_per_t: float          # after domestic carbon price credit
    cost_per_t: float                  # EUR per tonne of product
    gross_cost: float                  # EUR, before pass-through
    borne_cost: float                  # EUR, borne by exporter after pass-through
    cost_to_revenue: float             # borne cost / revenue
    cost_to_ebitda: float              # borne cost / baseline EBITDA
    export_tonnes: float               # tonnes after any demand response


def embedded_intensity(b: Borrower, a: Assumptions) -> float:
    p = PRODUCTS[b.product]
    e = b.direct_intensity
    if a.include_indirect and p.indirect_in_scope:
        e += b.indirect_intensity
    return e


def year_cost(b: Borrower, a: Assumptions, year: int) -> YearCost:
    p = PRODUCTS[b.product]
    cf = cbam_factor(year)
    price = PRICE_SCENARIOS[a.price_scenario].path.get(year, 0.0)
    e = embedded_intensity(b, a)
    free = p.benchmark_tco2_per_t * (1.0 - cf)
    chargeable = max(0.0, e - free)
    # domestic carbon price credited per tCO2, cannot exceed the EUA price
    credit_per_tco2 = min(b.domestic_carbon_price, price) if price > 0 else 0.0
    certs = chargeable * max(0.0, 1.0 - (credit_per_tco2 / price)) if price > 0 else 0.0
    cost_per_t = certs * price
    pass_through = b.pass_through_rate if b.pass_through_rate is not None else a.default_pass_through
    pass_through = min(max(pass_through, 0.0), 1.0)

    # optional demand response: higher delivered price in EU reduces volumes
    tonnes = b.eu_export_tonnes
    if a.demand_elasticity > 0 and b.revenue_eur > 0 and tonnes > 0:
        unit_price = b.revenue_eur / max(tonnes, 1e-9)
        price_uplift_pct = (cost_per_t * pass_through) / unit_price * 100.0
        tonnes = tonnes * max(0.0, 1.0 - a.demand_elasticity * price_uplift_pct / 100.0)

    gross = cost_per_t * tonnes
    borne = gross * (1.0 - pass_through)
    rev = b.revenue_eur if b.revenue_eur > 0 else 1e-9
    ebitda = b.ebitda_eur if b.ebitda_eur > 0 else 1e-9
    return YearCost(
        year=year, cbam_factor=cf, eua_price=price, embedded_intensity=e,
        benchmark_free=free, chargeable_intensity=chargeable, certificates_per_t=certs,
        cost_per_t=cost_per_t, gross_cost=gross, borne_cost=borne,
        cost_to_revenue=borne / rev, cost_to_ebitda=borne / ebitda, export_tonnes=tonnes,
    )


def cost_path(b: Borrower, a: Assumptions) -> List[YearCost]:
    return [year_cost(b, a, y) for y in range(a.horizon_start, a.horizon_end + 1)]


def cost_summary(path: List[YearCost]) -> Dict[str, float]:
    if not path:
        return {}
    peak = max(path, key=lambda y: y.borne_cost)
    return {
        "borne_cost_2026": next((y.borne_cost for y in path if y.year == 2026), 0.0),
        "borne_cost_2030": next((y.borne_cost for y in path if y.year == 2030), 0.0),
        "borne_cost_2034": next((y.borne_cost for y in path if y.year == 2034), 0.0),
        "peak_cost_to_ebitda": peak.cost_to_ebitda,
        "peak_year": peak.year,
        "cumulative_borne_cost": sum(y.borne_cost for y in path),
        "cumulative_gross_cost": sum(y.gross_cost for y in path),
    }
