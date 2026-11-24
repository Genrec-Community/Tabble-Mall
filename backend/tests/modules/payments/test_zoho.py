"""Zoho client: money encoding, webhook signatures, and the HTTP calls (mocked transport)."""

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from mallt.core.kv import KV
from mallt.modules.payments.money import to_paise, to_rupees
from mallt.modules.payments.provider import PaymentState
from mallt.modules.payments.zoho import TOKEN_KEY, ZohoPaymentProvider, dumps, verify_signature

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "zoho_sandbox_check.py"


def test_paise_and_rupees_round_trip_without_floats() -> None:
    assert to_rupees(43000) == "430.00"
    assert to_rupees(5) == "0.05"
    assert to_rupees(-1999) == "-19.99"
    assert to_paise("430.00") == 43000
    assert to_paise("₹1,200.5") == 120050
    assert to_paise("95.289") == 9528
    assert to_paise(200) == 20000
    with pytest.raises(ValueError):
        to_paise("abc")


def test_amounts_are_written_as_json_numbers() -> None:
    from mallt.modules.payments.zoho import _Rupees

    text = dumps({"amount": _Rupees(43005), "items": [{"amount": _Rupees(1)}], "x": "y"})
    assert text == '{"amount":430.05,"items":[{"amount":0.01}],"x":"y"}'
    assert json.loads(text)["amount"] == 430.05


def _sign(key: str, stamp: str, body: bytes) -> str:
    v = hmac.new(key.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v={v}"


def test_webhook_signature() -> None:
    body = b'{"event_id":"1"}'
    now = 1_800_000_000
    good = _sign("k", str(now), body)
    assert verify_signature(body, good, "k", now=now)
    assert verify_signature(body, _sign("k", str(now * 1000), body), "k", now=now)  # ms stamps
    assert not verify_signature(body + b" ", good, "k", now=now)  # body changed
    assert not verify_signature(body, good, "other", now=now)  # wrong key
    assert not verify_signature(body, good, "k", now=now + 3600)  # replayed later
    assert not verify_signature(body, None, "k", now=now)
    assert not verify_signature(body, "garbage", "k", now=now)
    assert not verify_signature(body, good, "", now=now)  # no key configured: refuse all


class Zoho:
    """A tiny fake of Zoho's HTTP API for the client tests."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.tokens = 0
        self.expire_next = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if request.url.host == "accounts.zoho.in":
            self.tokens += 1
            return httpx.Response(
                200, json={"access_token": f"tok{self.tokens}", "expires_in": 3600}
            )
        if self.expire_next:
            self.expire_next = False
            return httpx.Response(401, json={"code": "error", "message": "Invalid AuthToken"})
        assert request.url.params["account_id"] == "123"
        if path.endswith("/paymentsessions"):
            return httpx.Response(
                201,
                json={
                    "code": 0,
                    "payments_session": {"payments_session_id": "555", "amount": "430.00"},
                },
            )
        if path.endswith("/payments/777"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "payment": {
                        "payment_id": "777",
                        "payments_session_id": "555",
                        "reference_number": "order-1",
                        "amount": "430.00",
                        "amount_refunded": "120.00",
                        "status": "partially_refunded",
                    },
                },
            )
        if path.endswith("/transfers") and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "transfers": {
                            "status": "success",
                            "splits": [{"transfer_id": "900", "status": "success"}],
                        }
                    },
                },
            )
        if "/refunds" in path:
            return httpx.Response(
                400, json={"code": "refund_exceeds_payment_amount", "message": "no"}
            )
        if path.endswith("/transferreversals"):
            return httpx.Response(500, json={"code": "error", "message": "boom"})
        return httpx.Response(404, json={"code": "error", "message": "Not Authorised"})


@pytest.fixture
async def zoho(kv: KV) -> tuple[ZohoPaymentProvider, Zoho]:
    api = Zoho()
    provider = ZohoPaymentProvider(
        account_id="123",
        client_id="cid",
        client_secret="sec",
        refresh_token="ref",
        api_key="pub",
        kv=kv,
        sandbox=True,
        http=httpx.AsyncClient(transport=httpx.MockTransport(api)),
    )
    return provider, api


async def test_session_and_token_cache(zoho: tuple[ZohoPaymentProvider, Zoho], kv: KV) -> None:
    provider, api = zoho
    started = await provider.start(amount_paise=43000, reference="order-1", description="d")
    assert started.ok and not started.paid and started.session_ref == "555"
    session_call = api.calls[-1]
    assert session_call.url.host == "paymentssandbox.zoho.in"
    assert session_call.headers["authorization"] == "Zoho-oauthtoken tok1"
    body = json.loads(session_call.content)
    assert body["amount"] == 430.0 and body["reference_number"] == "order-1"
    await provider.start(amount_paise=100, reference="order-2", description="d")
    assert api.tokens == 1  # the access token is reused from KV
    assert await kv.get(TOKEN_KEY) == "tok1"
    params = provider.client_params(session_ref="555", amount_paise=43000, description="d")
    assert params and params["amount"] == "430.00" and params["is_test_mode"] is True


async def test_expired_token_is_refreshed_once(zoho: tuple[ZohoPaymentProvider, Zoho]) -> None:
    provider, api = zoho
    await provider.start(amount_paise=100, reference="r", description="d")
    api.expire_next = True
    info = await provider.get_payment("777")
    assert api.tokens == 2
    assert info is not None and info.state is PaymentState.SUCCEEDED
    assert info.amount_paise == 43000 and info.refunded_paise == 12000
    assert info.reference == "order-1" and info.session_ref == "555"


async def test_money_movements_report_retryable_vs_final(
    zoho: tuple[ZohoPaymentProvider, Zoho],
) -> None:
    provider, _ = zoho
    t = await provider.transfer(
        payment_ref="777", account_ref="42", amount_paise=11400, reference="so:1"
    )
    assert t.ok and t.ref == "900"
    refused = await provider.refund(payment_ref="777", amount_paise=99999, reference="so:1")
    assert not refused.ok and not refused.retryable
    down = await provider.reverse_transfer(transfer_ref="900", amount_paise=1, reference="so:1")
    assert not down.ok and down.retryable
    assert await provider.get_payment("not-a-number") is None


async def test_sandbox_check_script_runs_the_whole_cycle(
    zoho: tuple[ZohoPaymentProvider, Zoho], monkeypatch: pytest.MonkeyPatch
) -> None:
    """scripts/zoho_sandbox_check.py is what the owner runs against the real sandbox: it must at
    least run every step end to end (this fake answers some steps with errors on purpose)."""
    import importlib.util

    path = SCRIPT_PATH
    spec = importlib.util.spec_from_file_location("zoho_sandbox_check", path)
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    provider, api = zoho
    monkeypatch.setattr(script, "provider", lambda: provider)
    await script.split("777", ["acc-a", "acc-b"], 50)
    posted = [c for c in api.calls if c.method == "POST" and c.url.path.endswith("/transfers")]
    assert len(posted) == 2  # one transfer per store
    assert script.failures > 0  # the fake refuses the reversal and refund
