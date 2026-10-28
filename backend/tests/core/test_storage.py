import re
from urllib.parse import parse_qs, urlsplit

import pytest

from mallt.core.config import Settings
from mallt.core.errors import BadRequest
from mallt.core.ids import uuid7
from mallt.core.storage import Storage


@pytest.fixture
def storage() -> Storage:
    return Storage(
        Settings(
            env="test",
            s3_endpoint_url="https://s3.example.test",
            s3_region="us-east-1",
            s3_bucket="mallt-dev",
            s3_access_key_id="AKIATEST",
            s3_secret_access_key="secret",
            s3_public_base_url="https://cdn.example.test/",
            _env_file=None,  # type: ignore[call-arg]
        )
    )


def test_presign_put_contains_bucket_key_and_expiry(storage: Storage) -> None:
    up = storage.presign_put("org/x/product/a.webp", "image/webp")
    parts = urlsplit(up.url)
    assert "mallt-dev" in up.url and parts.path.endswith("org/x/product/a.webp")
    assert parse_qs(parts.query)["X-Amz-Expires"] == ["300"]
    assert up.key == "org/x/product/a.webp" and up.expires_in == 300
    assert up.headers == {"Content-Type": "image/webp"}


@pytest.mark.parametrize("ctype", ["text/html", "image/svg+xml", "application/pdf", ""])
def test_presign_put_rejects_non_image_types(storage: Storage, ctype: str) -> None:
    with pytest.raises(BadRequest):
        storage.presign_put("k", ctype)


def test_object_key_is_tenant_scoped_and_unique(storage: Storage) -> None:
    org = uuid7()
    a = storage.object_key(organization_id=org, kind="product", ext="webp")
    b = storage.object_key(organization_id=org, kind="product", ext="webp")
    assert re.fullmatch(rf"org/{org}/product/[0-9a-f-]{{36}}\.webp", a)
    assert a != b


def test_public_url_has_no_double_slash(storage: Storage) -> None:
    assert storage.public_url("org/x/a.webp") == "https://cdn.example.test/org/x/a.webp"
