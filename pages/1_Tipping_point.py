import streamlit as st

from dashboard.data import episodes_by_region_week, findings, headline, read_csv

st.set_page_config(page_title="Tipping point", layout="wide")
h, f = headline(), findings()
st.title("Where outages start to climb")

c = st.columns(3)
c[0].metric("Tipping point found", f"{h['tipping_ratio']:.2f}", help="Ratio of people to workload")
c[1].metric("Planted in the simulation", f"{h['true_tipping_ratio']:.2f}")
c[2].metric("Lead time", f"{h['lag_weeks']} weeks", help=f"Interval {h['lag_ci'][0]} to {h['lag_ci'][1]} weeks")

st.write(
    f"The method puts the tipping point at {h['tipping_ratio']:.2f} (interval {h['tipping_ci'][0]:.2f} to "
    f"{h['tipping_ci'][1]:.2f}). The planted value is {h['true_tipping_ratio']:.2f}, so this one is a miss: "
    "the estimate runs a little high. The lead time is found exactly."
)

st.subheader("How well each tipping point fits the data")
prof = read_csv("tipping_profile.csv").set_index("knot")
st.line_chart(prof.rename(columns={"loglik_drop": "fit (0 is best)"}))
st.caption("Higher is a better fit. Points within about 2 of the top cannot be told apart.")

st.subheader("How long after the strain do outages respond")
st.bar_chart(read_csv("lead_time_profile.csv").set_index("lag_weeks").rename(columns={"loglik_drop": "fit (0 is best)"}))

st.subheader("Detected outages per week, by region")
st.line_chart(episodes_by_region_week())
st.caption(f"Overdispersion {f['tipping']['overdispersion']:.2f}. Outages are detected from telemetry, so they do not depend on anyone filing a ticket.")
