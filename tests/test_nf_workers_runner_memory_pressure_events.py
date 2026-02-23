from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import job_repo, project_repo
from modules.nf_shared.config import Settings
from modules.nf_shared.protocol.dtos import JobType
from modules.nf_workers import runner


@pytest.mark.unit
def test_run_worker_emits_memory_pressure_pause_reason_with_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        project = project_repo.create_project(conn, "p", {})
        job = job_repo.create_job(conn, project.project_id, JobType.CONSISTENCY, {}, {})

    pressure_states = iter([True, True, False])

    def fake_memory_pressure(_max_ram_mb: int) -> bool:
        try:
            return next(pressure_states)
        except StopIteration:
            return False

    monkeypatch.setattr(runner, "_memory_pressure", fake_memory_pressure)
    monkeypatch.setattr(runner, "_get_process_rss_mb", lambda: 4096.0)
    monkeypatch.setattr(
        runner,
        "load_config",
        lambda: Settings(max_ram_mb=1024, max_heavy_jobs=1),
    )
    monkeypatch.setattr(runner, "_run_job", lambda _job_type, _ctx: None)

    runner.run_worker(db_path=db_path, poll_interval=0.01, max_jobs=1)

    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT level, payload_json
            FROM job_events
            WHERE job_id = ?
            ORDER BY seq ASC
            """,
            (job.job_id,),
        ).fetchall()

    warn_payloads = []
    for row in rows:
        if row["level"] != "WARN":
            continue
        raw = row["payload_json"]
        if not isinstance(raw, str) or not raw:
            continue
        payload = json.loads(raw)
        if payload.get("reason_code") == "PAUSED_DUE_TO_MEMORY_PRESSURE":
            warn_payloads.append(payload)

    assert len(warn_payloads) == 1
    payload = warn_payloads[0]
    assert payload["reason_code"] == "PAUSED_DUE_TO_MEMORY_PRESSURE"
    assert int(payload["max_ram_mb"]) == 1024
    assert float(payload["rss_mb"]) >= 4096.0
