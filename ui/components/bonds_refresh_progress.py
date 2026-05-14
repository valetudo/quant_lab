"""Streamlit progress UI for the bonds.db refresh.

Renders a panel whose contents change with the state file's ``status``:

- ``idle``      → just the "Aggiorna prezzi bonds" button.
- ``running``   → progress bar + current profile + ETA + Annulla button.
- ``completed`` → success banner + toast + summary + Chiudi button.
- ``failed``    → red error banner + traceback expander + Riprova/Chiudi.
- ``cancelled`` → amber banner + Chiudi button.

The caller wraps this in an auto-rerun loop while the refresh is running.
"""

from __future__ import annotations

import time

import streamlit as st

from core.data.refresh_bonds import (
    RefreshState,
    get_state,
    request_cancel,
    reset_state,
    start_refresh_async,
)


def format_duration(seconds: float) -> str:
    """Render ``seconds`` as ``Xs``, ``Xm Ys``, or ``Xh Ym Zs``."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m {seconds % 60}s"


def render_refresh_panel() -> bool:
    """Render the refresh panel and return ``True`` if the UI should auto-rerun.

    The caller is expected to ``time.sleep(2); st.rerun()`` if this returns
    ``True``, so the user sees progress without manual refresh.
    """
    state = get_state()
    handlers = {
        "idle": _render_idle,
        "running": _render_running,
        "completed": _render_completed,
        "failed": _render_failed,
        "cancelled": _render_cancelled,
    }
    handler = handlers.get(state.status, _render_idle)
    return handler(state)


# ---------- per-status handlers ----------


def _render_idle(_state: RefreshState) -> bool:
    if st.button(
        "🔄 Aggiorna prezzi bonds",
        type="primary",
        help="Lancia il refresh completo via Selenium (~5–10 min, 76 profili)",
        key="refresh_start_btn",
    ):
        started, msg = start_refresh_async()
        if started:
            st.success(msg)
            time.sleep(0.4)
            st.rerun()
        else:
            st.warning(msg)
    return False


def _render_running(state: RefreshState) -> bool:
    # Header banner.
    st.markdown(
        """
<div style="
    background-color: rgba(21, 101, 192, 0.10);
    border-left: 4px solid #1565C0;
    color: #1565C0;
    padding: 14px 16px;
    border-radius: 6px;
    margin-bottom: 14px;
">
  <b>🔄 Aggiornamento prezzi bonds in corso</b><br>
  <span style="font-size:0.9em;opacity:0.85;">
    Scraping da Borsa Italiana via Selenium. La pagina si aggiorna
    automaticamente — puoi anche navigare altrove, il refresh continua.
  </span>
</div>
""",
        unsafe_allow_html=True,
    )

    # Progress bar.
    pct = state.progress_pct
    st.progress(
        pct / 100.0,
        text=(
            f"{state.profiles_completed} / {state.profiles_total} profili "
            f"· {pct:.1f}%"
        ),
    )

    # Current profile + cancel.
    c1, c2 = st.columns([4, 1])
    with c1:
        label = state.current_profile_label or "Inizializzazione…"
        st.markdown(f"**📡 Profilo corrente**: {label}")
    with c2:
        if st.button(
            "❌ Annulla",
            use_container_width=True,
            key="refresh_cancel_btn",
        ):
            request_cancel()
            st.info(
                "Annullamento richiesto. Attendo il completamento del "
                "profilo corrente…"
            )
            time.sleep(0.4)
            st.rerun()

    # Metrics row.
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("⏱️ Tempo trascorso", format_duration(state.elapsed_seconds))
    eta = state.eta_seconds
    m2.metric(
        "⏳ Tempo rimanente",
        f"~{format_duration(eta)}" if eta is not None else "calcolando…",
    )
    m3.metric("✅ Bond salvati", f"{state.bonds_saved:,}")
    m4.metric(
        "⚠️ Errori",
        state.profiles_with_errors,
        delta=(
            f"{state.profiles_with_errors} profili"
            if state.profiles_with_errors > 0
            else None
        ),
        delta_color="off",
    )

    if state.recent_profiles:
        with st.expander("📋 Profili completati di recente", expanded=False):
            _render_profile_log(state.recent_profiles)

    return True


def _render_completed(state: RefreshState) -> bool:
    st.markdown(
        """
<div style="
    background-color: rgba(22, 163, 74, 0.10);
    border-left: 4px solid #16A34A;
    color: #166534;
    padding: 18px 18px;
    border-radius: 6px;
    margin-bottom: 14px;
