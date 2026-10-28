from mallt.workers.main import WorkerSettings, heartbeat


async def test_heartbeat_returns_ok() -> None:
    assert await heartbeat({}) == "ok"


def test_worker_registers_heartbeat() -> None:
    assert heartbeat in WorkerSettings.functions
