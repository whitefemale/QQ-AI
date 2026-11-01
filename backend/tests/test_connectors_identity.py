"""真实群导入前的登录身份确认：必须来自在线非 Mock 适配器。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.adapters.qq.mock import MockQQAdapter
from app.core.errors import AppError
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.services.account_service import AccountService


class IdentityAdapterManager:
    def __init__(self, adapter: Any = None) -> None:
        self.adapter = adapter

    def get_adapter(self, instance_id: str) -> Any:
        if self.adapter is not None and self.adapter.instance_id == instance_id:
            return self.adapter
        return None


@pytest.fixture
async def identity_context(database: Database, settings: Any) -> tuple[AccountService, str, str]:
    async with database.session() as session:
        account = Account(display_name="身份确认", platform="qq", adapter_type="onebot11", enabled=True)
        session.add(account)
        await session.flush()
        instance = AdapterInstance(
            account_id=account.id,
            name="connector",
            endpoint="ws://127.0.0.1:3001",
            connection_mode="onebot11",
            status="online",
        )
        session.add(instance)
        await session.commit()
        account_id = account.id
        instance_id = instance.id

    manager = IdentityAdapterManager()
    service = AccountService(
        database=database,
        cipher=CredentialCipher(settings.credential_encryption_key),
        manager=manager,  # type: ignore[arg-type]
        # 本测试只验证身份确认，不触发账号删除，因此派生服务用空值占位。
        personas=None,  # type: ignore[arg-type]
        memories=None,  # type: ignore[arg-type]
        media=None,  # type: ignore[arg-type]
    )
    return service, account_id, instance_id


def _online(account_id: str, instance_id: str, self_id: str | None, status: str = "online") -> Any:
    return SimpleNamespace(
        account_id=account_id,
        instance_id=instance_id,
        status=status,
        self_platform_user_id=self_id,
    )


async def test_requires_online_non_mock_adapter(identity_context: tuple[AccountService, str, str]) -> None:
    service, account_id, instance_id = identity_context
    manager = service.manager
    assert isinstance(manager, IdentityAdapterManager)

    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "10001")
    assert exc.value.code == "ADAPTER_UNAVAILABLE"

    manager.adapter = _online(account_id, instance_id, "10001", status="connected_unverified")
    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "10001")
    assert exc.value.code == "ADAPTER_IDENTITY_UNVERIFIED"

    manager.adapter = _online(account_id, instance_id, None)
    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "10001")
    assert exc.value.code == "ADAPTER_IDENTITY_UNVERIFIED"


async def test_missing_or_mismatched_confirmation_is_rejected(
    identity_context: tuple[AccountService, str, str],
) -> None:
    service, account_id, instance_id = identity_context
    manager = service.manager
    assert isinstance(manager, IdentityAdapterManager)
    manager.adapter = _online(account_id, instance_id, "10001")

    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, None)
    assert exc.value.code == "CONNECTOR_IDENTITY_MISMATCH"

    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "  ")
    assert exc.value.code == "CONNECTOR_IDENTITY_MISMATCH"

    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "20002")
    assert exc.value.code == "CONNECTOR_IDENTITY_MISMATCH"


async def test_matching_identity_is_confirmed_but_mock_never_is(
    identity_context: tuple[AccountService, str, str],
) -> None:
    service, account_id, instance_id = identity_context
    manager = service.manager
    assert isinstance(manager, IdentityAdapterManager)
    manager.adapter = _online(account_id, instance_id, "10001")

    result = await service.require_confirmed_identity(account_id, instance_id, " 10001 ")
    assert result["user_id"] == "10001"

    manager.adapter = MockQQAdapter(instance_id=instance_id, account_id=account_id)
    manager.adapter.status = "online"
    with pytest.raises(AppError) as exc:
        await service.require_confirmed_identity(account_id, instance_id, "10001")
    assert exc.value.code == "ADAPTER_UNSUPPORTED_OPERATION"
