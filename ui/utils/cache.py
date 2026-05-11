"""Streamlit cache helpers."""

from __future__ import annotations

import streamlit as st

from core.data.storage import DataStorage, load_global_config


@st.cache_resource(show_spinner=False)
def get_storage() -> DataStorage:
    return DataStorage.from_config(load_global_config())


@st.cache_data(show_spinner=False, ttl=300)
def cached_universe_meta():
    s = get_storage()
    return s.load_universe_meta()


@st.cache_data(show_spinner=False, ttl=300)
def cached_known_tickers():
    s = get_storage()
    return s.list_known_tickers()
