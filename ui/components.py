"""
Reusable UI building blocks shared by every page.

These take loader/saver callables rather than touching data paths directly,
so this module stays free of data/mock knowledge and circular imports.
"""

from __future__ import annotations

import os
from typing import Callable, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st


def plotly_chart(fig, **kwargs) -> None:
    """st.plotly_chart with the app's own Plotly template in full control.

    theme=None stops Streamlit's frontend from overriding the registered
    'saf' template (fonts, colorway) at render time.
    """
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("theme", None)
    st.plotly_chart(fig, **kwargs)


def page_header(title: str, subtitle: str = "") -> None:
    """Page title + muted subtitle. Used once at the top of every page."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def methodology(body_md: str, title: str = "Methodology") -> None:
    """Collapsed expander holding the methodology prose for a section."""
    with st.expander(title, icon=":material/info:", expanded=False):
        st.markdown(body_md)


def upload_controls(
    csv_name: str,
    ss_key: str,
    df_loader: Callable[[str], pd.DataFrame],
    template_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compact import controls: download-template button + CSV uploader inside
    a collapsed expander. Returns the working DataFrame with priority:
      1. newly uploaded file  2. prior upload in session state  3. on-disk CSV.

    Widget keys (_dl_{ss_key} / _up_{ss_key}) match the legacy _upload_widget
    so session state survives this refactor.
    """
    with st.expander("Import data", icon=":material/upload_file:", expanded=False):
        if template_path and os.path.exists(template_path):
            with open(template_path, "rb") as f:
                tmpl_bytes = f.read()
            st.download_button(
                label=f"Download template ({csv_name})",
                data=tmpl_bytes,
                file_name=csv_name,
                mime="text/csv",
                key=f"_dl_{ss_key}",
                icon=":material/download:",
                help="Download the baseline template CSV as a starting point.",
            )
        uploaded = st.file_uploader(
            f"Upload replacement CSV for {csv_name}",
            type="csv",
            key=f"_up_{ss_key}",
            help="Upload a CSV with the same columns as the existing table. "
                 "The uploaded data will populate the editor below — review, then click Save.",
        )
        if uploaded is not None:
            try:
                st.session_state[ss_key] = pd.read_csv(uploaded)
                st.success(
                    f"CSV loaded ({len(st.session_state[ss_key])} rows). "
                    "Review below and click **Save** to apply."
                )
            except Exception as exc:
                st.error(f"Could not parse CSV: {exc}")
    return st.session_state.get(ss_key, df_loader(csv_name))


def editor_with_save(
    df: pd.DataFrame,
    csv_name: str,
    ss_key: str,
    df_saver: Callable[[pd.DataFrame, str], None],
    save_label: str,
    button_key: str,
    editor_key: Optional[str] = None,
    column_config: Optional[dict] = None,
    num_rows: str = "dynamic",
    in_expander: bool = True,
    expander_label: str = "Edit table",
) -> None:
    """
    st.data_editor + Save button. On save: persists via df_saver, clears any
    upload override in session state, and shows a toast.
    """
    def _editor_and_button() -> None:
        kwargs = dict(use_container_width=True, num_rows=num_rows)
        if editor_key:
            kwargs["key"] = editor_key
        if column_config:
            kwargs["column_config"] = column_config
        edited = st.data_editor(df, **kwargs)
        if st.button(save_label, key=button_key, icon=":material/save:", type="primary"):
            df_saver(edited, csv_name)
            st.session_state.pop(ss_key, None)
            st.toast(f"{csv_name} saved", icon=":material/check_circle:")

    if in_expander:
        with st.expander(expander_label, icon=":material/edit:"):
            _editor_and_button()
    else:
        _editor_and_button()


def metric_row(metrics: Sequence[Tuple[str, str, Optional[str]]]) -> None:
    """Row of st.metric cards: (label, value, delta-or-None) per entry."""
    cols = st.columns(len(metrics))
    for col, (label, value, delta) in zip(cols, metrics):
        with col:
            st.metric(label, value, delta=delta)


def empty_state(
    message: str,
    cta_page_key: Optional[str] = None,
    cta_label: str = "Go to Run Model",
) -> None:
    """Bordered placeholder with an optional link to another page."""
    with st.container(border=True):
        st.markdown(f":material/insights: &nbsp; {message}")
        if cta_page_key:
            page = st.session_state.get("_pages", {}).get(cta_page_key)
            if page is not None:
                st.page_link(page, label=cta_label, icon=":material/arrow_forward:")
