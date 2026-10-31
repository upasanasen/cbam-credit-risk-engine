"""CBAM Credit Risk Engine: Streamlit front end.

Run:  streamlit run app.py
"""
from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from cbam_engine import (Assumptions, Borrower, load_loanbook, run_portfolio, results_table,
                         year_table, portfolio_kpis, sector_table, scenario_comparison,
                         template_csv, evaluate_all_levers, assess_borrower, climate_multiplier,
                         Shipment, TFAssumptions, load_shipments, run_shipments, shipments_table,
                         tf_kpis)
from cbam_engine.trade_finance import CLAUSE_EXPORTER_SHARE, CLAUSE_LABELS, DEFAULT_SOURCE
from cbam_engine.portfolio import dataframe_to_borrowers
from cbam_engine.reference import (PRODUCTS, PRICE_SCENARIOS, PHASE_IN, HORIZON_YEARS,
                                   levers_for)

st.set_page_config(page_title="CBAM Credit Risk Engine", page_icon="⚖️", layout="wide")

PALETTE = ["#1f4e79", "#c0504d", "#9bbb59", "#8064a2", "#f79646", "#4bacc6"]


def eur(x: float, unit: str = "m") -> str:
    if unit == "m":
        return f"€{x/1e6:,.1f}m"
    return f"€{x:,.0f}"


# ---------------------------------------------------------------------------
# Sidebar: data and assumptions
# ---------------------------------------------------------------------------
st.sidebar.title("CBAM Credit Risk Engine")
st.sidebar.caption("Carbon border costs translated into PD, LGD, ECL and transition-loan sizing "
                   "for lenders to non-EU exporters.")

src = st.sidebar.radio("Loan book", ["Sample book (17 exporters)", "Upload CSV / XLSX"])
if src.startswith("Upload"):
    up = st.sidebar.file_uploader("Loan book file", type=["csv", "xlsx"])
    st.sidebar.download_button("Download CSV template", template_csv(), "loanbook_template.csv")
    if up is None:
        st.info("Upload a loan book or switch to the sample book.")
        st.stop()
    if up.name.endswith(".csv"):
        df_in = pd.read_csv(up)
    else:
        df_in = pd.read_excel(up)
    borrowers, errors = dataframe_to_borrowers(df_in)
else:
    borrowers, errors = load_loanbook("sample_data/loanbook_sample.csv")

for e in errors:
    st.sidebar.warning(e)
if not borrowers:
    st.error("No valid borrower rows.")
    st.stop()

st.sidebar.subheader("Scenario")
scen = st.sidebar.selectbox("EUA / certificate price path", list(PRICE_SCENARIOS),
                            index=1, format_func=lambda k: PRICE_SCENARIOS[k].name)
st.sidebar.caption(PRICE_SCENARIOS[scen].description)
pass_through = st.sidebar.slider("Default pass-through to EU buyer", 0.0, 1.0, 0.30, 0.05,
                                 help="Share of the certificate cost recovered through price. "
                                      "Borrower-level overrides in the file take precedence.")
elasticity = st.sidebar.slider("Demand elasticity (volume loss per 1% price rise)", 0.0, 2.0, 0.0, 0.1)

with st.sidebar.expander("Credit model parameters"):
    pd_el = st.slider("PD elasticity k (logit shift per unit cost/EBITDA)", 0.5, 5.0, 2.5, 0.25)
    lgd_s = st.slider("LGD sensitivity (per unit cost/EBITDA)", 0.0, 0.6, 0.25, 0.05)
    icr_floor = st.slider("ICR floor for extra penalty", 0.5, 2.0, 1.0, 0.1)
    sicr_ratio = st.slider("SICR trigger: PD ratio", 1.5, 4.0, 2.0, 0.25)
    disc = st.slider("Discount rate", 0.03, 0.15, 0.08, 0.01)
    rw = st.number_input("Risk weight (%)", 20.0, 250.0, 100.0, 10.0)

A = Assumptions(price_scenario=scen, default_pass_through=pass_through, demand_elasticity=elasticity,
                pd_elasticity=pd_el, lgd_sensitivity=lgd_s, icr_floor=icr_floor,
                sicr_pd_ratio=sicr_ratio, discount_rate=disc, risk_weight_pct=rw)

