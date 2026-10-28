from mallt.cli import build_openapi


def test_openapi_has_health_with_stable_operation_id() -> None:
    schema = build_openapi()
    op = schema["paths"]["/api/v1/health"]["get"]
    assert op["operationId"] == "health_get_health"
    assert schema["info"]["title"] == "MallT API"
