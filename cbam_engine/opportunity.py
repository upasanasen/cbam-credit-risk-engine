"""Decarbonisation finance: size the transition loan that removes the CBAM drag.

For each lever available to the borrower's product:
  * recompute the CBAM cost path with the post-lever intensity (from lead-time year)
  * avoided cost_y = gross cost_y (baseline) - gross cost_y (lever)
  * capex = capex_per_t * annual production capacity (approximated by EU export
    tonnes unless a capacity figure is supplied); opex delta applies to all tonnes
  * NPV at the engine discount rate over the horizon; simple payback; DSCR of the
    avoided-cost stream against an annuity on the capex
  * the post-lever credit metrics show the PD and ECL benefit to the lender
"""
from __future__ import annotations

from dataclasses import dataclass, replace, asdict
from typing import List, Optional

from .models import Borrower, Assumptions
from .cbam_cost import cost_path
from .credit import assess_borrower, BorrowerResult
from .reference import Lever, levers_for


@dataclass
class LeverResult:
    lever: Lever
    capex_eur: float
    annual_opex_delta_eur: float
    avoided_cost_by_year: List[float]
    net_benefit_by_year: List[float]
    cumulative_avoided_cost: float
    npv_eur: float
    simple_payback_years: Optional[float]
    annuity_eur: float
    min_dscr: float
    pd_2034_before: float
    pd_2034_after: float
    ecl_delta_before: float
    ecl_delta_after: float
    ecl_saving_for_lender: float
    loan_size_eur: float
    viability: str

    def summary(self) -> dict:
        return {
            "lever": self.lever.name, "lever_code": self.lever.code,
            "capex_eur": self.capex_eur, "annual_opex_delta_eur": self.annual_opex_delta_eur,
            "cumulative_avoided_cost": self.cumulative_avoided_cost, "npv_eur": self.npv_eur,
            "simple_payback_years": self.simple_payback_years, "min_dscr": self.min_dscr,
            "pd_2034_before": self.pd_2034_before, "pd_2034_after": self.pd_2034_after,
            "ecl_saving_for_lender": self.ecl_saving_for_lender,
            "loan_size_eur": self.loan_size_eur, "viability": self.viability,
            "source": self.lever.source,
        }


def _annuity(principal: float, rate: float, years: int) -> float:
    if years <= 0:
        return principal
    if rate == 0:
        return principal / years
    return principal * rate / (1 - (1 + rate) ** (-years))


def evaluate_lever(b: Borrower, a: Assumptions, lever: Lever,
                   capacity_tonnes: Optional[float] = None,
                   loan_tenor_years: int = 8, loan_rate: float = 0.09) -> LeverResult:
    base = assess_borrower(b, a)
    capacity = capacity_tonnes if capacity_tonnes else b.eu_export_tonnes
    capex = lever.capex_eur_per_t_capacity * capacity
    opex_delta = lever.opex_delta_eur_per_t * capacity

    start_year = a.horizon_start + lever.lead_time_years
    b_lever = replace(
        b,
        direct_intensity_override=lever.new_direct_intensity,
        indirect_intensity_override=lever.new_indirect_intensity,
    )
    lever_costs = cost_path(b_lever, a)
    avoided, net = [], []
    for yc0, yc1 in zip(base.costs, lever_costs):
        if yc0.year < start_year:
            avoided.append(0.0)
            net.append(0.0)
        else:
            av = yc0.gross_cost - yc1.gross_cost
            avoided.append(av)
            net.append(av - opex_delta)

    npv = -capex + sum(n / ((1 + a.discount_rate) ** (i + 1)) for i, n in enumerate(net))
    cum, payback = 0.0, None
    for i, n in enumerate(net):
        cum += n
        if cum >= capex and payback is None:
            payback = i + 1
    annuity = _annuity(capex, loan_rate, loan_tenor_years)
    dscr_values = [n / annuity for n in net[lever.lead_time_years:] if annuity > 0]
    min_dscr = min(dscr_values) if dscr_values else 0.0

    after = assess_borrower(b_lever, a)
    pd_before = next(c.pd_adj for c in base.credit if c.year == a.horizon_end)
    pd_after = next(c.pd_adj for c in after.credit if c.year == a.horizon_end)
    ecl_saving = base.lifetime_ecl_delta - after.lifetime_ecl_delta

    if npv > 0 and min_dscr >= 1.2:
        viability = "Bankable on CBAM savings alone"
    elif npv > 0:
        viability = "Positive NPV; needs blended or concessional tranche"
    elif min_dscr >= 1.0:
        viability = "Covers debt service late in horizon; NPV negative at this rate"
    else:
        viability = "Not self-financing from CBAM savings; policy support required"

    return LeverResult(
        lever=lever, capex_eur=capex, annual_opex_delta_eur=opex_delta,
        avoided_cost_by_year=avoided, net_benefit_by_year=net,
        cumulative_avoided_cost=sum(avoided), npv_eur=npv, simple_payback_years=payback,
        annuity_eur=annuity, min_dscr=min_dscr, pd_2034_before=pd_before,
        pd_2034_after=pd_after, ecl_delta_before=base.lifetime_ecl_delta,
        ecl_delta_after=after.lifetime_ecl_delta, ecl_saving_for_lender=ecl_saving,
        loan_size_eur=capex, viability=viability,
    )


def evaluate_all_levers(b: Borrower, a: Assumptions, **kw) -> List[LeverResult]:
    results = [evaluate_lever(b, a, l, **kw) for l in levers_for(b.product)]
    return sorted(results, key=lambda r: r.npv_eur, reverse=True)