results = run_portfolio(borrowers, A)
tbl = results_table(results)
yt = year_table(results)
K = portfolio_kpis(results, A)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_p, tab_b, tab_s, tab_tf, tab_t, tab_m = st.tabs(
    ["Portfolio", "Borrower", "Scenarios", "Trade finance", "Transition finance", "Methodology and data"])

# ---------------- Portfolio -------------------------------------------------
with tab_p:
    st.subheader("Portfolio view")
    c = st.columns(5)
    c[0].metric("Total EAD", eur(K["total_ead"]))
    c[1].metric("EAD with EU exports", eur(K["ead_cbam_exposed"]),
                f"{K['ead_cbam_exposed']/K['total_ead']:.0%} of book")
    c[2].metric("Gross CBAM cost 2034", eur(K["gross_cbam_cost_2034"]),
                f"borne by borrowers: {eur(K['borne_cbam_cost_2034'])}")
    c[3].metric("12m ECL uplift 2034", eur(K["ecl_12m_delta_2034"]),
                f"{K['ecl_12m_delta_2034']/K['total_ead']*1e4:,.0f} bps of EAD", delta_color="inverse")
    c[4].metric("Stage 2 EAD 2034", eur(K["stage2_ead_2034"]), f"{K['stage2_share']:.0%} of book",
                delta_color="inverse")
    c = st.columns(4)
    c[0].metric("EAD-weighted PD, baseline", f"{K['wavg_pd_baseline']:.2%}")
    c[1].metric("EAD-weighted PD, 2034", f"{K['wavg_pd_2034']:.2%}")
    c[2].metric("Lifetime ECL uplift", eur(K["lifetime_ecl_delta"]))
    c[3].metric("High-risk EAD", eur(K["high_risk_ead"]))

    left, right = st.columns([3, 2])
    with left:
        agg = yt.groupby("year")[["gross_cost", "borne_cost", "ecl_delta"]].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(x=agg.year, y=agg.gross_cost, name="Gross CBAM cost", marker_color=PALETTE[0])
        fig.add_bar(x=agg.year, y=agg.borne_cost, name="Borne by borrowers", marker_color=PALETTE[1])
        fig.add_scatter(x=agg.year, y=agg.ecl_delta, name="12m ECL uplift", yaxis="y2",
                        mode="lines+markers", line=dict(color=PALETTE[3], width=3))
        fig.update_layout(barmode="group", title="CBAM cost and ECL uplift by year",
                          yaxis=dict(title="EUR"), yaxis2=dict(title="ECL uplift EUR", overlaying="y",
                                                                side="right"),
                          legend=dict(orientation="h", y=-0.2), height=420)
        st.plotly_chart(fig, width="stretch")
    with right:
        sec = sector_table(results, A)
        fig = px.bar(sec, x="sector", y="ecl_delta_bps_of_ead", color="sector",
                     color_discrete_sequence=PALETTE, title="2034 ECL uplift, bps of sector EAD",
                     labels={"ecl_delta_bps_of_ead": "bps", "sector": ""})
        fig.update_layout(showlegend=False, height=420)
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Heat map: borne CBAM cost as share of EBITDA**")
    heat = yt.pivot(index="name", columns="year", values="cost_to_ebitda")
    fig = px.imshow(heat, color_continuous_scale="YlOrRd", zmin=0, zmax=1.0, aspect="auto",
                    labels=dict(color="cost / EBITDA"))
    fig.update_layout(height=520, xaxis_title="", yaxis_title="")
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Borrower table (2034 point-in-time, selected scenario)**")
    show = tbl[["borrower_id", "name", "country", "sector", "route", "ead_eur", "embedded_intensity",
                "borne_cost_2034", "cost_to_ebitda_2034", "pd_baseline", "pd_2034",
                "rating_baseline", "rating_2034", "notches_down_2034", "lgd_2034", "stage_2034",
                "lifetime_ecl_delta", "risk_flag"]].copy()
    st.dataframe(show.style.format({
        "ead_eur": "{:,.0f}", "embedded_intensity": "{:.2f}", "borne_cost_2034": "{:,.0f}",
        "cost_to_ebitda_2034": "{:.1%}", "pd_baseline": "{:.2%}", "pd_2034": "{:.2%}",
        "lgd_2034": "{:.0%}", "lifetime_ecl_delta": "{:,.0f}"}), width="stretch", height=420)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame([K]).T.rename(columns={0: "value"}).to_excel(xw, sheet_name="portfolio_kpis")
        tbl.to_excel(xw, sheet_name="borrowers", index=False)
        yt.to_excel(xw, sheet_name="by_year", index=False)
        sector_table(results, A).to_excel(xw, sheet_name="sectors", index=False)
        pd.DataFrame([A.to_dict()]).T.rename(columns={0: "value"}).to_excel(xw, sheet_name="assumptions")
    st.download_button("Download results workbook (.xlsx)", buf.getvalue(), "cbam_credit_results.xlsx")

