"""Equity — Guida alla scelta dell'ETF passive globale (v3.0.0).

Pura pagina informativa: VWCE-first banner, motivazione, comparison table,
note fiscali. **No** form di registrazione posizioni — il portfolio
management è temporaneamente fuori dalla nav (vedi v3.0.0 simplification).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from ui.components.mode_badge import mode_badge

st.set_page_config(page_title="Equity", page_icon="🌍", layout="wide")
st.title("🌍 Equity")
mode_badge(
    "ricerca",
    "Guida alla scelta dell'ETF passive globale. Non gestisce posizioni — "
    "il portfolio management sarà integrato in futuro via API broker.",
)

# ----- filosofia -----

st.markdown(
    """
## Filosofia

L'equity sleeve di Quant Lab è **passiva e globale**. Non vale la pena attivare
strategie complesse su questa parte del portfolio per due ragioni:

1. **L'alpha estraibile da public US large-cap è zero/negativo** per il retail dopo
   costi (lezione Quantopian + verdict Quality Stocks V5 vs SPY, archiviato in
   `_migration_log/V5_VS_SPY_DECISION.md`).
2. **Massima diversificazione + costo minimo** è la strategia ottimale dimostrata
   empiricamente per orizzonti lungo termine (Fama-French, evidenza Bogleheads).

L'ETF World UCITS è la realizzazione pratica di questa filosofia per investitori
italiani.
"""
)

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

st.info(
    "💡 **Vuoi tracciare i tuoi acquisti?** Il portfolio management completo "
    "sarà integrato in futuro tramite API broker (Directa / IBKR). Per ora "
    "questa pagina è puramente informativa: la guida finisce qui, la "
    "decisione e l'esecuzione sono nelle tue mani."
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
