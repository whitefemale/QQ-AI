"""连接器状态机：只报告证据，不把进程/WS 在线当成真实收发。"""

from __future__ import annotations

from datetime import timedelta

from app.connectors.state_engine import StateInput, evaluate_state
from app.core.time import utcnow


def _base(**overrides: object) -> StateInput:
    data = StateInput(
        has_installation=True,
        managed=True,
        shell_installed=True,
        installer_ready=False,
        version_compatibility="documented",
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    return data


def test_not_installed_when_no_installation() -> None:
    state = evaluate_state(
        StateInput(
            has_installation=False,
            managed=False,
            shell_installed=False,
            installer_ready=False,
            version_compatibility="unsupported",
        )
    )
    assert state.state == "not_installed"
    assert state.can_start is False
    assert state.can_configure is False


def test_installer_ready_is_not_installed() -> None:
    state = evaluate_state(_base(shell_installed=False, installer_ready=True))
    assert state.state == "installer_ready"
    assert state.severity == "info"
    assert state.can_run_installer is True
    assert state.can_start is False


def test_installer_launched_but_no_shell_is_warning() -> None:
    state = evaluate_state(_base(shell_installed=False, installer_ready=True, installer_launched_at=utcnow()))
    assert state.state == "installer_ready"
    assert state.severity == "warning"
    assert any(item["kind"] == "warning" for item in state.evidence)


def test_running_process_is_not_login_or_traffic() -> None:
    state = evaluate_state(
        _base(
            process_owned=True,
            process_alive=True,
            process_started_at=utcnow(),
        )
    )
    assert state.state == "starting"
    assert state.state not in {"waiting_login", "connected_traffic_unverified", "traffic_verified"}
    assert state.can_stop is True


def test_process_with_listening_port_is_inferred_waiting_login() -> None:
    state = evaluate_state(
        _base(process_owned=True, process_alive=True, process_started_at=utcnow(), port_listening=True)
    )
    assert state.state == "waiting_login"
    assert state.inferred is True


def test_port_without_owned_process_is_running_unmanaged() -> None:
    state = evaluate_state(_base(port_listening=True))
    assert state.state == "running_unmanaged"
    assert state.can_start is False
    assert state.can_stop is False


def test_online_ws_without_traffic_is_unverified() -> None:
    state = evaluate_state(_base(adapter_status="online"))
    assert state.state == "connected_traffic_unverified"
    assert state.severity == "info"
    assert any(item["source"] == "verification_scope" for item in state.evidence)


def test_connected_unverified_maps_to_waiting_login() -> None:
    state = evaluate_state(_base(adapter_status="connected_unverified"))
    assert state.state == "waiting_login"
    assert state.inferred is True


def test_mock_never_traffic_verified_even_with_both_evidence() -> None:
    state = evaluate_state(
        _base(
            adapter_status="online",
            adapter_is_mock=True,
            identity_confirmed_at=utcnow(),
            inbound_after_confirmation=True,
            outbound_after_confirmation=True,
        )
    )
    assert state.state == "connected_traffic_unverified"


def test_traffic_verified_requires_identity_and_both_directions() -> None:
    confirmed = utcnow()
    only_inbound = evaluate_state(
        _base(
            adapter_status="online",
            identity_confirmed_at=confirmed,
            inbound_after_confirmation=True,
            outbound_after_confirmation=False,
        )
    )
    assert only_inbound.state == "connected_traffic_unverified"

    both = evaluate_state(
        _base(
            adapter_status="online",
            identity_confirmed_at=confirmed,
            inbound_after_confirmation=True,
            outbound_after_confirmation=True,
            inbound_observed_at=confirmed + timedelta(seconds=3),
            outbound_observed_at=confirmed + timedelta(seconds=4),
        )
    )
    assert both.state == "traffic_verified"
    assert both.severity == "success"


def test_auth_failure_beats_online_state() -> None:
    state = evaluate_state(_base(adapter_status="online", adapter_error_code="ADAPTER_AUTH_FAILED"))
    assert state.state == "auth_failed"
    assert state.severity == "error"


def test_external_and_incompatible_are_readonly() -> None:
    external = evaluate_state(_base(managed=False, external_readonly=True))
    assert external.state == "external_readonly"
    assert external.can_configure is False
    assert external.can_run_installer is False

    incompatible = evaluate_state(_base(version_compatibility="incompatible"))
    assert incompatible.state == "incompatible"
    assert incompatible.can_start is False


def test_global_pause_blocks_actions() -> None:
    state = evaluate_state(_base(global_paused=True, port_listening=False))
    assert state.can_start is False
    assert state.can_configure is False
    assert state.can_run_installer is False


def test_interrupted_after_active_history() -> None:
    state = evaluate_state(_base(last_state="waiting_login"))
    assert state.state == "interrupted"
    assert state.severity == "warning"


def test_job_active_precedes_installer_states() -> None:
    state = evaluate_state(_base(job_active=True, shell_installed=False, installer_ready=True))
    assert state.state == "installing"


def test_http_identity_without_ws_is_logged_in_not_connected() -> None:
    state = evaluate_state(_base(http_identity_verified=True))
    assert state.state == "logged_in_not_connected"
    assert state.inferred is True