# ---------------- Borrower -------------------------------------------------
with tab_b:
    names = {f"{b.borrower_id}  {b.name}": b for b in borrowers}
    pick = st.selectbox("Borrower", list(names))
    b = names[pick]
    prod = PRODUCTS[b.product]

    st.markdown(f"**{b.name}** · {b.country} · {prod.sector} · route: "
                f"{prod.routes[b.route].name}")
    with st.expander("Override borrower inputs for this view"):
        c = st.columns(4)
        di = c[0].number_input("Direct intensity tCO2/t", 0.0, 25.0, float(b.direct_intensity), 0.05)
        ii = c[1].number_input("Indirect intensity tCO2/t", 0.0, 25.0, float(b.indirect_intensity), 0.05)
        pt = c[2].slider("Pass-through", 0.0, 1.0,
                         float(b.pass_through_rate if b.pass_through_rate is not None else pass_through), 0.05)
        dcp = c[3].number_input("Domestic carbon price EUR/t", 0.0, 200.0, float(b.domestic_carbon_price), 1.0)
        b = replace(b, direct_intensity_override=di, indirect_intensity_override=ii,
                    pass_through_rate=pt, domestic_carbon_price_override=dcp)
    r = assess_borrower(b, A)

    scope_note = ("direct + indirect emissions in scope" if (A.include_indirect and prod.indirect_in_scope)
                  else "direct emissions only in scope (Annex II)")
    c = st.columns(5)
    c[0].metric("Embedded intensity", f"{r.costs[0].embedded_intensity:.2f} tCO2/t", scope_note)
    c[1].metric("EU benchmark", f"{prod.benchmark_tco2_per_t:.3f} tCO2/t")
    c34 = r.credit[-1]
    c[2].metric("Borne cost 2034", eur(c34.borne_cost), f"{c34.borne_cost/b.ebitda_eur:.0%} of EBITDA")
    c[3].metric("PD 2034", f"{c34.pd_adj:.2%}", f"from {b.pd_baseline:.2%} ({c34.rating_baseline} → {c34.rating_adj})",
                delta_color="inverse")
    c[4].metric("Lifetime ECL uplift", eur(r.lifetime_ecl_delta), f"IFRS 9 stage {r.worst_stage} · {r.risk_flag} risk",
                delta_color="inverse")

    left, right = st.columns(2)
    with left:
        df = pd.DataFrame([{**vars(yc)} for yc in r.costs])
        fig = go.Figure()
        fig.add_bar(x=df.year, y=df.gross_cost, name="Gross certificate cost", marker_color=PALETTE[0])
        fig.add_bar(x=df.year, y=df.borne_cost, name="Borne after pass-through", marker_color=PALETTE[1])
        fig.add_scatter(x=df.year, y=df.phase_in, name="Phase-in share (1 − CBAM factor)", yaxis="y2", mode="lines+markers",
                        line=dict(color=PALETTE[4], dash="dot"))
        fig.update_layout(title="Certificate cost path", barmode="group", yaxis_title="EUR",
                          yaxis2=dict(title="Phase-in share", overlaying="y", side="right", range=[0, 1]),
                          legend=dict(orientation="h", y=-0.25), height=400)
        st.plotly_chart(fig, width="stretch")
    with right:
        dc = pd.DataFrame([{**vars(cc)} for cc in r.credit])
        fig = go.Figure()
        fig.add_scatter(x=dc.year, y=dc.pd_adj, name="PD (CBAM-adjusted)", mode="lines+markers",
                        line=dict(color=PALETTE[1], width=3))
        fig.add_scatter(x=dc.year, y=dc.pd_baseline, name="PD baseline", line=dict(color=PALETTE[0], dash="dash"))
        fig.add_scatter(x=dc.year, y=dc.icr_adj, name="ICR adjusted", yaxis="y2", line=dict(color=PALETTE[2]))
        fig.update_layout(title="PD and interest cover", yaxis=dict(title="PD", tickformat=".1%"),
                          yaxis2=dict(title="ICR (x)", overlaying="y", side="right"),
                          legend=dict(orientation="h", y=-0.25), height=400)
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Year-by-year detail**")
    detail = df[["year", "phase_in", "eua_price", "benchmark_free", "chargeable_intensity",
                 "cost_per_t", "gross_cost", "borne_cost", "cost_to_ebitda"]].merge(
        dc[["year", "ebitda_adj", "icr_adj", "leverage_adj", "pd_adj", "rating_adj", "lgd_adj",
            "ecl_adj", "ecl_delta", "stage"]], on="year")
    st.dataframe(detail.style.format({
        "phase_in": "{:.1%}", "eua_price": "€{:.0f}", "benchmark_free": "{:.3f}",
        "chargeable_intensity": "{:.3f}", "cost_per_t": "€{:.1f}", "gross_cost": "{:,.0f}",
        "borne_cost": "{:,.0f}", "cost_to_ebitda": "{:.1%}", "ebitda_adj": "{:,.0f}", "icr_adj": "{:.1f}",
        "leverage_adj": "{:.1f}", "pd_adj": "{:.2%}", "lgd_adj": "{:.0%}", "ecl_adj": "{:,.0f}",
        "ecl_delta": "{:,.0f}"}), width="stretch")

    st.markdown("---")
    st.markdown("**Climate multiplier: provision and collateral overlay**")
    st.caption("A model-light overlay for lenders without a PD satellite model, inspired by the BRSA Journal "
               "(Tagtekin, 2024) proposal to reflect CBAM in provisions and collateral. "
               "CM = min(cap, 1 + α × borne CBAM cost / EBITDA). The formula is this engine's own "
               "implementation, not a reproduction of the paper.")
    c = st.columns(4)
    cm_year = c[0].selectbox("Year", HORIZON_YEARS, index=HORIZON_YEARS.index(2030))
    cm_alpha = c[1].slider("α (sensitivity)", 0.25, 3.0, 1.0, 0.25)
    cm_cov = c[2].slider("Base collateral coverage of EAD", 0.5, 2.0, 1.0, 0.1)
    cm_cap = c[3].slider("Multiplier cap", 1.5, 5.0, 3.0, 0.5)
    cmr = climate_multiplier(b, A, cm_year, alpha=cm_alpha, coverage_ratio=cm_cov, cap=cm_cap)
    c = st.columns(4)
    c[0].metric("Climate multiplier", f"{cmr.multiplier:.2f}×")
    c[1].metric("Provision with multiplier", eur(cmr.provision_with_multiplier),
                f"+{eur(cmr.provision_overlay)} overlay", delta_color="inverse")
    c[2].metric("Collateral required", eur(cmr.collateral_required_cm),
                f"base {eur(cmr.collateral_required_base)}", delta_color="off")
    c[3].metric("Collateral top-up", eur(cmr.collateral_top_up), f"held {eur(cmr.collateral_held)}",
                delta_color="inverse" if cmr.collateral_top_up > 0 else "off")
    cm_rows = []
    for bb in borrowers:
        r_ = climate_multiplier(bb, A, cm_year, alpha=cm_alpha, coverage_ratio=cm_cov, cap=cm_cap)
        cm_rows.append({"borrower_id": bb.borrower_id, "name": bb.name, "multiplier": r_.multiplier,
                        "provision_base": r_.ecl_base, "provision_overlay": r_.provision_overlay,
                        "collateral_held": r_.collateral_held, "collateral_required": r_.collateral_required_cm,
                        "collateral_top_up": r_.collateral_top_up})
    with st.expander(f"Climate multiplier across the book ({cm_year})"):
        cmd = pd.DataFrame(cm_rows).sort_values("multiplier", ascending=False)
        st.dataframe(cmd.style.format({"multiplier": "{:.2f}", "provision_base": "{:,.0f}",
                                       "provision_overlay": "{:,.0f}", "collateral_held": "{:,.0f}",
                                       "collateral_required": "{:,.0f}", "collateral_top_up": "{:,.0f}"}),
                     width="stretch")
        st.markdown(f"Book total: provision overlay **{eur(cmd.provision_overlay.sum())}**, "
                    f"collateral top-up **{eur(cmd.collateral_top_up.sum())}**")

