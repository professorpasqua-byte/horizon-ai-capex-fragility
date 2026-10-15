import streamlit as st

from dashboard.data import headline, read_csv

st.set_page_config(page_title="Grading and limits", layout="wide")
h = headline()
st.title("How the project grades itself")
st.write(
    "The simulation was built with a known answer. After the models run, each finding is compared with it. "
    f"This run: {h['hits']} of {h['total']} checks hit."
)
g = read_csv("grading.csv")
g["verdict"] = g["verdict"].str.upper()
g["found"], g["truth"] = g["found"].astype(str), g["truth"].astype(str)
st.dataframe(g[["verdict", "metric", "found", "truth", "note"]].fillna(""))

st.subheader("Where the method misses")
st.write(
    "The tipping point is the weak spot. It is estimated from a stand-in for workload (CPU use), "
    "not the real workload, so it can drift and its interval can be too narrow. Across 8 simulated "
    "worlds it landed within 0.05 of the planted value in 5, and the lead time was right in 7."
)

st.subheader("Data quality checks")
st.dataframe(read_csv("dq_report.csv"))
st.subheader("What the cleaning step fixed")
st.dataframe(read_csv("cleaning_report.csv"))
