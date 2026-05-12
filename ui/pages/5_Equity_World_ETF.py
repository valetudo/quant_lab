"""Equity — World ETF selection guide.

VWCE-first banner + comparison table + purchase form that writes into the
unified PositionTracker. Includes fiscal notes for the Italian retail
investor.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from portfolio.position_tracker import PositionTracker

st.set_page_config(page_title="Equity — World ETF", page_icon="🌍", layout="wide")
st.title("🌍 Equity — World ETF")
st.caption("Guida alla scelta dell'ETF globale ottimale per investitori italiani")

# ----- big banner -----

st.markdown(
    """
<div style="background: linear-gradient(135deg, #1565C0 0%, #1976D2 100%);
            padding: 26px; border-radius: 10px; color: white;">
  <h2 style="margin-top:0;">🏆 Raccomandato: <b>VWCE</b></h2>
  <h3 style="margin: 5px 0;">Vanguard FTSE All-World UCITS ETF (Accumulating)</h3>
  <p style="font-size: 16px; margin-bottom: 0;">
    ISIN: <b>IE00BK5BQT80</b> &nbsp;·&nbsp; TER <b>0.19%</b> &nbsp;·&nbsp;
    AUM <b>€37B+</b> &nbsp;·&nbsp; Quotato su <b>Borsa Italiana (VWCE.MI)</b> in EUR
  </p>
</div>
""",
    unsafe_allow_html=True,
)
st.markdown("")

# ----- rationale -----

with st.expander("📚 Perché VWCE? (motivazione completa)", expanded=True):
    st.markdown(
        """
**Cinque ragioni concrete per cui VWCE è la scelta ottimale per
investitore retail italiano:**

### 1. Vera diversificazione globale
VWCE traccia il **FTSE All-World Index**: ~3700 aziende in 47 paesi, inclusi
sviluppati (USA, Europa, Giappone) ed emerging markets (Cina, India,
Brasile). Una sola posizione, esposizione mondiale.

Alternative come CSPX (S&P 500 USA) o IWDA (MSCI World developed only)
escludono emerging markets, che pesano ~25% del PIL globale.

