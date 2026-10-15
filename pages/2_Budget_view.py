import streamlit as st

from dashboard.data import START_RATIO, budget_view, headline

st.set_page_config(page_title="Budget view", layout="wide")
h = headline()
st.title("What happens as budget moves into AI")

view = budget_view()
shares = [float(x) for x in view.index]
pick = st.select_slider("Share of the total budget moved to AI", options=shares, value=shares[len(shares) // 2],
                        format_func=lambda x: f"{x * 100:.0f}%")
row = view.loc[pick]
ratio = float(row.capacity_index) * START_RATIO

c = st.columns(4)
c[0].metric("Capacity vs demand", f"{ratio:.2f}")
c[1].metric("Outages per team-week", f"{row.outages_per_team_week:.2f}")
c[2].metric("Overtime hours per person", f"{row.overtime_hours:.1f}")
c[3].metric("Team-weeks observed", f"{int(row.team_weeks)}")

if ratio < h["tipping_ratio"]:
    st.error(f"Past the tipping point ({h['tipping_ratio']:.2f}). Teams here are stretched enough that outages climb after a delay of about {h['lag_weeks']} weeks.")
else:
    st.success(f"Above the tipping point ({h['tipping_ratio']:.2f}). Strain is not yet driving outages.")

st.subheader("All levels side by side")
show = view.copy()
show.index = [f"{x * 100:.0f}%" for x in show.index]
st.dataframe(show.round(2))
st.caption("Averages over team-weeks in the simulation. Shares of budget are shown as known at the time, so the first weeks of each quarter lag.")
