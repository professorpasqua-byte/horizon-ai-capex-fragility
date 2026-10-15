"""Look and feel shared by every page. Colors match the project site."""

import streamlit as st

INDIGO, INK = "#2B2A66", "#1B1A45"
REGION_COLORS = ["#2B2A66", "#5B58B8", "#8E8CD6", "#7A7A8C"]  # na-east, eu-west, apac-south, control
KNOT_COLOR = "#E0A100"


def header(title, subtitle=""):
    st.markdown(
        f"""<div style="background:{INDIGO};padding:1.6rem 1.5rem 1.9rem;border-radius:18px 18px 70px 18px;margin-bottom:1.2rem">
<div style="color:#B9B8E6;font-size:.8rem;letter-spacing:.12em;font-weight:600">HORIZON</div>
<div style="color:#FFFFFF;font-size:2rem;font-weight:700;line-height:1.2;margin:.35rem 0 .5rem">{title}</div>
<div style="color:#D9D8F0;font-size:1rem;line-height:1.5;max-width:46rem">{subtitle}</div></div>""",
        unsafe_allow_html=True,
    )
