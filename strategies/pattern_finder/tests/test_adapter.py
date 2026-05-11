"""Sanity tests for the Pattern Finder adapter scaffold."""

from __future__ import annotations


import pandas as pd
import pytest
import yaml

from strategies.pattern_finder import PatternFinder


def test_scaffold_status_loads_config():
    s = PatternFinder()
    # Default config.yaml on disk is status=scaffold
    assert s.strategy_id == "pattern_finder"
    assert s._status == "scaffold"


def test_scaffold_returns_no_signals():
    s = PatternFinder()
    idx = pd.bdate_range("2024-01-02", periods=5)
    history = pd.DataFrame({"SPY": [100.0] * 5}, index=idx)
    signals = s.generate_signals(idx[0], history, open_positions=[])
    actions = s.manage_positions(idx[0], history, open_positions=[])
    assert signals == []
    assert actions == []


def test_universe_from_config():
    s = PatternFinder()
    u = s.universe
    assert isinstance(u, list)
    assert len(u) >= 1
    # Default config carries SPY
    assert "SPY" in u


def test_active_without_external_path_raises(tmp_path):
    # Synthesise a config with status=active and a bogus path
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "strategy_id": "pattern_finder",
                "status": "active",
                "pattern_finder_path": str(tmp_path / "nonexistent"),
                "universe": ["SPY"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        PatternFinder(config_path=cfg)


def test_active_with_injected_runner_works(tmp_path):
    """The adapter accepts an injected runner so tests don't need the real repo."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "strategy_id": "pattern_finder",
                "status": "active",
                "pattern_finder_path": str(tmp_path),
                "universe": ["SPY"],
            }
        ),
        encoding="utf-8",
    )

    # Fake runner object
    class FakeRunner:
        pass

    s = PatternFinder(config_path=cfg, external_runner=FakeRunner())
    assert s._status == "active"
    # Even with a runner, the TODOs aren't implemented, so signals stay empty.
    idx = pd.bdate_range("2024-01-02", periods=3)
    history = pd.DataFrame({"SPY": [100.0] * 3}, index=idx)
    assert s.generate_signals(idx[0], history, []) == []
    assert s.manage_positions(idx[0], history, []) == []
