import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404 and "request_id" in r.json()


async def test_request_id_echoed(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


async def test_request_id_generated_when_absent(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert len(r.headers["X-Request-ID"]) == 32


async def test_validation_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/_test/echo", json={"n": "x"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert r.headers["content-type"].startswith("application/problem+json")
