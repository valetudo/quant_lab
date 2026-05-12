"""Debug Logs — browse migration and runtime logs."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Debug Logs", page_icon="🐛", layout="wide")
st.title("🐛 Debug Logs")

repo_root = Path(__file__).resolve().parents[2]

LOG_DIRS = [
    repo_root / "_migration_log",
    repo_root / "logs",
]

log_files: list[Path] = []
for d in LOG_DIRS:
    if d.exists():
        log_files += sorted(d.glob("*.log")) + sorted(d.glob("*.md"))

if not log_files:
    st.info("No log files found in `_migration_log/` or `logs/`.")
    st.stop()

choice = st.selectbox(
    "Log file",
    options=log_files,
    format_func=lambda p: f"{p.parent.name}/{p.name}",
)

level_filter = st.multiselect(
    "Filter by level", ["ERROR", "WARNING", "INFO", "DEBUG"], default=["ERROR", "WARNING", "INFO"]
)

text = choice.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()


def _matches(line: str) -> bool:
    if not level_filter:
        return True
    return any(lvl in line for lvl in level_filter)


def _color(line: str) -> str:
    if "ERROR" in line:
        return f"<span style='color:#c00;'>{line}</span>"
    if "WARNING" in line or "WARN" in line:
        return f"<span style='color:#c80;'>{line}</span>"
    return line


filtered = [_color(line) for line in lines if _matches(line)]
st.markdown(
    "<div style='font-family:monospace;white-space:pre-wrap;font-size:12px;'>"
    + "<br/>".join(filtered)
    + "</div>",
    unsafe_allow_html=True,
)

st.caption(f"{len(filtered)} of {len(lines)} lines shown.")
