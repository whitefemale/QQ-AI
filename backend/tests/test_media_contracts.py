"""多模态 Provider 契约、Mock 确定性与本地媒体存储边界。"""

from __future__ import annotations

import pytest
from app.adapters.media.base import (
    MediaProcessor,
    RerankerProvider,
    VideoProcessor,
    VisionProvider,
)
from app.adapters.media.local_store import LocalMediaStore
from app.adapters.media.mock import (
    MockMediaProcessor,
    MockRerankerProvider,
    MockVideoProcessor,
    MockVisionProvider,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.providers.registry import CAPABILITY_TYPES, build_default_registry
from app.schemas.media import (
    BinarySource,
    ImageUnderstandRequest,
    MediaInspectRequest,
    MediaMetadata,
    RerankRequest,
    VideoUnderstandRequest,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_new_media_provider_contracts_are_abstract() -> None:
    for abc_class in (MediaProcessor, RerankerProvider, VideoProcessor):
        with pytest.raises(TypeError):
            abc_class(provider_id="x", name="x")  # type: ignore[abstract]


def test_registry_exposes_new_capabilities_as_mock_only() -> None:
    registry = build_default_registry()
    for capability, provider_type in (
        ("media.inspect", "media_processor"),
        ("text.rerank", "reranker"),
        ("video.describe", "video"),
    ):
        assert CAPABILITY_TYPES[capability] == provider_type
        entries = registry.list_entries(provider_type)
        assert any(entry.is_mock and not entry.planned for entry in entries)
        assert any(entry.planned for entry in entries)
        # 默认全部关闭：未显式启用前不能声称能力可用。
        assert registry.available_for(capability) == []


async def test_mock_media_processor_is_deterministic_and_marked_mock() -> None:
    provider = MockMediaProcessor()
    request = MediaInspectRequest(media_ref="a" * 64, mime="image/png")
    first = await provider.inspect(request)
    second = await provider.inspect(request)
    assert first.model_dump() == second.model_dump()
    assert first.is_mock is True
    assert first.recognized is False
    assert first.provider_id == "mock.media_processor"
    assert any("Mock" in warning for warning in first.warnings)


async def test_mock_reranker_orders_by_overlap_and_respects_top_n() -> None:
    provider = MockRerankerProvider()
    request = RerankRequest(
        query="group budget alert",
        documents=[
            "unrelated document",
            "budget alert for the group",
            "group budget",
        ],
    )
    result = await provider.rerank(request)
    assert result.is_mock is True
    # 文档 1 覆盖查询的全部 3 个词，文档 2 覆盖 2 个，文档 0 覆盖 0 个。
    assert [item.index for item in result.items] == [1, 2, 0]
    assert result.items[0].score > result.items[-1].score

    # 同分时按原始顺序稳定排序。
    trimmed = await provider.rerank(RerankRequest(query="group budget", documents=request.documents, top_n=1))
    assert [item.index for item in trimmed.items] == [1]

    zero = await provider.rerank(RerankRequest(query="group budget", documents=request.documents, top_n=0))
    assert zero.items == []


async def test_mock_video_does_not_claim_real_understanding() -> None:
    provider = MockVideoProcessor()
    result = await provider.describe_video(VideoUnderstandRequest(media_ref="b" * 64, mime="video/mp4"))
    assert result.is_mock is True
    assert result.confidence == 0.0
    assert "模拟" in result.summary
    assert any("Mock" in warning for warning in result.warnings)


async def test_local_store_sniffs_mime_and_deduplicates(settings: Settings) -> None:
    store = LocalMediaStore(settings.media_path, max_bytes=1024)
    first = await store.put(BinarySource(data=PNG, mime=None), MediaMetadata(media_type="image"))
    second = await store.put(BinarySource(data=PNG, mime="image/jpeg"), MediaMetadata(media_type="image"))
    assert first.mime == "image/png"
    assert first.media_ref == second.media_ref
    assert await store.exists(first.media_ref)
    files = [path for path in settings.media_path.rglob("*") if path.is_file()]
    assert len(files) == 1


async def test_local_store_rejects_empty_oversized_and_invalid_refs(settings: Settings) -> None:
    store = LocalMediaStore(settings.media_path, max_bytes=8)
    with pytest.raises(AppError) as empty:
        await store.put(BinarySource(data=b"", mime="image/png"), MediaMetadata(media_type="image"))
    assert empty.value.code == "MEDIA_TYPE_UNSUPPORTED"

    with pytest.raises(AppError) as oversized:
        await store.put(BinarySource(data=b"x" * 9, mime=None), MediaMetadata(media_type="image"))
    assert oversized.value.code == "MEDIA_TOO_LARGE"

    for unsafe in ("../etc/passwd", "A" * 64, "", "0" * 63):
        with pytest.raises(AppError) as invalid:
            await store.get(unsafe)
        assert invalid.value.code == "MEDIA_NOT_FOUND"


async def test_mock_vision_still_marks_results_as_simulated() -> None:
    provider = MockVisionProvider()
    assert isinstance(provider, VisionProvider)
    result = await provider.describe_image(ImageUnderstandRequest(media_ref="c" * 64))
    assert result.is_mock is True
