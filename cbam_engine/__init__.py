"""CBAM Credit Risk Engine: translate EU carbon border costs into lender credit metrics."""
from .models import Borrower, Assumptions
from .cbam_cost import cost_path, year_cost, cost_summary
from .credit import assess_borrower, BorrowerResult, climate_multiplier
from .opportunity import evaluate_lever, evaluate_all_levers
from .trade_finance import (Shipment, TFAssumptions, assess_shipment, load_shipments,
                            run_shipments, shipments_table, tf_kpis)
from .portfolio import (load_loanbook, run_portfolio, results_table, year_table,
                        portfolio_kpis, sector_table, scenario_comparison, template_csv)

__version__ = "0.2.0"
__all__ = [
    "Borrower", "Assumptions", "cost_path", "year_cost", "cost_summary",
    "assess_borrower", "BorrowerResult", "evaluate_lever", "evaluate_all_levers",
    "load_loanbook", "run_portfolio", "results_table", "year_table", "portfolio_kpis",
    "sector_table", "scenario_comparison", "template_csv", "climate_multiplier",
    "Shipment", "TFAssumptions", "assess_shipment", "load_shipments", "run_shipments",
    "shipments_table", "tf_kpis",
]
