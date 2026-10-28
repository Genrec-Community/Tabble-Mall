from mallt.core.ids import uuid7


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert all(u.version == 7 for u in ids)
    assert all(u.variant == "specified in RFC 4122" for u in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == 5000
