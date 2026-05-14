"""Bond DB refresh — runs the bonds/ sister-repo Selenium scraper in a
background thread, with a JSON state file the UI can poll.

Why threading + state file? Streamlit re-executes the page script on
every interaction. A long-running scrape would either block the UI
(if synchronous) or get killed by the next rerun (if naively spawned
in the script body). The pattern here:

- ``start_refresh_async`` spawns a daemon thread that owns the scrape.
- The thread updates ``data_storage/bonds_refresh_state.json`` after
  every profile via the scraper's ``page_callback``.
- The UI calls :func:`get_state` on every rerun to read the JSON, then
  triggers ``st.rerun`` after a short sleep to poll again.
- ``cancel_flag`` is a module-level ``threading.Event`` shared with the
  scraper; ``request_cancel`` sets it.

Resilience:

- Orphan detection: if the JSON says ``running`` but the worker thread
  is not alive and the state is older than 30 minutes, :func:`get_state`
  rewrites it to ``failed``. This recovers cleanly from a Streamlit
  process restart that left the JSON behind.
- Per-callback try/except inside the worker so a bad-state update can't
  poison the whole run.
- The sister-repo scraper itself wraps every profile in try/except and
  records errors on its ``ScrapeStats`` — we accumulate those.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_path() -> Path:
    return _repo_root() / "data_storage" / "bonds_refresh_state.json"


def _bonds_db_path() -> Path:
    """Resolve the Quant Lab bonds.db location via DataStorage / global config.

    Falls back to the conventional `data_storage/bonds/bonds.db` when the
    config layer is unavailable (e.g. in a unit-test environment).
    """
    try:
        from core.data.storage import DataStorage, load_global_config

        storage = DataStorage.from_config(load_global_config())
        return Path(storage.bonds_db_path)
    except Exception:
        return _repo_root() / "data_storage" / "bonds" / "bonds.db"


# ---------- state ----------


@dataclass
class RefreshState:
    """JSON-persisted state of a refresh operation.

    The UI never holds this in session_state — every render reads it
    fresh from disk via :func:`get_state` so a background thread that
    updates the JSON is reflected on the next ``st.rerun()``.
    """

    status: str = "idle"  # idle | running | completed | failed | cancelled
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    profiles_total: int = 0
    profiles_completed: int = 0
    current_profile: Optional[str] = None
    current_profile_label: Optional[str] = None

    bonds_total: int = 0  # rows seen across all profiles
    bonds_saved: int = 0  # successfully upserted
    profiles_with_errors: int = 0

    # Internal set of profile names currently "started" (i.e. their
    # opening page_callback fired but the end-of-profile one didn't).
    # Stored as a plain list because dataclass-asdict serialises sets
    # poorly to JSON.
    in_progress_profiles: list[str] = field(default_factory=list)

    # The last N completed profiles, in reverse chronological order.
    recent_profiles: list[dict] = field(default_factory=list)

    fatal_error: Optional[str] = None

    # ---- derived ----

    @property
    def progress_pct(self) -> float:
        return (
            (self.profiles_completed / self.profiles_total * 100.0)
            if self.profiles_total > 0
            else 0.0
        )

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        start = datetime.fromisoformat(self.started_at)
        end = (
            datetime.fromisoformat(self.completed_at)
            if self.completed_at
            else datetime.now()
        )
        return max(0.0, (end - start).total_seconds())

    @property
    def eta_seconds(self) -> Optional[float]:
        if self.profiles_completed == 0 or not self.is_running:
            return None
        avg_per_profile = self.elapsed_seconds / self.profiles_completed
        remaining = self.profiles_total - self.profiles_completed
        return max(0.0, avg_per_profile * remaining)

    # ---- persistence ----

    def save(self) -> None:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, default=str)
        # Atomic move so a partial write never leaves a corrupt JSON.
        tmp.replace(path)

    @classmethod
    def load(cls) -> "RefreshState":
        path = _state_path()
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning("RefreshState.load failed: %s", e)
            return cls()
        # Be tolerant to forward/backward compat: keep only known fields.
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})


# ---------- threading primitives ----------

_cancel_event: threading.Event = threading.Event()
_worker_thread: Optional[threading.Thread] = None


# ---------- public API ----------


def is_refresh_running() -> bool:
    """True if a refresh is currently flagged as running on disk."""
    return get_state().is_running


def request_cancel() -> None:
    """Signal the worker to stop ASAP. The current profile finishes; the
    next one is skipped. The state then transitions to ``cancelled``."""
    _cancel_event.set()


def reset_state() -> None:
    """Delete the state file (e.g. user dismissed the summary panel)."""
    path = _state_path()
    if path.exists():
        try:
            path.unlink()
        except Exception as e:
            log.warning("reset_state: could not delete %s: %s", path, e)


def get_state() -> RefreshState:
    """Return the current refresh state, with an orphan-detection guard.

    If the file says ``running`` but no worker thread is alive in this
    Python process and the timestamp is older than 30 minutes, we treat
    it as a leftover from a previous (now-dead) Streamlit process and
    rewrite the state to ``failed`` with a clear message. This avoids
    a stuck UI on restart.
    """
    state = RefreshState.load()
    if state.is_running:
        worker_alive = _worker_thread is not None and _worker_thread.is_alive()
        if not worker_alive and state.started_at:
            try:
                started = datetime.fromisoformat(state.started_at)
                if datetime.now() - started > timedelta(minutes=30):
                    state.status = "failed"
                    state.fatal_error = (
                        "Stato orfano: il refresh sembra essere stato "
                        "interrotto dal restart di Streamlit. "
                        "Riprova quando vuoi."
                    )
                    state.completed_at = datetime.now().isoformat()
                    state.save()
            except Exception as e:
                log.warning("orphan-detection error: %s", e)
    return state


def start_refresh_async(profiles_subset: Optional[list[str]] = None) -> tuple[bool, str]:
    """Spawn the background scrape thread. Returns ``(started, message)``.

    ``profiles_subset`` lets callers run a smoke-test against a handful
    of profiles (by ``name``) instead of the full 76 — used by the
    end-to-end test in :mod:`tests.test_directa_importer`-style fixtures.
    """
    global _worker_thread

    if is_refresh_running():
        return False, "Refresh già in corso. Attendi il completamento o annullalo."

    _cancel_event.clear()
    initial = RefreshState(
        status="running",
        started_at=datetime.now().isoformat(),
    )
    initial.save()

    _worker_thread = threading.Thread(
        target=_worker,
        kwargs={"profiles_subset": profiles_subset},
        daemon=True,
        name="bonds-refresh-worker",
    )
    _worker_thread.start()
    return True, "Refresh avviato in background."


# ---------- worker ----------


def _record_profile_start(name: str, label: str) -> None:
    state = RefreshState.load()
    state.current_profile = name
    state.current_profile_label = label
    if name not in state.in_progress_profiles:
        state.in_progress_profiles.append(name)
    state.save()


def _record_profile_done(name: str, label: str, rows: int, saved: int, error: Optional[str]) -> None:
    state = RefreshState.load()
    # Only count completion once per profile name.
    if name in state.in_progress_profiles:
        state.in_progress_profiles.remove(name)
        state.profiles_completed += 1
        state.bonds_total += int(rows)
        state.bonds_saved += int(saved)
        if error and error != "cancelled":
            state.profiles_with_errors += 1
        state.recent_profiles.insert(
            0,
            {
                "name": name,
                "label": label,
                "rows": int(rows),
                "saved": int(saved),
                "error": error,
                "timestamp": datetime.now().isoformat(),
            },
        )
        state.recent_profiles = state.recent_profiles[:10]
    state.save()


def _worker(profiles_subset: Optional[list[str]] = None) -> None:
    """Background entry point. Imports the sister repo, runs the full
    scrape against the Quant Lab bonds.db, and writes state updates.
    """
    try:
        from core.data.sister_repos import import_bonds_scraper

        scraper_module, db_module = import_bonds_scraper()
    except Exception as e:
        s = RefreshState.load()
        s.status = "failed"
        s.fatal_error = (
            f"Impossibile caricare lo scraper dal sister repo bonds/: {e}"
        )
        s.completed_at = datetime.now().isoformat()
        s.save()
        return

    # Filter the profiles if a subset was requested (smoke test).
    all_profiles = list(scraper_module.SCRAPE_PROFILES)
    if profiles_subset:
        selected = {p for p in profiles_subset}
        profiles = [p for p in all_profiles if p.name in selected]
        if not profiles:
            s = RefreshState.load()
            s.status = "failed"
            s.fatal_error = (
                f"Nessun profilo trovato corrispondente a {profiles_subset!r}."
            )
            s.completed_at = datetime.now().isoformat()
            s.save()
            return
    else:
        profiles = all_profiles

    # Persist the total upfront so the progress bar is meaningful even
    # before the first profile finishes.
    s = RefreshState.load()
    s.profiles_total = len(profiles)
    s.save()

    # Build a Database wrapper that points at the Quant Lab DB (not the
    # sister repo's local bonds.db). The sister repo's Database class
    # takes the path via its `path` kwarg.
    quant_lab_db = _bonds_db_path()
    quant_lab_db.parent.mkdir(parents=True, exist_ok=True)
    db = db_module.Database(path=str(quant_lab_db))

    # Label lookup so the UI can show human-readable names.
    profile_label_by_name = {p.name: p.label for p in profiles}
    # Snapshot of which profile names have fired their start callback.
    # The scraper invokes page_callback twice per profile: once at the
    # beginning (only `profile` set), once at the end (rows/saved/error
    # populated). We use the in_progress_profiles list on the state.

    def page_callback(stats) -> None:
        try:
            name = stats.profile
            label = profile_label_by_name.get(name, name)
            current = RefreshState.load()
            if name not in current.in_progress_profiles and stats.rows == 0 and not stats.error:
                # First callback: start of profile.
                _record_profile_start(name, label)
            else:
                # Second callback: end of profile.
                _record_profile_done(
                    name,
                    label,
                    rows=stats.rows,
                    saved=stats.saved,
                    error=stats.error,
                )
        except Exception as cb_e:
            log.warning("page_callback handler failed: %s", cb_e)

    def cancel_flag() -> bool:
        return _cancel_event.is_set()

    # Run the scrape (this blocks the worker thread until done).
    try:
        results = scraper_module.run_scrape(
            db,
            profiles=profiles,
            headless=True,
            page_callback=page_callback,
            cancel_flag=cancel_flag,
        )
    except Exception as e:
        s = RefreshState.load()
        s.status = "failed"
        s.fatal_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        s.completed_at = datetime.now().isoformat()
        s.save()
        return

    # Drain any profiles still flagged in_progress (shouldn't happen,
    # but defensive — keeps the count consistent if a callback was missed).
    final = RefreshState.load()
    final.in_progress_profiles = []
    final.completed_at = datetime.now().isoformat()

    if _cancel_event.is_set():
        final.status = "cancelled"
    elif isinstance(results, dict) and "__error__" in results:
        final.status = "failed"
        final.fatal_error = results["__error__"].get("error", "Errore sconosciuto.")
    else:
        final.status = "completed"

    final.save()
