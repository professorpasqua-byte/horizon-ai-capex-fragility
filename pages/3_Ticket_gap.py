import streamlit as st

from dashboard.data import headline, team_filing
from dashboard.style import INDIGO, header

st.set_page_config(page_title="Ticket gap", layout="wide")
h = headline()
header("Outages that never become a ticket", "Real outages, found in the telemetry, that nobody filed a ticket for.")

c = st.columns(3)
c[0].metric("Filed, low-safety teams", f"{h['low_rate'] * 100:.0f}%")
c[1].metric("Filed, high-safety teams", f"{h['high_rate'] * 100:.0f}%")
c[2].metric("Detected outages with no ticket", f"{h['unticketed']} of {h['episodes']}")
st.write(
    "Outages are detected from telemetry, then matched to tickets on the same cluster. "
    "Teams that report low psychological safety in the monthly pulse survey file fewer tickets, "
    f"so a ticket count alone understates their trouble. The gap is {(h['high_rate'] - h['low_rate']) * 100:.0f} points "
    f"(interval {h['rate_gap_ci'][0] * 100:.0f} to {h['rate_gap_ci'][1] * 100:.0f})."
)

t = team_filing()
t["team"] = ["team " + str(int(x)) for x in t.team_id]
st.subheader("Filing rate by team")
st.bar_chart(t.set_index("team")[["filing_rate"]], color=INDIGO)
st.subheader("Survey safety score and outages")
st.dataframe(t[["team", "episodes", "ticketed", "filing_rate", "safety_score", "low_safety"]].round(2))
st.caption("Safety score is the team's average on a 1 to 5 scale. Below 3 counts as low.")