# ---------------- Trade finance ---------------------------------------------
with tab_tf:
    st.subheader("Trade finance: shipment-level carbon ledger")
    st.caption("CBAM's legal obligation sits with the EU declarant, but the cost flows back to the exporter "
               "through rebates and set-offs. Eligible receivables are reduced by the higher of calculated "
               "and default-value exposure, scaled by the contract carbon clause, plus a buffer.")
    tf_src = st.radio("Shipment ledger", ["Sample ledger (12 shipments)", "Upload CSV"], horizontal=True)
    if tf_src.startswith("Upload"):
        tf_up = st.file_uploader("Shipment ledger CSV", type=["csv"], key="tf_up")
        tmpl = pd.DataFrame(columns=list(Shipment.__dataclass_fields__)).to_csv(index=False)
        st.download_button("Download shipment template", tmpl, "shipments_template.csv")
        shipments, tf_errs = (load_shipments(tf_up) if tf_up else ([], []))
    else:
        shipments, tf_errs = load_shipments("sample_data/shipments_sample.csv")
    for e in tf_errs:
        st.warning(e)
    if not shipments:
        st.info("Upload a shipment ledger or use the sample.")
    else:
        with st.expander("Trade-finance assumptions", expanded=False):
            c = st.columns(4)
            stress = c[0].number_input("Stress certificate price (EUR/t)", 50.0, 250.0, 100.0, 5.0)
            pv_buf = c[1].slider("Pre-verified intensity buffer", 0.0, 0.3, 0.10, 0.01)
            el_buf = c[2].slider("Eligibility buffer", 0.0, 0.2, 0.05, 0.01)
            res_cov = c[3].slider("Funded reserve cover", 1.0, 1.5, 1.25, 0.05)
            st.markdown("Exporter share of CBAM cost by contract clause (judgement inputs):")
            cc = st.columns(len(CLAUSE_EXPORTER_SHARE))
            shares = {k: cc[i].slider(CLAUSE_LABELS[k], 0.0, 1.0, v, 0.05, key=f"cl_{k}")
                      for i, (k, v) in enumerate(CLAUSE_EXPORTER_SHARE.items())}
        TA = TFAssumptions(price_scenario=scen, stress_price=stress, pre_verified_buffer=pv_buf,
                           eligibility_buffer=el_buf, reserve_cover=res_cov, clause_share=shares)
        tfr = run_shipments(shipments, TA)
        tft = shipments_table(tfr)
        TK = tf_kpis(tfr)

        c = st.columns(5)
        c[0].metric("Invoice value", eur(TK["invoice_value"]), f"{TK['shipments']} shipments", delta_color="off")
        c[1].metric("CBAM exposure (declared)", eur(TK["exposure_declared"]),
                    f"default-value case {eur(TK['exposure_default'])}", delta_color="off")
        c[2].metric("Dilution", eur(TK["dilution"]), f"{TK['dilution_pct']:.1%} of invoices", delta_color="inverse")
        c[3].metric("Borrowing base, carbon-adjusted", eur(TK["borrowing_base_carbon"]),
                    f"−{eur(TK['borrowing_base_reduction'])} vs plain", delta_color="inverse")
        c[4].metric("Funded reserves (import loans)", eur(TK["funded_reserve"]))
        c = st.columns(3)
        c[0].metric("Stress exposure", eur(TK["exposure_stress"]), f"at ≥ €{stress:.0f}/t, default values",
                    delta_color="off")
        c[1].metric("Shipments without verified data", f"{TK['unverified_share']:.0%}")
        c[2].metric("Value of verification", eur(TK["value_of_verification"]),
                    "default-value cost avoided if emissions are verified", delta_color="off")

        left, right = st.columns(2)
        with left:
            vv = tft[["shipment_id", "exposure_if_verified", "exposure_default"]].melt(
                "shipment_id", var_name="case", value_name="EUR")
            vv["case"] = vv["case"].map({"exposure_if_verified": "Verified actual emissions",
                                         "exposure_default": "Default value + mark-up"})
            fig = px.bar(vv, x="shipment_id", y="EUR", color="case", barmode="group",
                         color_discrete_sequence=[PALETTE[2], PALETTE[1]],
                         title="Certificate exposure: verified vs default value")
            fig.update_layout(legend=dict(orientation="h", y=-0.25), height=420, xaxis_title="")
            st.plotly_chart(fig, width="stretch")
        with right:
            bb_df = tft[tft.borrowing_base_plain > 0][["shipment_id", "borrowing_base_plain",
                                                       "borrowing_base_carbon"]]
            fig = go.Figure()
            fig.add_bar(x=bb_df.shipment_id, y=bb_df.borrowing_base_plain, name="Plain borrowing base",
                        marker_color=PALETTE[0])
            fig.add_bar(x=bb_df.shipment_id, y=bb_df.borrowing_base_carbon, name="Carbon-adjusted",
                        marker_color=PALETTE[4])
            fig.update_layout(title="Advance capacity per shipment", barmode="group", yaxis_title="EUR",
                              legend=dict(orientation="h", y=-0.25), height=420)
            st.plotly_chart(fig, width="stretch")

        st.markdown("**Shipment ledger**")
        st.dataframe(tft[["shipment_id", "counterparty", "instrument", "product", "country", "year",
                          "verification", "clause", "intensity_used", "default_with_markup",
                          "exposure_declared", "exposure_default", "dilution", "dilution_pct_invoice",
                          "borrowing_base_plain", "borrowing_base_carbon", "funded_reserve",
                          "lc_discrepancy_risk"]].style.format({
            "intensity_used": "{:.2f}", "default_with_markup": "{:.2f}", "exposure_declared": "{:,.0f}",
            "exposure_default": "{:,.0f}", "dilution": "{:,.0f}", "dilution_pct_invoice": "{:.1%}",
            "borrowing_base_plain": "{:,.0f}", "borrowing_base_carbon": "{:,.0f}",
            "funded_reserve": "{:,.0f}"}), width="stretch", height=380)

        st.markdown("**Early-warning flags**")
        for _, row in tft[tft["flags"] != ""].iterrows():
            st.markdown(f"- **{row.shipment_id}** ({row.counterparty}): {row["flags"]}")

        st.markdown("**Recommended controls**")
        st.markdown("""
- Keep LCs on commercial and shipping documents; make an approved emissions-data package and pre-verification scope a **condition precedent** to utilisation instead of an LC document.
- Run the borrowing base on **carbon-adjusted eligible receivables**; check whether credit insurance excludes CBAM-related set-offs and rebates.
- For importer facilities, hold a **funded certificate reserve** of 100-125 % of the estimated liability, built from the import date, and keep liquidity covenants above the reserve.
- Trigger a revaluation and drawstop on: a gap between reported and verified emissions, repeated default values, loss of authorised-declarant status, or missing MRV data.
""")
        st.caption(f"Default values: {DEFAULT_SOURCE} Mark-ups: 10 % (2026), 20 % (2027), 30 % (2028+); "
                   f"fertilisers 1 %. Control logic follows practitioner guidance (cbam.engineer, 2026).")
        tf_buf = io.BytesIO()
        with pd.ExcelWriter(tf_buf) as xw:
            pd.DataFrame([TK]).T.rename(columns={0: "value"}).to_excel(xw, sheet_name="tf_kpis")
            tft.to_excel(xw, sheet_name="shipments", index=False)
        st.download_button("Download trade-finance workbook (.xlsx)", tf_buf.getvalue(), "cbam_trade_finance.xlsx")

