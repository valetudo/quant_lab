"""Aggiorna Posizioni — workflow per chi ha già investimenti.

Manual entry + manual removal of bond + ETF positions. The unified
:class:`PositionTracker` is the single source of truth; both add and
remove flows go through it. Duplicate-ISIN protection: any active row
must be removed (soft-delete) before re-adding the same ISIN.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from portfolio.position_tracker import PositionTracker
from portfolio.price_provider import PriceProvider

st.set_page_config(page_title="Aggiorna Posizioni", page_icon="📥", layout="wide")
st.title("📥 Aggiorna posizioni esistenti")
st.markdown(
    "Inserisci, modifica o rimuovi bond e ETF posseduti. Il sistema "
    "calcola la tua asset allocation attuale."
)

tracker = PositionTracker()

tab_b, tab_e, tab_a = st.tabs(["💰 Bonds", "🌍 Equity ETF", "🎯 Alternative"])


def _removal_ui(positions: list, label_fn, key_prefix: str) -> None:
    """Generic remove-position widget. Two-step confirmation."""
    if not positions:
        return
    st.subheader("🗑️ Rimuovi posizione")
    st.caption(
        "La rimozione è soft: la posizione viene marcata come `sold` "
        "(o altro motivo) ma resta nello storico."
    )

    options = ["—"] + [label_fn(p) for p in positions]
    selected = st.selectbox(
        "Posizione da rimuovere",
        options=options,
        key=f"{key_prefix}_to_remove",
    )

    if selected == "—":
        return

    idx = options.index(selected) - 1
    pos = positions[idx]

    c1, c2 = st.columns([1, 3])
    with c1:
        reason = st.selectbox(
            "Motivo",
            ["sold", "matured", "error_correction"],
            key=f"{key_prefix}_reason",
        )
    with c2:
        confirm_key = f"{key_prefix}_confirming"
        if not st.session_state.get(confirm_key):
            if st.button(
                f"🗑️ Rimuovi {pos.isin}",
                key=f"{key_prefix}_step1",
            ):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning(
                f"⚠️ Confermi la rimozione di **{pos.name}** "
                f"({pos.isin}) con motivo `{reason}`?"
            )
            cc1, cc2 = st.columns(2)
            if cc1.button("✅ Sì, rimuovi", type="primary", key=f"{key_prefix}_yes"):
                tracker.remove_position(pos.isin, reason=reason)
                st.session_state.pop(confirm_key, None)
                st.success(f"✅ Rimossa: {pos.name}")
                st.rerun()
            if cc2.button("❌ Annulla", key=f"{key_prefix}_no"):
                st.session_state.pop(confirm_key, None)
                st.rerun()


# ----- BONDS -----

with tab_b:
    st.subheader("Inserisci un bond posseduto")

    with st.form("add_bond_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            isin = st.text_input("ISIN", placeholder="IT0005XXXXXX")
            name = st.text_input("Descrizione", placeholder="BTP 4.5% 2030")
            issuer = st.text_input(
                "Emittente",
                placeholder="Repubblica Italiana",
                help="Per i governativi italiani: 'Repubblica Italiana'.",
            )
        with c2:
            quantity = st.number_input(
                "Valore nominale (€)",
                min_value=1000.0,
                step=1000.0,
                value=10_000.0,
                help=(
                    "Il valore nominale totale del bond che possiedi (es. €10.000 "
                    "= 10 lotti da €1.000 face value). NON è il numero di lotti."
                ),
            )
            avg_price = st.number_input(
                "Prezzo medio acquisto (% face)", value=100.0, step=0.01, format="%.2f"
            )
            purchase_date = st.date_input("Data acquisto", value=date.today())
        with c3:
            maturity_date = st.date_input(
                "Data scadenza",
                value=date(date.today().year + 5, 1, 15),
            )
            coupon_pct = st.number_input(
                "Cedola annuale (%)", value=3.0, step=0.01, format="%.2f"
            )
            ytm_pct = st.number_input(
                "YTM all'acquisto (%, opzionale)", value=0.0, step=0.01, format="%.2f"
            )
            rating = st.text_input("Rating (opzionale)", placeholder="BBB")

        if st.form_submit_button("➕ Aggiungi bond", type="primary"):
            if not isin:
                st.error("ISIN obbligatorio.")
            else:
                try:
                    tracker.add_bond(
                        isin=isin,
                        name=name or isin,
                        quantity=quantity,
                        avg_purchase_price=avg_price,
                        purchase_date=purchase_date,
                        issuer=issuer or None,
                        maturity_date=maturity_date,
                        coupon_rate=coupon_pct / 100.0,
                        coupon_frequency=1,
                        ytm_at_purchase=(ytm_pct / 100.0 if ytm_pct > 0 else None),
                        rating=rating or None,
                    )
                    st.success(f"✅ Aggiunto: {name or isin}")
                    st.rerun()
                except ValueError as e:
                    st.error(f"❌ {e}")

    bonds = tracker.get_by_asset_class("bond")
    if bonds:
        st.subheader(f"Bond nel portfolio ({len(bonds)})")
        df = pd.DataFrame([p.to_dict() for p in bonds])
        st.dataframe(df, use_container_width=True, hide_index=True)

        _removal_ui(
            bonds,
            label_fn=lambda p: (
                f"{p.isin} — {p.name} (€{p.quantity:,.0f} nominal @ "
                f"{p.avg_purchase_price:.2f})"
            ),
            key_prefix="bond",
        )
    else:
        st.info("Nessun bond ancora inserito.")

# ----- EQUITY -----

with tab_e:
    st.subheader("Inserisci un ETF posseduto")

    with st.form("add_equity_form"):
        c1, c2 = st.columns(2)
        with c1:
            e_isin = st.text_input("ISIN ETF", placeholder="IE00BK5BQT80 (VWCE)")
            e_name = st.text_input("Nome ETF", placeholder="Vanguard FTSE All-World")
        with c2:
            e_qty = st.number_input("Quote possedute", min_value=1, step=1, value=10)
            e_price = st.number_input(
                "Prezzo medio acquisto (€/quota)",
                min_value=0.01,
                step=0.01,
                value=120.0,
                format="%.2f",
            )
            e_date = st.date_input("Data acquisto", value=date.today(), key="eq_date")

        if st.form_submit_button("➕ Aggiungi ETF", type="primary"):
            if not e_isin:
                st.error("ISIN obbligatorio.")
            else:
                try:
                    tracker.add_equity(
                        isin=e_isin,
                        name=e_name or e_isin,
                        quantity=e_qty,
                        avg_purchase_price=e_price,
                        purchase_date=e_date,
                    )
                    st.success(f"✅ Aggiunto: {e_name or e_isin}")
                    st.rerun()
                except ValueError as e:
                    st.error(f"❌ {e}")

    eq = tracker.get_by_asset_class("equity")
    if eq:
        st.subheader(f"ETF nel portfolio ({len(eq)})")
        df = pd.DataFrame([p.to_dict() for p in eq])
        st.dataframe(df, use_container_width=True, hide_index=True)

        _removal_ui(
            eq,
            label_fn=lambda p: (
                f"{p.isin} — {p.name} ({p.quantity:.0f} quote @ €{p.avg_purchase_price:.2f})"
            ),
            key_prefix="equity",
        )
    else:
        st.info("Nessun ETF ancora inserito.")

# ----- ALTERNATIVE -----

with tab_a:
    alt = tracker.get_by_asset_class("alternative")
    if alt:
        st.subheader(f"Strategie alternative attive ({len(alt)})")
        df = pd.DataFrame([p.to_dict() for p in alt])
        st.dataframe(
            df[
                [
                    "isin",
                    "name",
                    "strategy_id",
                    "quantity",
                    "avg_purchase_price",
                    "purchase_date",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
        _removal_ui(
            alt,
            label_fn=lambda p: (
                f"{p.strategy_id} — €{p.avg_purchase_price:,.0f} "
                f"dal {pd.Timestamp(p.purchase_date).date().isoformat()}"
            ),
            key_prefix="alt",
        )
    else:
        st.info(
            "Le strategie alternative si attivano dalla pagina "
            "**🎯 Alternative Strategies** del menù laterale."
        )

# ----- live allocation -----

st.markdown("---")
st.subheader("📊 Asset allocation attuale")

positions = tracker.get_all()
if positions:
    prices = PriceProvider().get_prices(positions)
    values = tracker.current_value_eur(prices)
    total = values["total"] or 1.0
    a, b, c, d = st.columns(4)
    a.metric(
        "💰 Bonds",
        f"€{values['bond']:,.0f}",
        f"{values['bond'] / total * 100:.1f}%",
    )
    b.metric(
        "🌍 Equity",
        f"€{values['equity']:,.0f}",
        f"{values['equity'] / total * 100:.1f}%",
    )
    c.metric(
        "🎯 Alternative",
        f"€{values['alternative']:,.0f}",
        f"{values['alternative'] / total * 100:.1f}%",
    )
    d.metric("📊 Totale", f"€{values['total']:,.0f}")
else:
    st.info("Inserisci almeno una posizione per vedere l'asset allocation.")

# ----- destructive reset -----

st.markdown("---")
with st.expander("⚠️ Reset completo portfolio", expanded=False):
    st.warning(
        "Questa azione marca **tutte** le posizioni attive come `reset` (soft-delete). "
        "Utile per ripartire da zero dopo dati di test. Viene fatto un backup "
        "del parquet prima della modifica."
    )
    confirm_text = st.text_input(
        "Per confermare scrivi `RESET` qui sotto",
        key="reset_text",
        placeholder="RESET",
    )
    if confirm_text == "RESET":
        if st.button(
            "🗑️ ESEGUI RESET (operazione non distruttiva, solo soft-delete)",
            type="primary",
        ):
            path = (
                _PROJECT_ROOT
                / "data_storage"
                / "positions"
                / "portfolio_positions.parquet"
            )
            if path.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = path.parent / f"positions_reset_backup_{ts}.parquet"
                shutil.copy(path, backup)
                st.info(f"📁 Backup salvato: `{backup.name}`")
                for p in tracker.get_all():
                    tracker.remove_position(p.isin, reason="reset")
                st.success("✅ Portfolio resettato.")
                st.rerun()
            else:
                st.info("Nessun parquet da resettare.")
