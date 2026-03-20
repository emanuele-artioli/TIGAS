"""Media scaffold tests."""

from tigas.media.cmaf_packager import BasicCmafPackager
from tigas.media.priority import assign_object_priority
from tigas.shared.types import RawFrame


def test_priority_policy() -> None:
    assert assign_object_priority(True) == "high"
    assert assign_object_priority(False) == "normal"


def test_packager_assigns_incrementing_fragment_id() -> None:
    packager = BasicCmafPackager()
    frame = RawFrame(
        frame_id=1,
        width=1280,
        height=720,
        pixel_format="rgb24",
        is_keyframe_hint=True,
        data=b"abc",
    )

    fragment_a = packager.package(b"encoded-a", frame)
    fragment_b = packager.package(b"encoded-b", frame)

    assert fragment_a.fragment_id == 0
    assert fragment_b.fragment_id == 1
    assert fragment_a.priority == "high"