# ---------------- Scenarios -------------------------------------------------
with tab_s:
    st.subheader("Price scenarios")
    sc = scenario_comparison(borrowers, A)
    c = st.columns(3)
    for i, row in sc.iterrows():
        c[i].metric(row.scenario, eur(row.ecl_12m_delta_2034),
                    f"Stage 2: {row.stage2_share:.0%} · gross cost {eur(row.gross_cbam_cost_2034)}",
                    delta_color="off")
    pp = pd.DataFrame({k: v.path for k, v in PRICE_SCENARIOS.items()}).reset_index().rename(columns={"index": "year"})
    fig = px.line(pp.melt("year", var_name="scenario", value_name="EUR/t"), x="year", y="EUR/t",
                  color="scenario", color_discrete_sequence=PALETTE, markers=True,
                  title="Assumed EUA / certificate price paths")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(sc.style.format({c_: "{:,.0f}" for c_ in sc.columns if c_ not in
                                  ("scenario", "borrowers", "stage2_share", "wavg_pd_baseline", "wavg_pd_2034")}
                                 | {"stage2_share": "{:.0%}", "wavg_pd_baseline": "{:.2%}", "wavg_pd_2034": "{:.2%}"}),
                 width="stretch")

    st.markdown("**Pass-through sensitivity (selected price scenario)**")
    rows = []
    for ptv in [0.0, 0.15, 0.30, 0.50, 0.70, 1.0]:
        a2 = replace(A, default_pass_through=ptv)
        bs2 = [replace(x, pass_through_rate=None) for x in borrowers]
        k2 = portfolio_kpis(run_portfolio(bs2, a2), a2)
        rows.append({"pass_through": ptv, "ecl_12m_delta_2034": k2["ecl_12m_delta_2034"],
                     "stage2_share": k2["stage2_share"], "wavg_pd_2034": k2["wavg_pd_2034"]})
    sens = pd.DataFrame(rows)
    fig = px.line(sens, x="pass_through", y="ecl_12m_delta_2034", markers=True,
                  title="ECL uplift vs pass-through (all borrower overrides removed)",
                  labels={"ecl_12m_delta_2034": "EUR", "pass_through": "pass-through share"},
                  color_discrete_sequence=PALETTE)
    st.plotly_chart(fig, width="stretch")

