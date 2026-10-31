"""Reference data for the CBAM credit-risk engine.

All figures are public-domain parameters or indicative defaults. Every default
intensity should be overridden with borrower-verified (MRV) data where available;
the `source` and `confidence` fields exist so that analysts can see what they are
relying on.

Regulatory anchors
------------------
* Regulation (EU) 2023/956 (CBAM): definitive period from 1 Jan 2026; certificate
  obligation phased in as free allocation is withdrawn under Directive
  2003/87/EC Art. 10a(1a). The Directive's "CBAM factor" is the share of free
  allocation that REMAINS (97.5 percent in 2026 down to 0 in 2034); this engine
  works with its complement, the phase-in share (1 - CBAM factor).
* Free allocation benchmarks: Implementing Regulation (EU) 2021/447 (2021-2025
  period). Benchmarks for 2026-2030 are updated by the Commission; the 2021-2025
  values are used here as the default proxy and are flagged as such.
* Indirect (electricity) emissions count towards the CBAM obligation only for
  cement, fertilisers and electricity during the definitive period as currently
  legislated; iron & steel, aluminium and hydrogen are assessed on direct
  emissions only (Annex II of the Regulation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

# ---------------------------------------------------------------------------
# Phase-in share = 1 - CBAM factor: share of the benchmark-based free allocation
# withdrawn in each year (Directive 2003/87/EC Art. 10a(1a)). CBAM factor itself is
# 97.5, 95, 90, 77.5, 51.5, 39, 26.5, 14, 0 percent for 2026-2034.
# Directive 2003/87/EC Art. 10a(1a) as amended by Directive (EU) 2023/959.
# ---------------------------------------------------------------------------
PHASE_IN: Dict[int, float] = {
    2026: 0.025,
    2027: 0.050,
    2028: 0.100,
    2029: 0.225,
    2030: 0.485,
    2031: 0.610,
    2032: 0.735,
    2033: 0.860,
    2034: 1.000,
}
HORIZON_YEARS: List[int] = sorted(PHASE_IN)


def phase_in(year: int) -> float:
    """Phase-in share (1 - CBAM factor) for a year; 0 before 2026, 1 after 2034."""
    if year < 2026:
        return 0.0
    if year > 2034:
        return 1.0
    return PHASE_IN[year]


def cbam_factor(year: int) -> float:
    """CBAM factor as defined in the Directive: share of free allocation remaining."""
    return 1.0 - phase_in(year)


# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Product:
    code: str
    sector: str
    name: str
    unit: str
    benchmark_tco2_per_t: float          # EU ETS free-allocation benchmark (direct)
    benchmark_source: str
    indirect_in_scope: bool              # do indirect emissions count for CBAM?
    routes: Dict[str, "Route"] = field(default_factory=dict)


@dataclass(frozen=True)
class Route:
    code: str
    name: str
    direct_intensity: float              # tCO2 per tonne of product (indicative)
    indirect_intensity: float            # tCO2 per tonne via purchased electricity
    source: str
    confidence: str                      # high / medium / low


PRODUCTS: Dict[str, Product] = {}


def _add(p: Product) -> None:
    PRODUCTS[p.code] = p


_add(Product(
    code="steel",
    sector="Iron and steel",
    name="Crude steel / semi-finished steel",
    unit="t steel",
    benchmark_tco2_per_t=1.288,
    benchmark_source="IR (EU) 2021/447 hot metal benchmark 1.288 tCO2/t (proxy for crude steel)",
    indirect_in_scope=False,
    routes={
        "bf_bof": Route("bf_bof", "Blast furnace - basic oxygen furnace",
                        2.30, 0.10,
                        "IEA Iron and Steel Technology Roadmap (2020): global BF-BOF ~2.2-2.4 tCO2/t; "
                        "worldsteel 2023 sustainability indicators",
                        "medium"),
        "bf_bof_india": Route("bf_bof_india", "BF-BOF, Indian average",
                              2.55, 0.12,
                              "Indian average ~2.5-2.6 tCO2/t crude steel (Ministry of Steel, "
                              "Greening the Steel Sector in India, 2024; IEA India Energy Outlook)",
                              "medium"),
        "dri_eaf_coal": Route("dri_eaf_coal", "Coal-based DRI - EAF/IF",
                              2.70, 0.60,
                              "Coal DRI route widely reported at 2.5-3.0 tCO2/t; Ministry of Steel 2024",
                              "medium"),
        "dri_eaf_gas": Route("dri_eaf_gas", "Gas-based DRI - EAF",
                             1.40, 0.45,
                             "IEA Iron and Steel Technology Roadmap (2020): NG-DRI-EAF ~1.4 tCO2/t",
                             "medium"),
        "scrap_eaf": Route("scrap_eaf", "Scrap - EAF",
                           0.30, 0.45,
                           "IR (EU) 2021/447 EAF carbon steel benchmark 0.215; IEA scrap-EAF 0.3-0.4 "
                           "direct",
                           "medium"),
    },
))

_add(Product(
    code="cement",
    sector="Cement",
    name="Cement (OPC / blended)",
    unit="t cement",
    benchmark_tco2_per_t=0.693 * 0.90,  # clinker benchmark x indicative clinker ratio
    benchmark_source="IR (EU) 2021/447 grey clinker benchmark 0.693 tCO2/t clinker, scaled by 0.90 "
                     "clinker ratio (analyst assumption; CBAM benchmark for cement pending)",
    indirect_in_scope=True,
    routes={
        "opc": Route("opc", "Ordinary Portland cement (high clinker)",
                     0.80, 0.08,
                     "GCCA Getting the Numbers Right: ~0.8 tCO2/t for ~95% clinker cement",
                     "medium"),
        "blended_india": Route("blended_india", "Blended cement, Indian average",
                               0.58, 0.07,
                               "Indian cement average ~0.57-0.60 tCO2/t (CSI/GCCA India; CMA)",
                               "medium"),
        "clinker": Route("clinker", "Clinker (exported as clinker)",
                         0.85, 0.06,
                         "GCCA GNR global clinker ~0.84-0.86 tCO2/t",
                         "high"),
    },
))

_add(Product(
    code="aluminium",
    sector="Aluminium",
    name="Unwrought aluminium",
    unit="t Al",
    benchmark_tco2_per_t=1.464,
    benchmark_source="IR (EU) 2021/447 primary aluminium benchmark 1.464 tCO2/t",
    indirect_in_scope=False,
    routes={
        "primary_prebake": Route("primary_prebake", "Primary smelter, prebake anodes",
                                 1.70, 14.0,
                                 "IAI 2022: direct process + anode ~1.6-1.8 tCO2/t; indirect depends "
                                 "on grid (coal-based ~13-15 tCO2/t, not in CBAM scope)",
                                 "medium"),
        "primary_soderberg": Route("primary_soderberg", "Primary smelter, Soderberg",
                                   2.10, 14.0,
                                   "IAI: Soderberg direct intensities higher than prebake",
                                   "low"),
        "secondary": Route("secondary", "Secondary (scrap remelt)",
                           0.35, 0.30,
                           "IAI secondary aluminium ~0.3-0.5 tCO2/t",
                           "medium"),
    },
))

_add(Product(
    code="ammonia",
    sector="Fertilisers",
    name="Ammonia",
    unit="t NH3",
    benchmark_tco2_per_t=1.570,
    benchmark_source="IR (EU) 2021/447 ammonia benchmark 1.570 tCO2/t",
    indirect_in_scope=True,
    routes={
        "smr_gas": Route("smr_gas", "Steam methane reforming (natural gas)",
                         1.90, 0.10,
                         "IFA/IEA Ammonia Technology Roadmap (2021): gas-based ~1.8-2.0 tCO2/t",
                         "high"),
        "smr_india": Route("smr_india", "Gas-based, Indian average",
                           2.05, 0.12,
                           "Indian plants ~2.0-2.2 tCO2/t (FAI benchmarking; IEA 2021)",
                           "medium"),
        "coal_gasification": Route("coal_gasification", "Coal gasification",
                                   3.80, 0.20,
                                   "IEA Ammonia Technology Roadmap: coal-based ~3.5-4.0 tCO2/t",
                                   "medium"),
        "blue": Route("blue", "Blue ammonia (SMR + CCS)",
                      0.60, 0.15,
                      "IEA: 60-90 percent capture on SMR",
                      "low"),
    },
))

_add(Product(
    code="urea",
    sector="Fertilisers",
    name="Urea",
    unit="t urea",
    benchmark_tco2_per_t=1.570 * 0.57 + 0.0,  # ammonia benchmark scaled by NH3 content
    benchmark_source="Ammonia benchmark scaled by 0.57 t NH3 per t urea (analyst assumption)",
    indirect_in_scope=True,
    routes={
        "gas_integrated": Route("gas_integrated", "Integrated ammonia-urea, gas",
                                0.75, 0.08,
                                "Net of CO2 captured into urea; IFA benchmarking ~0.7-0.9 tCO2/t",
                                "medium"),
        "coal_integrated": Route("coal_integrated", "Integrated ammonia-urea, coal",
                                 1.90, 0.15,
                                 "Coal-based urea ~1.8-2.2 tCO2/t (IEA 2021)",
                                 "low"),
    },
))

_add(Product(
    code="hydrogen",
    sector="Hydrogen",
    name="Hydrogen",
    unit="t H2",
    benchmark_tco2_per_t=6.84,
    benchmark_source="IR (EU) 2021/447 hydrogen benchmark 6.84 tCO2/t",
    indirect_in_scope=False,
    routes={
        "smr": Route("smr", "Steam methane reforming",
                     9.30, 0.30,
                     "IEA Global Hydrogen Review: unabated SMR ~9-10 tCO2/t",
                     "high"),
        "coal_gasification": Route("coal_gasification", "Coal gasification",
                                   19.0, 0.40,
                                   "IEA: coal gasification ~19-20 tCO2/t",
                                   "high"),
        "electrolysis": Route("electrolysis", "Electrolysis",
                              0.0, 0.0,
                              "Zero direct; indirect depends on power source",
                              "high"),
    },
))

SECTORS = sorted({p.sector for p in PRODUCTS.values()})


# ---------------------------------------------------------------------------
# ETS price scenarios (EUR per tCO2). CBAM certificate price equals the
# average EUA auction price of the preceding quarter (Reg. 2023/956 Art. 21).
# Q1 2026 official CBAM certificate price was EUR 75.36/t (European Commission).
# Spot EUAs traded around EUR 80/t in mid-2026.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PriceScenario:
    code: str
    name: str
    description: str
    path: Dict[int, float]


def _path(start: float, end: float) -> Dict[int, float]:
    n = len(HORIZON_YEARS) - 1
    return {y: round(start + (end - start) * i / n, 2) for i, y in enumerate(HORIZON_YEARS)}


PRICE_SCENARIOS: Dict[str, PriceScenario] = {
    "low": PriceScenario("low", "Low", "Price drifts down to EUR 55/t by 2034 (weak demand, "
                         "policy relaxation).", _path(75.0, 55.0)),
    "base": PriceScenario("base", "Base", "Gradual rise to EUR 110/t by 2034, consistent with "
                          "MSR tightening and the 2040 target trajectory.", _path(78.0, 110.0)),
    "high": PriceScenario("high", "High", "Rapid tightening to EUR 160/t by 2034 (NGFS Net Zero "
                          "2050 style trajectory).", _path(80.0, 160.0)),
}

# Domestic carbon prices creditable against CBAM (Art. 9): EUR per tCO2, indicative.
# India's CCTS is not yet a liquid priced market; Turkey's ETS pilot starts 2026.
DOMESTIC_CARBON_PRICE: Dict[str, float] = {
    "IN": 0.0,     # India: Carbon Credit Trading Scheme, no effective price yet
    "TR": 0.0,     # Turkey: ETS pilot phase 2026, free allocation
    "AE": 0.0,     # UAE: no carbon price
    "SA": 0.0,
    "EG": 0.0,
    "MA": 0.0,
    "UA": 1.0,     # Ukraine: CO2 tax ~ UAH 30/t (~EUR 0.7)
    "GB": 45.0,    # UK ETS, indicative
    "CN": 11.0,    # China national ETS, indicative
    "VN": 0.0,
    "OTHER": 0.0,
}

# ---------------------------------------------------------------------------
# Decarbonisation levers: indicative intensity after lever, capex (EUR per tonne
# of annual capacity) and opex delta (EUR per tonne product). Sources are
# literature ranges; they are starting points for structuring a transition loan,
# not engineering estimates.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Lever:
    code: str
    product: str
    name: str
    new_direct_intensity: float
    new_indirect_intensity: float
    capex_eur_per_t_capacity: float
    opex_delta_eur_per_t: float
    lead_time_years: int
    source: str


LEVERS: List[Lever] = [
    Lever("steel_scrap_eaf", "steel", "Switch to scrap-EAF (partial relining)",
          0.30, 0.45, 350.0, 15.0, 3,
          "IEA Iron and Steel Technology Roadmap: EAF capex USD 250-400/t; opex sensitive to scrap"),
    Lever("steel_gas_dri", "steel", "Gas-based DRI-EAF",
          1.40, 0.45, 600.0, 25.0, 4,
          "IEA: NG-DRI-EAF capex USD 500-700/t"),
    Lever("steel_h2_dri", "steel", "Hydrogen DRI-EAF",
          0.10, 0.60, 900.0, 80.0, 6,
          "IEA/MPP: H2-DRI capex USD 800-1000/t, green premium EUR 60-120/t"),
    Lever("cement_clinker_sub", "cement", "Clinker substitution to 0.65 ratio",
          0.52, 0.07, 25.0, -2.0, 2,
          "GCCA Roadmap: clinker ratio reduction, low capex, often opex-neutral"),
    Lever("cement_ccs", "cement", "Carbon capture on kiln",
          0.20, 0.12, 180.0, 40.0, 5,
          "IEA CCUS in cement: capex EUR 150-200/t capacity, opex EUR 30-60/t"),
    Lever("ammonia_blue", "ammonia", "CCS retrofit on SMR (blue ammonia)",
          0.60, 0.15, 220.0, 20.0, 4,
          "IEA Ammonia Technology Roadmap: CCS retrofit capex USD 200-250/t"),
    Lever("ammonia_green_blend", "ammonia", "30 percent green hydrogen feed",
          1.35, 0.15, 400.0, 45.0, 4,
          "IEA: electrolyser cost USD 500-900/kW; partial substitution"),
    Lever("aluminium_secondary", "aluminium", "Increase scrap share to 40 percent",
          1.15, 8.5, 150.0, -10.0, 3,
          "IAI: secondary remelt capex USD 100-200/t; scrap economics favourable"),
    Lever("hydrogen_ccs", "hydrogen", "CCS on SMR",
          2.00, 0.35, 1800.0, 300.0, 4,
          "IEA Global Hydrogen Review: blue H2 capex USD 1.5-2.0k/t"),
]


def levers_for(product: str) -> List[Lever]:
    return [l for l in LEVERS if l.product == product]


# Rating scale used for PD-to-notch mapping (through-the-cycle, indicative).
RATING_SCALE: List[tuple] = [
    ("AAA", 0.0001), ("AA", 0.0003), ("A", 0.0008), ("BBB+", 0.0015), ("BBB", 0.0030),
    ("BBB-", 0.0050), ("BB+", 0.0080), ("BB", 0.0130), ("BB-", 0.0200), ("B+", 0.0320),
    ("B", 0.0500), ("B-", 0.0800), ("CCC", 0.1500), ("CC", 0.3000), ("C", 0.5000),
]


def pd_to_rating(pd_value: float) -> str:
    for label, ceiling in RATING_SCALE:
        if pd_value <= ceiling:
            return label
    return "D"


def rating_index(label: str) -> int:
    labels = [r[0] for r in RATING_SCALE] + ["D"]
    return labels.index(label)