">
  <h3 style="margin:0 0 6px 0;">✅ Aggiornamento completato</h3>
  <span style="opacity:0.85;">bonds.db aggiornato con successo.</span>
</div>
""",
        unsafe_allow_html=True,
    )

    if not st.session_state.get("refresh_toast_shown"):
        st.toast(
            f"✅ Aggiornamento completato: {state.bonds_saved:,} bond salvati",
            icon="🎉",
        )
        st.session_state["refresh_toast_shown"] = True

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("⏱️ Durata", format_duration(state.elapsed_seconds))
    m2.metric("📊 Profili", f"{state.profiles_completed} / {state.profiles_total}")
    m3.metric("✅ Bond salvati", f"{state.bonds_saved:,}")
    m4.metric(
        "⚠️ Errori",
        state.profiles_with_errors,
        delta_color="off",
    )

    if state.recent_profiles:
        with st.expander(
            f"📋 Log dei profili ({len(state.recent_profiles)} mostrati)",
            expanded=False,
        ):
            _render_profile_log(state.recent_profiles)

    error_profiles = [p for p in state.recent_profiles if p.get("error")]
    if error_profiles:
        with st.expander(f"⚠️ Profili con errori ({len(error_profiles)})", expanded=False):
            st.warning(
                "Alcuni profili hanno avuto problemi. I bond già salvati dagli altri "
                "profili non sono interessati. Puoi rilanciare il refresh in qualsiasi momento."
            )
            for p in error_profiles:
                st.markdown(f"- **{p['label']}** — {p['error']}")

    if st.button(
        "📊 Chiudi e torna al ladder",
        type="primary",
        key="refresh_dismiss_btn",
    ):
        reset_state()
        st.session_state.pop("refresh_toast_shown", None)
        st.rerun()
    return False


def _render_failed(state: RefreshState) -> bool:
    st.markdown(
        """
<div style="
    background-color: rgba(220, 38, 38, 0.10);
    border-left: 4px solid #DC2626;
    color: #991B1B;
    padding: 18px 18px;
    border-radius: 6px;
    margin-bottom: 14px;
">
  <h3 style="margin:0 0 6px 0;">❌ Aggiornamento fallito</h3>
  <span style="opacity:0.85;">Lo scraping ha incontrato un errore irrecuperabile.</span>
</div>
""",
        unsafe_allow_html=True,
    )

    if state.bonds_saved > 0:
        st.info(
            f"📊 **Risultati parziali salvati**: {state.bonds_saved:,} bond "
            "aggiornati prima dell'errore. I dati sono comunque utilizzabili."
        )

    if state.fatal_error:
        with st.expander("🔍 Dettaglio errore", expanded=True):
            st.code(state.fatal_error)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔁 Riprova", type="primary", key="refresh_retry_btn"):
            reset_state()
            st.session_state.pop("refresh_toast_shown", None)
            started, msg = start_refresh_async()
            if started:
                st.rerun()
            else:
                st.error(msg)
    with c2:
        if st.button("❌ Chiudi", key="refresh_failed_dismiss_btn"):
            reset_state()
            st.session_state.pop("refresh_toast_shown", None)
            st.rerun()
    return False


def _render_cancelled(state: RefreshState) -> bool:
    st.markdown(
        """
<div style="
    background-color: rgba(217, 119, 6, 0.10);
    border-left: 4px solid #D97706;
    color: #92400E;
    padding: 18px 18px;
    border-radius: 6px;
    margin-bottom: 14px;
">
  <h3 style="margin:0 0 6px 0;">⚠️ Aggiornamento annullato</h3>
  <span style="opacity:0.85;">L'operazione è stata interrotta dall'utente.</span>
</div>
""",
        unsafe_allow_html=True,
    )

    if state.bonds_saved > 0:
        st.info(
            f"📊 **Risultati parziali**: {state.bonds_saved:,} bond aggiornati "
            "prima dell'annullamento."
        )

    if st.button("❌ Chiudi", key="refresh_cancelled_dismiss_btn"):
        reset_state()
        st.session_state.pop("refresh_toast_shown", None)
        st.rerun()
    return False


# ---------- helpers ----------


def _render_profile_log(rows: list[dict]) -> None:
    for p in rows:
        emoji = "❌" if p.get("error") else "✅"
        text = (
            f"{emoji} **{p.get('label', p.get('name', '?'))}** — "
            f"{p.get('rows', 0)} bond trovati, {p.get('saved', 0)} salvati"
        )
        if p.get("error"):
            text += f" — *Errore*: {p['error']}"
        st.markdown(text)