# ---------------- Transition finance -------------------------------------
with tab_t:
    st.subheader("Decarbonisation levers and transition-loan sizing")
    names_t = {f"{b_.borrower_id}  {b_.name}": b_ for b_ in borrowers if b_.eu_export_tonnes > 0}
    pick_t = st.selectbox("Borrower ", list(names_t))
    bt = names_t[pick_t]
    c = st.columns(3)
    cap_t = c[0].number_input("Capacity to retrofit (t/yr)", 0.0, 5e7, float(bt.eu_export_tonnes), 1000.0,
                              help="Defaults to EU export tonnes; set to full plant capacity if the whole "
                                   "line is converted.")
    tenor = c[1].slider("Loan tenor (years)", 3, 15, 8)
    rate = c[2].slider("Loan rate", 0.03, 0.15, 0.09, 0.005)
    levers = evaluate_all_levers(bt, A, capacity_tonnes=cap_t, loan_tenor_years=tenor, loan_rate=rate)
    if not levers:
        st.info("No levers catalogued for this product.")
    else:
        lt = pd.DataFrame([l.summary() for l in levers])
        st.dataframe(lt[["lever", "capex_eur", "annual_opex_delta_eur", "cumulative_avoided_cost", "npv_eur",
                         "simple_payback_years", "min_dscr", "pd_2034_before", "pd_2034_after",
                         "ecl_saving_for_lender", "viability"]].style.format({
            "capex_eur": "{:,.0f}", "annual_opex_delta_eur": "{:,.0f}", "cumulative_avoided_cost": "{:,.0f}",
            "npv_eur": "{:,.0f}", "min_dscr": "{:.2f}", "pd_2034_before": "{:.2%}", "pd_2034_after": "{:.2%}",
            "ecl_saving_for_lender": "{:,.0f}"}), width="stretch")
        best = levers[0]
        st.markdown(f"**Top lever by NPV: {best.lever.name}**  ·  loan size {eur(best.loan_size_eur)}  ·  "
                    f"{best.viability}")
        yrs = [yc.year for yc in assess_borrower(bt, A).costs]
        fig = go.Figure()
        fig.add_bar(x=yrs, y=best.avoided_cost_by_year, name="Avoided CBAM cost", marker_color=PALETTE[2])
        fig.add_scatter(x=yrs, y=best.net_benefit_by_year, name="Net benefit after opex delta",
                        line=dict(color=PALETTE[0], width=3))
        fig.add_scatter(x=yrs, y=[best.annuity_eur] * len(yrs), name="Debt service (annuity)",
                        line=dict(color=PALETTE[1], dash="dash"))
        fig.update_layout(title="Does the CBAM saving service the transition loan?", yaxis_title="EUR",
                          legend=dict(orientation="h", y=-0.25), height=420)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Lever source: {best.lever.source}. Capex and opex are literature ranges for structuring, "
                   f"not engineering estimates.")

