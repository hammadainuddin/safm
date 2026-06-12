"""
Global CSS for the app. Injected once per rerun from the entry script,
before nav.run(). Selectors are restricted to stable [data-testid] /
[data-baseweb] hooks so a Streamlit upgrade degrades gracefully
(cosmetics only) rather than breaking the app.
"""

from __future__ import annotations

import streamlit as st

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stSidebar"] {
    font-family: 'Inter', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
}

/* Hide Streamlit chrome */
#MainMenu, footer { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #FFFFFF 0%, #F6F9FC 100%);
    border-right: 1px solid #E3E8EF;
}
[data-testid="stSidebarNav"] a span { font-weight: 500; }
[data-testid="stNavSectionHeader"] {
    text-transform: uppercase;
    letter-spacing: .08em;
    font-size: .72rem;
    color: #5C677D;
}

/* Headings */
h1 { font-weight: 700; letter-spacing: -0.02em; color: #1A2B3C; }
h2, h3 { font-weight: 600; letter-spacing: -0.01em; color: #1A2B3C; }

/* Metric cards */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #E3E8EF;
    border-radius: 10px;
    padding: 14px 16px 12px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, .05);
}
[data-testid="stMetricLabel"] { color: #5C677D; }

/* Inner tabs: clean underline */
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #0077B6;
    font-weight: 600;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    background-color: #0077B6;
    height: 3px;
}
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    background-color: #E3E8EF;
}

/* Expanders and buttons: consistent radius */
[data-testid="stExpander"] details {
    border: 1px solid #E3E8EF;
    border-radius: 10px;
}
.stButton button { border-radius: 8px; }

/* Bordered containers: subtle card look */
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
    border-radius: 10px;
}
"""


def inject() -> None:
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)
