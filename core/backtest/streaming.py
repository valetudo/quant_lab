"""Streaming backtest infrastructure — file-based pubsub.

Allows `PortfolioBacktester.run()` to emit events (equity update, trade open/close,
log, started/completed/stopped/error) to a JSONL file while a separate process
(typically a Streamlit page) reads them incrementally and re-renders.

Design rationale:
  - File-based instead of in-memory queue: works across threads AND processes
    (some streamlit deployments fork workers), and survives a hot reload.
  - JSONL append-only for events; one-shot JSON for control state.
  - Cancellation is cooperative: backtest must call `is_cancel_requested()`
    each iteration. No signals, no thread.interrupt — keeps cross-platform.
  - Backwards compatible: `stream_writer` is optional on the engine.

Example:
    writer = StreamWriter(run_id="abc123", output_dir=Path("/tmp/runs"))
    bt = PortfolioBacktester(strat, panel, stream_writer=writer)
    threading.Thread(target=bt.run, daemon=True).start()

    reader = StreamReader(run_id="abc123", output_dir=Path("/tmp/runs"))
    for ev in reader.read_new_events():
        ...
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class StreamEvent:
    """Single event emitted by a backtest run."""

    timestamp: str  # ISO datetime when emitted
    sim_date: str  # ISO date of the simulation
    event_type: str  # started | equity_update | trade_open | trade_close
    # | log | completed | stopped | error
    data: dict


class StreamWriter:
    """Thread-safe writer for stream events + control state.

    Files written under `output_dir`:
      - {run_id}_stream.jsonl  — append-only event log
      - {run_id}_control.json  — current status + cancel_requested flag
    """

    def __init__(self, run_id: str, output_dir: Path) -> None:
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.output_dir / f"{run_id}_stream.jsonl"
        self.control_path = self.output_dir / f"{run_id}_control.json"
        self._lock = threading.Lock()
        # Truncate any leftover events file from a previous run with the same id.
        self.events_path.write_text("", encoding="utf-8")
        # Initialise control state. `cancel_requested` is owned by readers — we
        # only seed False on first creation; subsequent status updates merge.
        self._patch_control({"status": "starting", "cancel_requested": False}, overwrite=True)

    # -------- emission --------

    def emit(self, sim_date, event_type: str, data: dict) -> None:
        sd = sim_date.isoformat() if hasattr(sim_date, "isoformat") else str(sim_date)
        ev = StreamEvent(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            sim_date=sd,
            event_type=event_type,
            data=dict(data),
        )
        with self._lock:
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(ev), default=str) + "\n")

    # -------- control --------

    def _patch_control(self, patch: dict, *, overwrite: bool = False) -> None:
        """In-place write of the control file with retry (Windows-safe).

        Merges `patch` over the existing state unless `overwrite=True`. We avoid
        os.replace/rename because on Windows a concurrent reader holding the
        file (even momentarily) makes the replace fail. The control file is
        tiny (<200 bytes) and readers already tolerate JSON decode errors, so a
        plain truncate+write under our lock is safe enough.
        """
        with self._lock:
            if overwrite:
                state = dict(patch)
            else:
                try:
                    state = json.loads(self.control_path.read_text(encoding="utf-8"))
                except (FileNotFoundError, json.JSONDecodeError):
                    state = {}
                state.update(patch)
            for attempt in range(5):
                try:
                    self.control_path.write_text(json.dumps(state), encoding="utf-8")
                    return
                except PermissionError:
                    # Reader briefly held the file open — retry with backoff.
                    import time as _t

                    _t.sleep(0.01 * (attempt + 1))
            # Final attempt without swallowing the error.
            self.control_path.write_text(json.dumps(state), encoding="utf-8")

    def is_cancel_requested(self) -> bool:
        try:
            return bool(
                json.loads(self.control_path.read_text(encoding="utf-8")).get(
                    "cancel_requested", False
                )
            )
        except (FileNotFoundError, json.JSONDecodeError):
            return False

    # `mark_*` only flip the status; they MUST preserve any cancel_requested
    # the reader has already set, otherwise an early cancel posted before the
    # backtest reads the file would be silently lost.
    def mark_started(self) -> None:
        self._patch_control({"status": "running"})

    def mark_completed(self) -> None:
        self._patch_control({"status": "completed"})

    def mark_stopped(self) -> None:
        self._patch_control({"status": "stopped_early"})

    def mark_error(self, msg: str) -> None:
        self._patch_control({"status": "error", "error": str(msg)})


class StreamReader:
    """Incremental tail reader for the JSONL stream + control file."""

    def __init__(self, run_id: str, output_dir: Path) -> None:
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.events_path = self.output_dir / f"{run_id}_stream.jsonl"
        self.control_path = self.output_dir / f"{run_id}_control.json"
        self._last_offset = 0

    def read_new_events(self) -> list[StreamEvent]:
        if not self.events_path.exists():
            return []
        events: list[StreamEvent] = []
        with open(self.events_path, "r", encoding="utf-8") as f:
            f.seek(self._last_offset)
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    events.append(StreamEvent(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    # partial write race: leave _last_offset alone for this line
                    # by breaking before updating it.
                    return events
            self._last_offset = f.tell()
        return events

    def get_status(self) -> dict:
        try:
            return json.loads(self.control_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"status": "unknown"}

    def request_cancel(self) -> None:
        try:
            ctrl = json.loads(self.control_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            ctrl = {}
        ctrl["cancel_requested"] = True
        self.control_path.write_text(json.dumps(ctrl), encoding="utf-8")


def update_every_for_span(total_days: int) -> int:
    """Heuristic for how often to emit equity_update events.

    Tuned so an N-fold walk-forward (N folds × ~250 days) still emits a few
    dozen points without flooding the JSONL.
    """
    if total_days < 90:
        return 1
    if total_days < 365:
        return 5
    if total_days < 365 * 3:
        return 10
    return 21