# ---------------- Methodology -------------------------------------------
with tab_m:
    st.subheader("Methodology")
    st.markdown(r"""
**1. Certificate obligation per tonne (Reg. (EU) 2023/956, Arts. 9, 21, 22, 31)**

$\text{certificates}_t = \max\big(0,\; E_{\text{embedded}} - B \cdot CF_y\big)\cdot\big(1 - p_{\text{dom}}/P_y\big)$

* $E_{\text{embedded}}$: direct intensity, plus indirect where Annex II puts it in scope (cement, fertilisers, electricity).
* $B$: EU free-allocation benchmark (IR (EU) 2021/447, 2021-2025 values used as proxy).
* $CF_y$: CBAM factor, the share of free allocation that remains: 97.5 % in 2026 falling to 0 % in 2034 (Directive 2003/87/EC Art. 10a(1a)). Charts show its complement, the phase-in share $1-CF_y$.
* $P_y$: certificate price, equal to the previous quarter's average EUA auction price.
* $p_{\text{dom}}$: carbon price effectively paid in the country of origin, credited under Art. 9.

**2. Earnings shock.** Borne cost = gross cost × (1 − pass-through). EBITDA, ICR and leverage are restated.

**3. PD.** $\text{logit}(PD_y) = \text{logit}(PD_0) + k \cdot \frac{\text{borne cost}_y}{EBITDA_0} + \text{penalty}_{ICR<\text{floor}}$.
The link function mirrors supervisory climate stress tests (ECB 2022, BoE CBES) in which a sectoral cost shock is mapped to PD through a monotone function. $k$ must be calibrated to the lender's own migration history; the default is a placeholder.

**4. LGD.** $LGD_y = \min(\text{cap},\; LGD_0 + s \cdot \frac{\text{borne cost}_y}{EBITDA_0})$, the stranded-collateral channel (cf. BRSA Journal 2024 "climate multiplier" proposal).

**5. ECL and staging.** 12-month ECL = PD × LGD × EAD; lifetime ECL is the survival-weighted, discounted sum over remaining maturity. Stage 2 when PD ratio and absolute increase both exceed the SICR thresholds, or EBITDA turns negative.

**6. Transition finance.** For each catalogued lever, capex = unit capex × capacity; avoided cost is the difference in gross certificate cost from the lead-time year; NPV, payback and DSCR against an annuity on the capex are reported, with the post-lever PD and ECL.

**Limitations.** Default intensities are sectoral literature values, not installation MRV data. Benchmarks for 2026-2030 are pending Commission adoption. Pass-through is a judgement. No second-round effects (EU demand substitution, domestic price response) unless the demand-elasticity slider is set. Results are decision support, not a regulatory capital calculation.
""")
    st.subheader("Reference data in use")
    rows = []
    for p in PRODUCTS.values():
        for rt in p.routes.values():
            rows.append({"product": p.code, "sector": p.sector, "route": rt.name,
                         "direct_tCO2_t": rt.direct_intensity, "indirect_tCO2_t": rt.indirect_intensity,
                         "indirect_in_cbam_scope": p.indirect_in_scope,
                         "benchmark_tCO2_t": round(p.benchmark_tco2_per_t, 3), "confidence": rt.confidence,
                         "source": rt.source})
    st.dataframe(pd.DataFrame(rows), width="stretch", height=420)
    st.markdown("**CBAM factor and phase-in schedule**")
    st.dataframe(pd.DataFrame({"year": list(PHASE_IN),
                               "cbam_factor (free allocation remaining)": [1 - v for v in PHASE_IN.values()],
                               "phase_in (certificates required)": list(PHASE_IN.values())})
                 .style.format({"cbam_factor (free allocation remaining)": "{:.1%}",
                                "phase_in (certificates required)": "{:.1%}"}), width="content")
    st.markdown("**Lever catalogue**")
    st.dataframe(pd.DataFrame([vars(l) for l in sum((levers_for(p) for p in PRODUCTS), [])]),
                 width="stretch")
