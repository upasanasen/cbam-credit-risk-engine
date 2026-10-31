# CBAM Credit Risk Engine

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://cbam-credit-risk-engine.streamlit.app/)

**Live demo:** https://cbam-credit-risk-engine.streamlit.app/

Translates the EU Carbon Border Adjustment Mechanism (CBAM) into lender metrics for non-EU exporters: certificate cost paths 2026 to 2034, restated EBITDA and interest cover, probability of default, loss given default, expected credit loss, IFRS 9 staging, and the size and bankability of the decarbonisation loan that would remove the drag.

Built for banks in exporting economies (India, Türkiye, Gulf, North Africa, Ukraine) whose steel, cement, aluminium, fertiliser and hydrogen borrowers sell into the EU, and for EU institutions embedding ESG factors into credit underwriting under the EBA Guidelines on the management of ESG risks (EBA/GL/2025/01, applicable from 11 January 2026).

## What it does

| Layer | Output |
|---|---|
| CBAM cost | Chargeable intensity above the EU benchmark, certificates per tonne, gross cost, cost borne after pass-through, cost / EBITDA, per year under Low, Base and High EUA price paths |
| Credit | PD (logit shift on the earnings shock), LGD (stranded-collateral haircut), 12-month and lifetime ECL, rating migration in notches, IFRS 9 stage 1 or 2, capital at risk |
| Portfolio | EAD-weighted PD, ECL uplift in bps of EAD, stage-2 share, sector table, scenario and pass-through sensitivities, Excel export |
| Transition finance | For each catalogued lever: capex, avoided certificate cost, NPV, payback, DSCR against an annuity, post-lever PD and the lender's ECL saving |

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py                      # interactive dashboard
python -m cbam_engine run sample_data/loanbook_sample.csv --scenario base --out results.xlsx
python -m cbam_engine template > my_loanbook.csv
pytest -q
```

## Loan-book schema

Required columns: `borrower_id, name, country, product, route, eu_export_tonnes, revenue_eur, ebitda_eur, interest_expense_eur, total_debt_eur, ead_eur, pd_baseline, lgd_baseline`.

Optional: `collateral_value_eur, maturity_years, direct_intensity_override, indirect_intensity_override, pass_through_rate, domestic_carbon_price_override, rating_internal, sector_note`.

`product` is one of `steel, cement, aluminium, ammonia, urea, hydrogen`; `route` is a production route listed in `cbam_engine/reference.py` (for example `bf_bof_india`, `scrap_eaf`, `blended_india`, `primary_prebake`, `smr_india`). Supply verified installation intensities through the override columns whenever MRV data exists; route defaults are sectoral literature values.

## Regulatory anchors

* Regulation (EU) 2023/956: definitive period from 1 January 2026; certificate obligation (Art. 22); deduction for carbon price paid abroad (Art. 9); certificate price equals the previous quarter's average EUA auction price (Art. 21); first annual declaration for 2026 imports due 30 September 2027.
* Directive 2003/87/EC Art. 10a(1a): free-allocation phase-out 2026 to 2034, implemented here as the CBAM factor (2.5 %, 5 %, 10 %, 22.5 %, 48.5 %, 61 %, 73.5 %, 86 %, 100 %).
* Implementing Regulation (EU) 2021/447: product benchmarks used as the free-allocation proxy.
* EBA/GL/2025/01: ESG factors in credit underwriting, risk classification and portfolio management.

## Structure

```
cbam_engine/
  reference.py    CBAM factor, benchmarks, route intensities, price scenarios, levers, rating scale
  models.py       Borrower and Assumptions dataclasses
  cbam_cost.py    certificate obligation and cost path
  credit.py       PD, LGD, ECL, staging, borrower assessment
  opportunity.py  decarbonisation lever evaluation and loan sizing
  portfolio.py    loan-book I/O, aggregation, scenario comparison
  cli.py          command line entry point
app.py            Streamlit dashboard
sample_data/      synthetic 17-borrower loan book
docs/methodology.md
tests/
```

## Limitations

Route intensities are indicative; benchmarks for 2026 to 2030 await Commission adoption; the PD elasticity and LGD sensitivity are placeholders to be calibrated against the lender's migration history; pass-through is a judgement input; second-round demand effects are off unless the elasticity slider is set. The engine is decision support for credit and sustainability teams, not a regulatory capital model.

## Licence

MIT.
