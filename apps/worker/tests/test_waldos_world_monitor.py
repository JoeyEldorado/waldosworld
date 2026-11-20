"""Tests for the Waldo's World monitor workflow, run in local (no-infra) mode.

State is redirected to a local file via WALDOS_STATE_FILE so no Mistral Files
or Gmail credentials are needed; the YouTube fetch is real.
"""

import asyncio

import mistralai.workflows as workflows

from worker.workflows.waldos_world_monitor import MonitorInput, WaldosWorldMonitor


def _run(monkeypatch, tmp_path, inp: MonitorInput):
    monkeypatch.setenv("WALDOS_STATE_FILE", str(tmp_path / "state.json"))
    return asyncio.run(workflows.execute_workflow(WaldosWorldMonitor, params=inp))


def test_first_run_seeds_baseline_without_draft(monkeypatch, tmp_path):
    result = _run(monkeypatch, tmp_path, MonitorInput(dry_run=True))
    assert result.dry_run is True
    assert result.draft_id is None
    assert result.latest.video_id  # e.g. the current newest upload
    assert result.latest.link.startswith("https://www.youtube.com/watch?v=")
    # state was persisted with the newest video as baseline
    state_file = tmp_path / "state.json"
    import json

    state = json.loads(state_file.read_text())
    assert state["last_video_id"] == result.latest.video_id
    assert state["last_published"] == result.latest.published


def test_second_run_finds_nothing_new(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, MonitorInput(dry_run=True))
    result = _run(monkeypatch, tmp_path, MonitorInput(dry_run=True))
    assert result.new_videos == []
    assert result.draft_id is None


def test_force_draft_reports_latest_without_creating(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, MonitorInput(dry_run=True))
    result = _run(monkeypatch, tmp_path, MonitorInput(dry_run=True, force_draft=True))
    assert [v.video_id for v in result.new_videos] == [result.latest.video_id]
    assert result.draft_id is None  # dry_run never creates the draft
