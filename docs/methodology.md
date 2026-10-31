# Methodology

## 1. Scope and purpose

The engine quantifies the transition risk that the EU Carbon Border Adjustment Mechanism (CBAM) imposes on a lender's exposures to non-EU producers of CBAM goods, and the financing opportunity created by the abatement that would neutralise it. It operates at borrower level and aggregates to portfolio level.

## 2. CBAM certificate obligation

Regulation (EU) 2023/956 requires the authorised declarant to surrender certificates equal to the embedded emissions of imported goods, adjusted for free allocation granted to EU producers (Art. 31) and for any carbon price effectively paid in the country of origin (Art. 9). The engine models the obligation per tonne of product as

```
chargeable_y   = max(0, E_embedded - B * (1 - CF_y))
certificates_y = chargeable_y * (1 - min(p_dom, P_y) / P_y)
cost_per_t_y   = certificates_y * P_y
```

* `E_embedded`: direct specific emissions, plus indirect (electricity) emissions where Annex II places them in scope (cement, fertilisers, electricity). Iron and steel, aluminium and hydrogen are assessed on direct emissions only.
* `B`: EU ETS product benchmark (Implementing Regulation (EU) 2021/447). The engine uses the 2021-2025 values as a proxy until the 2026-2030 benchmarks are adopted.
* `CF_y`: CBAM factor, the share of free allocation withdrawn in year y under Directive 2003/87/EC Art. 10a(1a): 2.5 % (2026), 5 %, 10 %, 22.5 %, 48.5 %, 61 %, 73.5 %, 86 %, 100 % (2034).
* `P_y`: certificate price. Under Art. 21 this equals the average closing price of EUA auctions in the preceding quarter; the official Q1 2026 price was EUR 75.36/t. Three forward paths are supplied (Low, Base, High) and are user-editable.
* `p_dom`: domestic carbon price creditable under Art. 9. India's Carbon Credit Trading Scheme has no effective price yet; Türkiye's ETS pilot starts in 2026 with free allocation. Both default to zero.

Gross cost is `cost_per_t × EU export tonnes`. The cost borne by the exporter is gross cost × (1 − pass-through). Pass-through is a judgement input, defaulting to 30 % and overridable per borrower.

An optional demand-response term reduces volumes by `elasticity × percentage price uplift`.

## 3. Earnings restatement

```
EBITDA_y    = EBITDA_0 - borne_cost_y
ICR_y       = EBITDA_y / interest
Leverage_y  = Debt / EBITDA_y
```

## 4. Probability of default

```
logit(PD_y) = logit(PD_0) + k * (borne_cost_y / EBITDA_0) + penalty * 1[ICR_y < floor]
```

The monotone link from a sectoral cost shock to PD mirrors the structure of supervisory climate stress tests (ECB 2022 climate stress test; Bank of England CBES 2021), where transition costs enter borrower financials and are mapped to PD through a satellite model. `k` (default 2.5) and the ICR penalty (default 1.0 logit) are placeholders: calibrate them against the institution's own migration data by regressing historical rating migrations on EBITDA shocks of similar magnitude.

PD is floored at the baseline so that CBAM never improves credit quality in the risk view.

## 5. Loss given default

Carbon-intensive plant and equipment loses collateral value as the carbon cost it generates rises. Following the logic of the "climate multiplier" proposed in the Journal of BRSA Banking and Financial Markets (2024), LGD is lifted in proportion to the earnings shock and capped:

```
LGD_y = min(cap, LGD_0 + s * borne_cost_y / EBITDA_0)
```

## 6. Expected credit loss and staging

* 12-month ECL_y = PD_y × LGD_y × EAD.
* Lifetime ECL = Σ discounted survival-weighted marginal ECL over the remaining maturity.
* IFRS 9 stage 2 is assigned when PD_y / PD_0 ≥ SICR ratio (default 2.0) and PD_y − PD_0 ≥ absolute threshold (default 50 bps), or when restated EBITDA is negative.
* Rating migration is reported in notches on an indicative through-the-cycle scale.
* Capital at risk = EAD × risk weight × capital ratio, as a sizing reference only.

## 7. Transition finance

For each lever catalogued for the borrower's product the engine:

1. recomputes the certificate cost path with the post-lever intensities, from the lead-time year;
2. computes avoided gross cost per year and net benefit after the opex delta;
3. sizes the loan as unit capex × retrofit capacity;
4. reports NPV at the engine discount rate, simple payback, and the minimum DSCR of net benefit against an annuity on the capex;
5. re-runs the credit assessment to show the post-lever PD and the lender's ECL saving.

Capex and opex parameters are literature ranges (IEA technology roadmaps, GCCA, IAI, Mission Possible Partnership) suitable for a first structuring conversation, not engineering estimates.

## 8. Data sources for default intensities

| Product | Default routes | Primary sources |
|---|---|---|
| Steel | BF-BOF (global, India), coal DRI, gas DRI, scrap EAF | IEA Iron and Steel Technology Roadmap 2020; worldsteel indicators; Ministry of Steel (India) Greening the Steel Sector 2024 |
| Cement | OPC, Indian blended, clinker | GCCA Getting the Numbers Right; CMA |
| Aluminium | Primary prebake, Soderberg, secondary | International Aluminium Institute GHG data 2022 |
| Ammonia / urea | Gas SMR (global, India), coal gasification, blue | IEA Ammonia Technology Roadmap 2021; IFA benchmarking |
| Hydrogen | SMR, coal gasification, electrolysis | IEA Global Hydrogen Review |

Every default carries a confidence tag. Installation-level MRV data should replace defaults wherever available; the override columns exist for that purpose.

## 9. Known limitations

* No modelling of EU demand substitution, competitor response or domestic price pass-back unless the elasticity term is set.
* No treatment of CBAM scope extensions (downstream products, Art. 30 review) or of the proposed Art. 2 de minimis threshold of 50 tonnes per importer.
* Single-year balance-sheet snapshot: EBITDA growth, refinancing and hedging are outside the model.
* Parameters k and s are not calibrated; results are directional until the lender supplies its own migration history.
