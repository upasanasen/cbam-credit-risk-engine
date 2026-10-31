"""Data models: borrower exposure record and engine assumptions."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .reference import PRODUCTS, DOMESTIC_CARBON_PRICE


@dataclass
class Borrower:
    borrower_id: str
    name: str
    country: str                      # ISO-2
    product: str                      # key in PRODUCTS
    route: str                        # key in product.routes
    eu_export_tonnes: float           # annual tonnes shipped to EU
    revenue_eur: float
    ebitda_eur: float
    interest_expense_eur: float
    total_debt_eur: float
    ead_eur: float                    # bank exposure at default
    pd_baseline: float                # 1-year PD, decimal
    lgd_baseline: float               # decimal
    collateral_value_eur: float = 0.0
    maturity_years: float = 5.0
    direct_intensity_override: Optional[float] = None
    indirect_intensity_override: Optional[float] = None
    pass_through_rate: Optional[float] = None   # share of CBAM cost passed to EU buyers
    domestic_carbon_price_override: Optional[float] = None
    rating_internal: str = ""
    sector_note: str = ""

    def validate(self) -> List[str]:
        errs = []
        if self.product not in PRODUCTS:
            errs.append(f"{self.borrower_id}: unknown product '{self.product}'")
        elif self.route not in PRODUCTS[self.product].routes:
            errs.append(f"{self.borrower_id}: unknown route '{self.route}' for {self.product}")
        if not (0 < self.pd_baseline < 1):
            errs.append(f"{self.borrower_id}: pd_baseline must be in (0,1)")
        if not (0 <= self.lgd_baseline <= 1):
            errs.append(f"{self.borrower_id}: lgd_baseline must be in [0,1]")
        if self.ead_eur <= 0:
            errs.append(f"{self.borrower_id}: ead_eur must be positive")
        if self.eu_export_tonnes < 0:
            errs.append(f"{self.borrower_id}: eu_export_tonnes must be non-negative")
        return errs

    @property
    def direct_intensity(self) -> float:
        if self.direct_intensity_override is not None:
            return self.direct_intensity_override
        return PRODUCTS[self.product].routes[self.route].direct_intensity

    @property
    def indirect_intensity(self) -> float:
        if self.indirect_intensity_override is not None:
            return self.indirect_intensity_override
        return PRODUCTS[self.product].routes[self.route].indirect_intensity

    @property
    def domestic_carbon_price(self) -> float:
        if self.domestic_carbon_price_override is not None:
            return self.domestic_carbon_price_override
        return DOMESTIC_CARBON_PRICE.get(self.country, DOMESTIC_CARBON_PRICE["OTHER"])

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Assumptions:
    """Engine parameters. Defaults are deliberately transparent and tunable."""
    price_scenario: str = "base"
    default_pass_through: float = 0.30        # share of CBAM cost borne by EU buyer
    demand_elasticity: float = 0.0            # volume loss per 1 percent cost-price increase (set >0 to use)
    pd_elasticity: float = 2.5                # logit shift per unit of (cost / EBITDA)
    icr_floor: float = 1.0                    # below this ICR an additional PD penalty applies
    icr_penalty_logit: float = 1.0            # extra logit shift when ICR drops below floor
    lgd_sensitivity: float = 0.25             # LGD increase per unit of (cost / EBITDA), capped
    lgd_cap: float = 0.90
    sicr_pd_ratio: float = 2.0                # IFRS 9 stage-2 trigger: PD ratio
    sicr_pd_abs: float = 0.005                # and absolute PD increase
    discount_rate: float = 0.08               # for NPV of avoided costs
    include_indirect: bool = True             # follow Annex II scope by product
    horizon_start: int = 2026
    horizon_end: int = 2034
    risk_weight_pct: float = 100.0            # standardised approach RW for corporates
    capital_ratio: float = 0.105              # CET1 + buffers used for capital-at-risk

    def to_dict(self) -> Dict:
        return asdict(self)
