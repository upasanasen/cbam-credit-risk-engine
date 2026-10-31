"""Command line: python -m cbam_engine run loanbook.csv --scenario base --out results.xlsx"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from .models import Assumptions
from .portfolio import (load_loanbook, run_portfolio, results_table, year_table,
                        portfolio_kpis, sector_table, scenario_comparison, template_csv)
from .opportunity import evaluate_all_levers


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cbam_engine", description="CBAM credit-risk engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Assess a loan book")
    r.add_argument("loanbook")
    r.add_argument("--scenario", default="base", choices=["low", "base", "high"])
    r.add_argument("--pass-through", type=float, default=0.30)
    r.add_argument("--out", default="cbam_results.xlsx")

    t = sub.add_parser("template", help="Print an empty loan-book CSV template")

    args = p.parse_args(argv)

    if args.cmd == "template":
        sys.stdout.write(template_csv())
        return 0

    borrowers, errors = load_loanbook(args.loanbook)
    for e in errors:
        print("WARN", e, file=sys.stderr)
    if not borrowers:
        print("No valid borrowers.", file=sys.stderr)
        return 1
    a = Assumptions(price_scenario=args.scenario, default_pass_through=args.pass_through)
    res = run_portfolio(borrowers, a)
    k = portfolio_kpis(res, a)

    print(f"Borrowers: {k['borrowers']}   Total EAD: EUR {k['total_ead']:,.0f}")
    print(f"Gross CBAM cost 2034 (scenario {args.scenario}): EUR {k['gross_cbam_cost_2034']:,.0f}")
    print(f"12m ECL uplift 2034: EUR {k['ecl_12m_delta_2034']:,.0f}   "
          f"Lifetime ECL uplift: EUR {k['lifetime_ecl_delta']:,.0f}")
    print(f"Stage 2 EAD 2034: EUR {k['stage2_ead_2034']:,.0f} ({k['stage2_share']:.1%})")

    lever_rows = []
    for rr in res:
        for lr in evaluate_all_levers(rr.borrower, a)[:3]:
            lever_rows.append({"borrower_id": rr.borrower.borrower_id, **lr.summary()})

    with pd.ExcelWriter(args.out) as xw:
        pd.DataFrame([k]).T.rename(columns={0: "value"}).to_excel(xw, sheet_name="portfolio_kpis")
        results_table(res).to_excel(xw, sheet_name="borrowers", index=False)
        year_table(res).to_excel(xw, sheet_name="by_year", index=False)
        sector_table(res, a).to_excel(xw, sheet_name="sectors", index=False)
        scenario_comparison(borrowers, a).to_excel(xw, sheet_name="scenarios", index=False)
        pd.DataFrame(lever_rows).to_excel(xw, sheet_name="transition_levers", index=False)
        pd.DataFrame([a.to_dict()]).T.rename(columns={0: "value"}).to_excel(xw, sheet_name="assumptions")
    print(f"Written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