### 2. Costo ridotto
**TER 0.19%** (ridotto da 0.22% nell'ottobre 2025). Tra i più bassi della
categoria global UCITS. Su €30k investiti, il costo annuo è ~€57.

### 3. Accumulazione (tax-efficient per Italia)
VWCE è **accumulating**: i dividendi vengono reinvestiti automaticamente
dentro l'ETF. Per la fiscalità italiana questo è importante:

- **ETF accumulazione**: nessuna tassazione sui dividendi reinvestiti.
  Pagherai 26% solo alla vendita, sulla plusvalenza totale.
- **ETF distribuzione**: 26% sui dividendi ricevuti immediatamente,
  rompendo il compounding fiscale.

Su 20 anni con €30k iniziali, la differenza accumulazione vs distribuzione
è significativa (compounding fiscalmente intatto).

### 4. Domiciliazione Irlanda
VWCE è domiciliato in Irlanda → trattati fiscali favorevoli sui dividendi
US. Internamente l'ETF paga 15% (invece di 30%) sui dividendi delle
aziende americane.

### 5. Comprabile da broker italiano
Quotato su **Borsa Italiana** (VWCE.MI) in EUR. Disponibile su Fineco,
Directa, IBKR, Trade Republic, Scalable Capital. Liquidità eccellente
(AUM €37B+, spread bid-ask trascurabili).
"""
    )

# ----- comparison table -----

st.subheader("📊 Confronto con alternative")

comparison_data = {
    "ETF": [
        "VWCE (Vanguard FTSE All-World)",
        "IWDA / SWDA (iShares MSCI World)",
        "SPYY (SPDR MSCI ACWI)",
        "VUSA (Vanguard S&P 500)",
        "CSPX (iShares S&P 500)",
    ],
    "ISIN": [
        "IE00BK5BQT80",
        "IE00B4L5Y983",
        "IE00B3YLTY66",
        "IE00B3XXRP09",
        "IE00B5BMR087",
    ],
    "TER": ["0.19%", "0.20%", "0.12%", "0.07%", "0.07%"],
    "AUM": ["€37B", "€119B", "€3B", "€60B+", "€100B+"],
    "Tipo": [
        "Accumulating",
        "Accumulating",
        "Accumulating",
        "Distributing",
        "Accumulating",
    ],
    "Mercati": [
        "Sviluppati + Emerging (~3700)",
        "Solo sviluppati (~1500)",
        "Sviluppati + Emerging (~2900)",
        "Solo USA (500)",
        "Solo USA (500)",
    ],
    "Borsa IT": ["✅ VWCE.MI", "❌", "❌", "❌", "✅ CSPX.MI"],
    "Verdetto": [
        "🏆 Raccomandato",
        "Buono ma no emerging",
        "Cheap ma low AUM",
        "USA only + distributing",
        "USA only ma alternativa solida",
    ],
}
st.dataframe(
    pd.DataFrame(comparison_data), hide_index=True, use_container_width=True
)

st.markdown("---")

# ----- buy form -----

st.subheader("💼 Hai acquistato? Registra la posizione")

ETF_CATALOG = {
    "VWCE (consigliato)": ("IE00BK5BQT80", "Vanguard FTSE All-World UCITS ETF (Acc)"),
    "IWDA / SWDA": ("IE00B4L5Y983", "iShares Core MSCI World UCITS ETF (Acc)"),
    "SPYY": ("IE00B3YLTY66", "SPDR MSCI ACWI UCITS ETF"),
    "VUSA": ("IE00B3XXRP09", "Vanguard S&P 500 UCITS ETF (Dist)"),
    "CSPX": ("IE00B5BMR087", "iShares Core S&P 500 UCITS ETF (Acc)"),
}

tracker = PositionTracker()

with st.form("buy_etf_form"):
    c1, c2 = st.columns(2)
    with c1:
        etf_choice = st.selectbox(
            "ETF acquistato", list(ETF_CATALOG.keys()) + ["Altro"]
        )
        if etf_choice == "Altro":
            isin = st.text_input("ISIN dell'ETF")
            name = st.text_input("Nome ETF")
        else:
            isin, name = ETF_CATALOG[etf_choice]
            st.text(f"ISIN: {isin}")
            st.text(f"Nome: {name}")
    with c2:
        qty = st.number_input(
            "Quote acquistate", min_value=1, step=1, value=100
        )
        avg_price = st.number_input(
            "Prezzo medio acquisto (€/quota)",
            min_value=0.01,
            step=0.01,
            value=120.0,
            format="%.2f",
        )
        pdate = st.date_input("Data acquisto", value=date.today())

    if st.form_submit_button("💾 Registra acquisto", type="primary"):
        if not isin or not name:
            st.error("ISIN e nome obbligatori.")
        else:
            tracker.add_equity(
                isin=isin,
                name=name,
                quantity=qty,
                avg_purchase_price=avg_price,
                purchase_date=pdate,
            )
            st.success(f"✅ Registrate {qty} quote di {name}")
            st.info(
                "Vai a **📊 Portfolio Overview** per vedere il portfolio aggiornato."
            )

st.markdown("---")

# ----- fiscal notes -----

with st.expander("🇮🇹 Note fiscali per investitore italiano"):
    st.markdown(
        """
**Tassazione capital gain ETF azionari in Italia: 26%**

Si applica sulla differenza tra prezzo di vendita e prezzo di acquisto, al
momento della vendita.

**Imposta di bollo annua**: 0.20% sul controvalore totale degli ETF detenuti
al 31 dicembre.

**ETF accumulazione (es. VWCE, IWDA, CSPX)**:
- Nessuna tassazione finché tieni l'ETF.
- Pagherai 26% solo alla vendita, sulla plusvalenza totale.
- Più efficiente per accumulo lungo termine.

**ETF distribuzione (es. VUSA)**:
- 26% sui dividendi quando vengono accreditati (4 volte/anno tipicamente).
- Compounding rotto (rinvesti il 74%, non il 100%).
- Conveniente solo se hai bisogno di cash flow regolare.

**Domiciliazione Irlanda** (VWCE, IWDA, CSPX): riduce withholding tax US
sui dividendi dal 30% al 15%.

*Disclaimer*: queste informazioni sono indicative. Consulta un commercialista
per la tua situazione fiscale specifica.
"""
    )
