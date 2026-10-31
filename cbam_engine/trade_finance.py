"""Trade-finance module: carbon-cost sensitivity at shipment level.

The CBAM legal obligation sits with the EU authorised declarant (usually the
importer), but the economic cost travels back to the exporter through price
rebates, set-offs and renegotiation, and to the banks financing the trade.

This module builds a shipment-level carbon ledger and derives, per instrument:

* certificate exposure on the declared intensity and on the Commission default
  value (with the statutory mark-up), the latter being what applies if the
  verified emissions report is missing or rejected;
* the exporter's dilution exposure, given the contract's carbon clause;
* a carbon-adjusted eligible receivable and borrowing base (receivables
  discounting, supply chain finance on the exporter side);
* a funded certificate reserve for importer-side facilities (import loans,
  buyer-side SCF), at 100-125 percent of the estimated liability;
* LC documentary-discrepancy risk when an emissions report is a required
  document;
* early-warning flags.

Default values and mark-ups: Commission Implementing Regulation on CBAM default
values (adopted December 2025). Mark-up 10 percent (2026), 20 percent (2027),
30 percent (2028 onwards); fertilisers 1 percent; electricity none.
Control logic follows practitioner guidance on carbon-adjusted borrowing bases
and reserves (e.g. cbam.engineer, "CBAM turns EU export finance into a
carbon-adjusted credit decision", 2026).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .reference import PRODUCTS, PRICE_SCENARIOS, phase_in

# ---------------------------------------------------------------------------
# Default values (tCO2e per tonne, before mark-up). Only values verified against
# a public source are listed; otherwise the engine falls back to the route
# intensity x DEFAULT_FALLBACK_UPLIFT and flags the row as "estimated default".
# ---------------------------------------------------------------------------
DEFAULT_VALUES: Dict[Tuple[str, str], Dict] = {
    ("steel", "IN"): {"value": 4.270, "cn": "7207 12 10", "label": "Semi-finished steel slab, India"},
    ("aluminium", "AE"): {"value": 1.870, "cn": "7601", "label": "Unwrought aluminium, UAE"},
    ("urea", "EG"): {"value": 1.390, "cn": "3102 10 19", "label": "Urea, Egypt"},
    ("cement", "TR"): {"value": 1.440, "cn": "2523", "label": "Cement, Turkey (reported as 'other countries' value)"},
}
DEFAULT_SOURCE = ("Commission default values as reported by cbamguide.com/compliance/default-values "
                  "(accessed Oct 2026). Verify against the official annex before use.")
DEFAULT_FALLBACK_UPLIFT = 1.50   # analyst assumption when no published default is loaded


def default_markup(product: str, year: int) -> float:
    if PRODUCTS[product].sector == "Fertilisers":
        return 0.01
    if product == "electricity":
        return 0.0
    if year <= 2026:
        return 0.10
    if year == 2027:
        return 0.20
    return 0.30


def default_value(product: str, country: str, route: str) -> Tuple[float, str]:
    """Return (default value before mark-up, provenance)."""
    rec = DEFAULT_VALUES.get((product, country))
    if rec:
        return rec["value"], f"published: {rec['label']} (CN {rec['cn']})"
    p = PRODUCTS[product]
    est = p.routes[route].direct_intensity
    if p.indirect_in_scope:
        est += p.routes[route].indirect_intensity
    return est * DEFAULT_FALLBACK_UPLIFT, f"estimated: route intensity x {DEFAULT_FALLBACK_UPLIFT}"


# Share of the CBAM cost that flows back to the exporter as rebate / set-off,
# by contract carbon clause. Judgement defaults, editable in the app.
CLAUSE_EXPORTER_SHARE: Dict[str, float] = {
    "fixed_price": 0.30,          # importer legally bears it, but commercial rebate pressure
    "indexed_certificate": 1.00,  # price indexed to certificate cost, deducted from invoice
    "verified_adjustment": 0.70,  # price adjusted ex post on verified emissions
    "retro_reconcile": 1.00,      # full reconciliation after the annual declaration
    "ddp_exporter_declarant": 1.00,  # exporter (or its EU entity) is the declarant
}
CLAUSE_LABELS = {
    "fixed_price": "Fixed price, no carbon clause",
    "indexed_certificate": "Price indexed to certificate cost",
    "verified_adjustment": "Adjustment on verified emissions",
    "retro_reconcile": "Retroactive reconciliation",
    "ddp_exporter_declarant": "DDP / exporter is declarant",
}
INSTRUMENTS = {
    "receivables_discounting": "Receivables discounting / forfaiting",
    "scf_supplier": "Supply chain finance, supplier side",
    "letter_of_credit": "Documentary credit (LC)",
    "pre_export": "Pre-export finance",
    "import_loan": "Importer working-capital / import loan",
}
VERIFICATION_STATES = ("verified", "pre_verified", "none")


@dataclass
class Shipment:
    shipment_id: str
    borrower_id: str
    counterparty: str
    instrument: str
    product: str
    route: str
    country: str
    tonnes: float
    invoice_value_eur: float
    import_year: int = 2026
    declared_intensity: Optional[float] = None    # exporter-reported tCO2/t (in CBAM scope)
    verification_status: str = "none"
    contract_clause: str = "fixed_price"
    advance_rate: float = 0.80
    tenor_days: int = 90
    lc_requires_emissions_doc: bool = False
    domestic_carbon_price_paid: float = 0.0       # EUR/tCO2 with proof of payment

    def validate(self) -> List[str]:
        e = []
        if self.product not in PRODUCTS:
            e.append(f"{self.shipment_id}: unknown product {self.product}")
        elif self.route not in PRODUCTS[self.product].routes:
            e.append(f"{self.shipment_id}: unknown route {self.route}")
        if self.instrument not in INSTRUMENTS:
            e.append(f"{self.shipment_id}: unknown instrument {self.instrument}")
        if self.contract_clause not in CLAUSE_EXPORTER_SHARE:
            e.append(f"{self.shipment_id}: unknown contract clause {self.contract_clause}")
        if self.verification_status not in VERIFICATION_STATES:
            e.append(f"{self.shipment_id}: verification_status must be one of {VERIFICATION_STATES}")
        if self.tonnes <= 0 or self.invoice_value_eur <= 0:
            e.append(f"{self.shipment_id}: tonnes and invoice value must be positive")
        return e


@dataclass
class TFAssumptions:
    price_scenario: str = "base"
    stress_price: float = 100.0                 # EUR/t stress, per practitioner guidance
    pre_verified_buffer: float = 0.10           # extra intensity buffer if only pre-verified
    eligibility_buffer: float = 0.05            # price, classification and verification buffer (share of exposure)
    reserve_cover: float = 1.25                 # funded reserve as multiple of liability (1.00-1.25)
    material_dilution_pct: float = 0.05         # flag if dilution > 5 percent of invoice
    default_gap_flag: float = 0.25              # flag if default exceeds declared by >25 percent
    clause_share: Dict[str, float] = field(default_factory=lambda: dict(CLAUSE_EXPORTER_SHARE))


@dataclass
class ShipmentResult:
    shipment: Shipment
    certificate_price: float
    phase_in: float
    benchmark_free: float
    intensity_route: float
    intensity_declared_used: float
    intensity_default: float
    default_markup: float
    default_provenance: str
    exposure_declared: float
    exposure_default: float
    exposure_stress: float
    exposure_if_verified: float
    exposure_used_for_eligibility: float
    exporter_share: float
    dilution: float
    dilution_pct_invoice: float
    eligible_receivable: float
    borrowing_base_plain: float
    borrowing_base_carbon: float
    borrowing_base_reduction: float
    funded_reserve: float
    lc_discrepancy_risk: str
    flags: List[str]

    def row(self) -> Dict:
        s = self.shipment
        return {
            "shipment_id": s.shipment_id, "borrower_id": s.borrower_id, "counterparty": s.counterparty,
            "instrument": INSTRUMENTS[s.instrument], "product": s.product, "country": s.country,
            "tonnes": s.tonnes, "invoice_value_eur": s.invoice_value_eur, "year": s.import_year,
            "verification": s.verification_status, "clause": CLAUSE_LABELS[s.contract_clause],
            "intensity_used": self.intensity_declared_used, "default_with_markup": self.intensity_default,
            "default_provenance": self.default_provenance,
            "certificate_price": self.certificate_price, "exposure_declared": self.exposure_declared,
            "exposure_default": self.exposure_default, "exposure_stress": self.exposure_stress,
            "exposure_if_verified": self.exposure_if_verified,
            "exporter_share": self.exporter_share, "dilution": self.dilution,
            "dilution_pct_invoice": self.dilution_pct_invoice,
            "borrowing_base_plain": self.borrowing_base_plain,
            "borrowing_base_carbon": self.borrowing_base_carbon,
            "borrowing_base_reduction": self.borrowing_base_reduction,
            "funded_reserve": self.funded_reserve, "lc_discrepancy_risk": self.lc_discrepancy_risk,
            "flags": "; ".join(self.flags),
        }


def _exposure(intensity: float, benchmark_free: float, price: float, tonnes: float,
              dom_price: float) -> float:
    chargeable = max(0.0, intensity - benchmark_free)
    credit = min(dom_price, price) / price if price > 0 else 0.0
    return chargeable * (1 - credit) * price * tonnes


def assess_shipment(s: Shipment, a: TFAssumptions) -> ShipmentResult:
    p = PRODUCTS[s.product]
    year = s.import_year
    price = PRICE_SCENARIOS[a.price_scenario].path.get(year, PRICE_SCENARIOS[a.price_scenario].path[2034])
    cf = phase_in(year)
    free = p.benchmark_tco2_per_t * (1 - cf)

    route_i = p.routes[s.route].direct_intensity + (p.routes[s.route].indirect_intensity
                                                    if p.indirect_in_scope else 0.0)
    dv, prov = default_value(s.product, s.country, s.route)
    mu = default_markup(s.product, year)
    dv_mu = dv * (1 + mu)

    flags: List[str] = []
    if s.verification_status == "verified" and s.declared_intensity is not None:
        used = s.declared_intensity
    elif s.verification_status == "pre_verified" and s.declared_intensity is not None:
        used = s.declared_intensity * (1 + a.pre_verified_buffer)
        flags.append("Pre-verified only: buffer applied until accredited verification")
    else:
        used = dv_mu
        flags.append("No verified emissions: default value with mark-up applied")

    # domestic carbon price is credited only with proof; downside case assumes none
    exp_used = _exposure(used, free, price, s.tonnes, s.domestic_carbon_price_paid)
    exp_default = _exposure(dv_mu, free, price, s.tonnes, 0.0)
    verified_i = s.declared_intensity if s.declared_intensity is not None else route_i
    exp_if_verified = _exposure(verified_i, free, price, s.tonnes, 0.0)
    stress_price = max(a.stress_price, price)
    exp_stress = _exposure(max(used, dv_mu), free, stress_price, s.tonnes, 0.0)

    share = a.clause_share.get(s.contract_clause, 1.0)
    # eligibility haircut: higher of calculated or default-value exposure, plus buffer
    elig_basis = max(exp_used, exp_default if s.verification_status != "verified" else exp_used)
    dilution = elig_basis * share * (1 + a.eligibility_buffer)
    dilution = min(dilution, s.invoice_value_eur)
    eligible = s.invoice_value_eur - dilution

    exporter_side = s.instrument in ("receivables_discounting", "scf_supplier", "pre_export", "letter_of_credit")
    bb_plain = s.advance_rate * s.invoice_value_eur if exporter_side else 0.0
    bb_carbon = s.advance_rate * eligible if exporter_side else 0.0
    reserve_basis = exp_used if s.verification_status == "verified" else max(exp_used, exp_default)
    reserve = a.reserve_cover * reserve_basis if s.instrument == "import_loan" else 0.0

    if s.instrument == "letter_of_credit" and s.lc_requires_emissions_doc:
        lc_risk = "High: emissions report as LC document invites discrepancies; move to condition precedent"
        flags.append("LC requires emissions document")
    elif s.instrument == "letter_of_credit":
        lc_risk = "Low"
    else:
        lc_risk = "n/a"

    if s.declared_intensity and dv_mu > s.declared_intensity * (1 + a.default_gap_flag):
        gap, saving = dv_mu / s.declared_intensity - 1, (exp_default - exp_if_verified) / 1e3
        if s.verification_status == "verified":
            flags.append(f"Verified data saves EUR {saving:,.0f}k vs default value (+{gap:.0%}); "
                         f"monitor verification renewal")
        else:
            flags.append(f"Default value exceeds declared by {gap:.0%}: verification is worth EUR {saving:,.0f}k")
    if dilution / s.invoice_value_eur >= a.material_dilution_pct:
        flags.append(f"Material dilution {dilution / s.invoice_value_eur:.1%} of invoice")
    if prov.startswith("estimated"):
        flags.append("Default value estimated, load official value")
    if s.domestic_carbon_price_paid > 0:
        flags.append("Domestic carbon price credit requires proof of payment")

    return ShipmentResult(
        shipment=s, certificate_price=price, phase_in=cf, benchmark_free=free,
        intensity_route=route_i, intensity_declared_used=used, intensity_default=dv_mu,
        default_markup=mu, default_provenance=prov, exposure_declared=exp_used,
        exposure_default=exp_default, exposure_stress=exp_stress, exposure_if_verified=exp_if_verified,
        exposure_used_for_eligibility=elig_basis,
        exporter_share=share, dilution=dilution, dilution_pct_invoice=dilution / s.invoice_value_eur,
        eligible_receivable=eligible, borrowing_base_plain=bb_plain, borrowing_base_carbon=bb_carbon,
        borrowing_base_reduction=bb_plain - bb_carbon, funded_reserve=reserve,
        lc_discrepancy_risk=lc_risk, flags=flags,
    )


def load_shipments(source) -> Tuple[List[Shipment], List[str]]:
    df = pd.read_csv(source) if (hasattr(source, "read") or str(source).endswith(".csv")) else pd.read_excel(source)
    return dataframe_to_shipments(df)


def dataframe_to_shipments(df: pd.DataFrame) -> Tuple[List[Shipment], List[str]]:
    errs: List[str] = []
    out: List[Shipment] = []
    valid = set(Shipment.__dataclass_fields__)
    for _, row in df.iterrows():
        kw = {k: v for k, v in row.items() if k in valid and not pd.isna(v)}
        for k in ("shipment_id", "borrower_id", "counterparty", "instrument", "product", "route",
                  "country", "verification_status", "contract_clause"):
            if k in kw:
                kw[k] = str(kw[k])
        if "lc_requires_emissions_doc" in kw:
            kw["lc_requires_emissions_doc"] = str(kw["lc_requires_emissions_doc"]).lower() in ("1", "true", "yes")
        for k in ("import_year", "tenor_days"):
            if k in kw:
                kw[k] = int(kw[k])
        try:
            s = Shipment(**kw)
        except TypeError as exc:
            errs.append(f"Row {row.get('shipment_id', '?')}: {exc}")
            continue
        e = s.validate()
        errs.extend(e)
        if not e:
            out.append(s)
    return out, errs


def run_shipments(shipments: List[Shipment], a: TFAssumptions) -> List[ShipmentResult]:
    return [assess_shipment(s, a) for s in shipments]


def shipments_table(results: List[ShipmentResult]) -> pd.DataFrame:
    return pd.DataFrame([r.row() for r in results])


def tf_kpis(results: List[ShipmentResult]) -> Dict[str, float]:
    t = shipments_table(results)
    if t.empty:
        return {}
    inv = t.invoice_value_eur.sum()
    return {
        "shipments": len(t),
        "invoice_value": inv,
        "exposure_declared": t.exposure_declared.sum(),
        "exposure_default": t.exposure_default.sum(),
        "exposure_stress": t.exposure_stress.sum(),
        "dilution": t.dilution.sum(),
        "dilution_pct": t.dilution.sum() / inv if inv else 0.0,
        "borrowing_base_plain": t.borrowing_base_plain.sum(),
        "borrowing_base_carbon": t.borrowing_base_carbon.sum(),
        "borrowing_base_reduction": t.borrowing_base_reduction.sum(),
        "funded_reserve": t.funded_reserve.sum(),
        "unverified_share": (t.verification != "verified").mean(),
        "value_of_verification": (t.exposure_default - t.exposure_if_verified).clip(lower=0).sum(),
    }
