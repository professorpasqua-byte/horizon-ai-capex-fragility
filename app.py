import streamlit as st

from dashboard.data import headline, region_index_by_week

st.set_page_config(page_title="Horizon: AI budget and infrastructure fragility", layout="wide")
h = headline()

st.title("Do stretched teams break systems?")
st.write(
    "Horizon is a fictional tech company with about 245,000 hourly infrastructure records, plus team "
    "capacity, overtime, tickets and budget data. It moves budget from core maintenance into AI, region "
    "by region. Because the simulation's real answer is known, this project grades its own findings."
)

c = st.columns(4)
c[0].metric("Tipping point found", f"{h['tipping_ratio']:.2f}", help="Capacity-to-load ratio where outages start to climb")
c[1].metric("Lead time", f"{h['lag_weeks']} weeks", help="Outages respond to strain this many weeks later")
c[2].metric("Outages with no ticket", f"{h['unticketed']} of {h['episodes']}")
c[3].metric("Self-grade", f"{h['hits']} of {h['total']}")

st.subheader("Capacity against demand, by region")
st.line_chart(region_index_by_week())
st.caption(
    "1.0 is where each team started. The three regions that move budget into AI fall one after another. "
    "latam-central, the protected control region, holds steady."
)
st.info("Use the pages on the left: the tipping point, a budget view for executives, the ticket gap, and how the project grades itself.")
