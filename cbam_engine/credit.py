"""Translate CBAM cost into credit metrics: PD, LGD, ECL, IFRS 9 staging, capital.

Method (documented in docs/methodology.md):

1. Earnings shock.  EBITDA_y = EBITDA_0 - borne CBAM cost_y.  ICR_y and
   Debt/EBITDA_y follow.
2. PD adjustment.  A logit shift proportional to the earnings shock:
       logit(PD_y) = logit(PD_0) + k * (borne cost_y / EBITDA_0)
                     + penalty if ICR_y < floor
   k is the pd_elasticity assumption.  The functional form mirrors the
   stressed-PD approach of supervisory climate stress tests (ECB 2022, BoE CBES),
   where a sectoral cost shock is mapped onto PD via a monotone link function.
   Calibrate k to the institution's own rating-migration history.
3. LGD adjustment.  Collateral tied to carbon-intensive assets loses value as the
   cost of carbon rises (stranded-asset channel, see BRSA 2024 "climate multiplier"
   proposal):  LGD_y = min(cap, LGD_0 + s * borne cost_y / EBITDA_0).
4. ECL_y = PD_y * LGD_y * EAD (12-month) and lifetime ECL as the discounted sum
   over the remaining maturity.
5. IFRS 9 stage 2 is triggered when PD_y / PD_0 exceeds the SICR ratio AND the
   absolute PD increase exceeds the SICR threshold.
6. Capital at risk = EAD * RW * capital ratio, for context on exposure size.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Dict, List

from .models import Borrower, Assumptions
from .cbam_cost import YearCost, cost_path
from .reference import pd_to_rating, rating_index


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _inv_logit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class YearCredit:
    year: int
    borne_cost: float
    ebitda_adj: float
    icr_baseline: float
    icr_adj: float
    leverage_baseline: float
    leverage_adj: float
    pd_baseline: float
    pd_adj: float
    pd_uplift_ratio: float
    rating_baseline: str
    rating_adj: str
    notches_down: int
    lgd_baseline: float
    lgd_adj: float
    ecl_baseline: float
    ecl_adj: float
    ecl_delta: float
    stage: int


def year_credit(b: Borrower, a: Assumptions, yc: YearCost) -> YearCredit:
    ebitda0 = b.ebitda_eur
    ebitda_adj = ebitda0 - yc.borne_cost
    interest = b.interest_expense_eur if b.interest_expense_eur > 0 else 1e-9
    icr0 = ebitda0 / interest
    icr1 = ebitda_adj / interest
    lev0 = b.total_debt_eur / ebitda0 if ebitda0 > 0 else float("inf")
    lev1 = b.total_debt_eur / ebitda_adj if ebitda_adj > 0 else float("inf")

    shock = yc.borne_cost / ebitda0 if ebitda0 > 0 else (1.0 if yc.borne_cost > 0 else 0.0)
    shock = max(0.0, shock)
    shift = a.pd_elasticity * shock
    if icr1 < a.icr_floor and icr0 >= a.icr_floor:
        shift += a.icr_penalty_logit
    pd1 = b.pd_baseline if shift == 0.0 else max(_inv_logit(_logit(b.pd_baseline) + shift), b.pd_baseline)

    lgd1 = min(a.lgd_cap, b.lgd_baseline + a.lgd_sensitivity * shock)

    ecl0 = b.pd_baseline * b.lgd_baseline * b.ead_eur
    ecl1 = pd1 * lgd1 * b.ead_eur
    ratio = pd1 / b.pd_baseline
    stage = 2 if (ratio >= a.sicr_pd_ratio and (pd1 - b.pd_baseline) >= a.sicr_pd_abs) else 1
    if ebitda_adj <= 0:
        stage = max(stage, 2)

    r0, r1 = pd_to_rating(b.pd_baseline), pd_to_rating(pd1)
    return YearCredit(
        year=yc.year, borne_cost=yc.borne_cost, ebitda_adj=ebitda_adj,
        icr_baseline=icr0, icr_adj=icr1, leverage_baseline=lev0, leverage_adj=lev1,
        pd_baseline=b.pd_baseline, pd_adj=pd1, pd_uplift_ratio=ratio,
        rating_baseline=r0, rating_adj=r1, notches_down=rating_index(r1) - rating_index(r0),
        lgd_baseline=b.lgd_baseline, lgd_adj=lgd1,
        ecl_baseline=ecl0, ecl_adj=ecl1, ecl_delta=ecl1 - ecl0, stage=stage,
    )


@dataclass
class BorrowerResult:
    borrower: Borrower
    costs: List[YearCost]
    credit: List[YearCredit]
    lifetime_ecl_baseline: float
    lifetime_ecl_adj: float
    lifetime_ecl_delta: float
    capital_at_risk: float
    worst_year: int
    worst_pd_adj: float
    worst_stage: int
    worst_notches: int
    risk_flag: str

    def summary(self) -> Dict:
        c34 = next((c for c in self.credit if c.year == 2034), self.credit[-1])
        c30 = next((c for c in self.credit if c.year == 2030), self.credit[-1])
        b = self.borrower
        return {
            "borrower_id": b.borrower_id, "name": b.name, "country": b.country,
            "sector": b.product, "route": b.route, "ead_eur": b.ead_eur,
            "eu_export_tonnes": b.eu_export_tonnes,
            "embedded_intensity": self.costs[0].embedded_intensity if self.costs else 0.0,
            "borne_cost_2030": c30.borne_cost, "borne_cost_2034": c34.borne_cost,
            "cost_to_ebitda_2030": c30.borne_cost / b.ebitda_eur if b.ebitda_eur else float("nan"),
            "cost_to_ebitda_2034": c34.borne_cost / b.ebitda_eur if b.ebitda_eur else float("nan"),
            "icr_2034": c34.icr_adj, "pd_baseline": b.pd_baseline, "pd_2030": c30.pd_adj,
            "pd_2034": c34.pd_adj, "rating_baseline": c34.rating_baseline,
            "rating_2034": c34.rating_adj, "notches_down_2034": c34.notches_down,
            "lgd_2034": c34.lgd_adj, "stage_2034": c34.stage,
            "ecl_12m_baseline": c34.ecl_baseline, "ecl_12m_2034": c34.ecl_adj,
            "lifetime_ecl_delta": self.lifetime_ecl_delta,
            "capital_at_risk": self.capital_at_risk, "risk_flag": self.risk_flag,
        }


def _lifetime_ecl(b: Borrower, a: Assumptions, pds: List[float], lgds: List[float],
                  years: List[int]) -> float:
    """Discounted sum of marginal ECL over remaining maturity (survival-weighted)."""
    total, survival = 0.0, 1.0
    horizon = int(math.ceil(b.maturity_years))
    for i, (pd_v, lgd_v) in enumerate(zip(pds, lgds)):
        if i >= horizon:
            break
        marginal = survival * pd_v * lgd_v * b.ead_eur
        total += marginal / ((1 + a.discount_rate) ** (i + 1))
        survival *= (1 - pd_v)
    return total


def assess_borrower(b: Borrower, a: Assumptions) -> BorrowerResult:
    costs = cost_path(b, a)
    credit = [year_credit(b, a, yc) for yc in costs]
    years = [c.year for c in credit]
    lt0 = _lifetime_ecl(b, a, [b.pd_baseline] * len(credit), [b.lgd_baseline] * len(credit), years)
    lt1 = _lifetime_ecl(b, a, [c.pd_adj for c in credit], [c.lgd_adj for c in credit], years)
    worst = max(credit, key=lambda c: c.pd_adj)
    cap = b.ead_eur * a.risk_weight_pct / 100.0 * a.capital_ratio

    peak_shock = max((c.borne_cost / b.ebitda_eur for c in credit), default=0.0) if b.ebitda_eur > 0 else 1.0
    if peak_shock >= 0.50 or worst.stage == 2 and worst.notches_down >= 3:
        flag = "High"
    elif peak_shock >= 0.15 or worst.notches_down >= 1:
        flag = "Medium"
    elif peak_shock > 0.0:
        flag = "Low"
    else:
        flag = "None"

    return BorrowerResult(
        borrower=b, costs=costs, credit=credit,
        lifetime_ecl_baseline=lt0, lifetime_ecl_adj=lt1, lifetime_ecl_delta=lt1 - lt0,
        capital_at_risk=cap, worst_year=worst.year, worst_pd_adj=worst.pd_adj,
        worst_stage=worst.stage, worst_notches=worst.notches_down, risk_flag=flag,
    )
