"""连接器安装任务：单任务互斥、进度、成功校验、取消与重启恢复。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.connectors.installer import InstallProcessResult
from app.connectors.jobs import ConnectorJobRunner
from app.connectors.napcat import MANIFEST_MARKER, NapCatProfile
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.models.connector import ConnectorJob
from sqlalchemy import select


class FakeInstaller:
    available = True

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.target: Path | None = None
        self.fail: tuple[str, str] | None = None
        self.events: list[dict[str, Any]] = []

    async def run_install(self, *, dest: Path, version: str, on_event: Any = None) -> InstallProcessResult:
        assert self.target is not None
        self.started.set()
        if on_event is not None:
            await on_event({"event": "progress", "stage": "download", "progress": 30, "message": "下载中"})
        await self.gate.wait()
        if self.fail is not None:
            code, message = self.fail
            return InstallProcessResult(
                returncode=1,
                stderr_tail="failed",
                last_error_code=code,
                last_error_message=message,
            )
        return InstallProcessResult(
            returncode=0,
            stderr_tail="",
            final_event={"event": "installed", "target": str(self.target)},
        )


def build_managed(root: Path) -> Path:
    package = root / "v4.18.42"
    package.mkdir(parents=True)
    installer = package / "NapCatInstaller.exe"
    installer.write_bytes(b"fake-installer")
    manifest = {
        "installer": MANIFEST_MARKER,
        "version": "v4.18.42",
        "installer_relative_path": "NapCatInstaller.exe",
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    shell = package / "NapCat.Shell"
    (shell / "config").mkdir(parents=True)
    (shell / "napcat.bat").write_text("@echo off\n", encoding="utf-8")
    return package


@pytest.fixture
def runner(
    settings: Settings,
    database: Database,
) -> tuple[ConnectorJobRunner, FakeInstaller]:
    fake = FakeInstaller()
    fake.target = build_managed(settings.connectors_path)
    instance = ConnectorJobRunner(
        database=database,
        installer=fake,  # type: ignore[arg-type]
        profile=NapCatProfile(),
        connectors_root=settings.connectors_path,
    )
    return instance, fake


async def _wait_state(
    runner: ConnectorJobRunner,
    job_id: str,
    state: str,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        job = await runner.get(job_id)
        if job["state"] == state:
            return job
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"job did not reach {state}: {job}")
        await asyncio.sleep(0.02)


async def test_install_success_reports_installer_ready_not_installed(
    runner: tuple[ConnectorJobRunner, FakeInstaller],
) -> None:
    jobs, fake = runner
    job = await jobs.start_install(version=None, actor="test")
    await fake.started.wait()
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        active = await jobs.get(job["id"])
        if active["progress"] == 30:
            break
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"progress event was not persisted: {active}")
        await asyncio.sleep(0.02)
    assert active["stage"] == "download"
    assert active["can_cancel"] is True

    fake.gate.set()
    done = await _wait_state(jobs, job["id"], "succeeded")
    assert done["progress"] == 100
    assert done["version"] == "v4.18.42"
    assert "安装器尚未运行" in done["message"]


async def test_only_one_install_job_and_cancel(
    runner: tuple[ConnectorJobRunner, FakeInstaller],
) -> None:
    jobs, fake = runner
    job = await jobs.start_install(version=None, actor="test")
    await fake.started.wait()

    with pytest.raises(AppError) as exc:
        await jobs.start_install(version=None, actor="test")
    assert exc.value.code == "CONNECTOR_JOB_CONFLICT"

    cancelled = await jobs.cancel(job["id"], actor="test")
    assert cancelled["state"] in {"cancelled", "interrupted"}


async def test_failure_keeps_stable_error(
    runner: tuple[ConnectorJobRunner, FakeInstaller],
) -> None:
    jobs, fake = runner
    fake.fail = ("CONNECTOR_DIGEST_MISMATCH", "SHA-256 不一致")
    job = await jobs.start_install(version=None, actor="test")
    await fake.started.wait()
    fake.gate.set()
    done = await _wait_state(jobs, job["id"], "failed")
    assert done["error_code"] == "CONNECTOR_DIGEST_MISMATCH"
    assert "SHA-256 不一致" in (done["error_message"] or "")


async def test_restart_marks_active_jobs_interrupted(
    runner: tuple[ConnectorJobRunner, FakeInstaller],
    database: Database,
) -> None:
    jobs, _ = runner
    async with database.session() as session:
        session.add(
            ConnectorJob(
                kind="install",
                state="running",
                stage="download",
                target_path="",
            )
        )
        await session.commit()

    count = await jobs.recover_interrupted()

    assert count == 1
    async with database.session() as session:
        row = await session.scalar(select(ConnectorJob))
        assert row is not None
        assert row.state == "interrupted"
        assert row.finished_at is not None


async def test_runner_verifies_target_and_rejects_missing_manifest(tmp_path: Path) -> None:
    fake = FakeInstaller()
    fake.target = tmp_path / "not-managed"
    fake.target.mkdir()
    fake.gate.set()

    class _Database:
        pass

    # 直接验证私有校验函数所需 profile 语义：目标缺少受管清单时失败。
    runner = ConnectorJobRunner(
        database=_Database(),  # type: ignore[arg-type]
        installer=fake,  # type: ignore[arg-type]
        profile=NapCatProfile(),
        connectors_root=tmp_path,
    )
    with pytest.raises(AppError) as exc:
        runner._verify_target(str(fake.target), requested="")
    assert exc.value.code == "CONNECTOR_INSTALL_FAILED"
