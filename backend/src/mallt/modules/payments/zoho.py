"""Zoho Payments (India) with Split: payment sessions, transfers, reversals, refunds, connected
accounts, and webhook signature checks.

API reference: https://www.zoho.com/in/payments/api/v1/ . Amounts are rupees with two decimals on
the wire; we convert from paise with integer arithmetic only (``money.py``).
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from mallt.core.kv import KV
from mallt.modules.payments.money import to_paise, to_rupees
from mallt.modules.payments.provider import (
    AccountDetails,
    AccountInfo,
    MoneyResult,
    PaymentInfo,
    PaymentState,
    ProviderError,
    StartResult,
)

log = logging.getLogger(__name__)

SESSION_TTL_S = 900  # Zoho's maximum; also how long the browser has to pay
TOKEN_KEY = "payments:zoho:access_token"  # noqa: S105 - a cache key, not a secret
SIGNATURE_TOLERANCE_S = 300

_STATE = {
    "succeeded": PaymentState.SUCCEEDED,
    "refunded": PaymentState.SUCCEEDED,
    "partially_refunded": PaymentState.SUCCEEDED,
    "disputed": PaymentState.SUCCEEDED,
    "failed": PaymentState.FAILED,
    "canceled": PaymentState.FAILED,
    "blocked": PaymentState.FAILED,
}


class _Rupees:
    """A JSON number written from paise without ever being a float."""

    def __init__(self, paise: int) -> None:
        self.text = to_rupees(paise)


def dumps(body: Mapping[str, Any]) -> str:
    """json.dumps that writes ``_Rupees`` as a bare number literal (Zoho's fields are doubles)."""
    marks: dict[str, str] = {}

    def default(obj: Any) -> Any:
        if isinstance(obj, _Rupees):
            token = f"__rupees_{len(marks)}__"
            marks[token] = obj.text
            return token
        raise TypeError(f"not JSON serialisable: {type(obj).__name__}")

    text = json.dumps(body, default=default, separators=(",", ":"))
    for token, literal in marks.items():
        text = text.replace(f'"{token}"', literal)
    return text


def verify_signature(
    body: bytes, header: str | None, signing_key: str, *, now: float | None = None
) -> bool:
    """``X-Zoho-Webhook-Signature: t=<ms or s>,v=<hex>`` over ``"{t}.{raw body}"``."""
    if not header or not signing_key:
        return False
    parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
    stamp, given = parts.get("t", ""), parts.get("v", "")
    if not stamp.isdigit() or not given:
        return False
    seconds = int(stamp) / 1000 if len(stamp) > 11 else int(stamp)  # Zoho may send ms
    if abs((now if now is not None else time.time()) - seconds) > SIGNATURE_TOLERANCE_S:
        return False
    signed = stamp.encode() + b"." + body
    expected = hmac.new(signing_key.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given.lower())


class ZohoPaymentProvider:
    name = "zoho"
    requires_payout_accounts = True

    def __init__(
        self,
        *,
        account_id: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        api_key: str,
        kv: KV,
        sandbox: bool = False,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.api_key = api_key
        self.kv = kv
        self.sandbox = sandbox
        host = "paymentssandbox.zoho.in" if sandbox else "payments.zoho.in"
        self.base_url = f"https://{host}/api/v1"
        self.token_url = "https://accounts.zoho.in/oauth/v2/token"  # noqa: S105 - a URL
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))

    # ---- transport ----

    async def _token(self, *, fresh: bool = False) -> str:
        if not fresh and (cached := await self.kv.get(TOKEN_KEY)):
            return cached
        try:
            resp = await self.http.post(
                self.token_url,
                params={
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderError("Zoho sign-in failed", retryable=True) from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        token = data.get("access_token")
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ProviderError(f"Zoho sign-in: HTTP {resp.status_code}", retryable=True)
        if resp.status_code != 200 or not token:
            raise ProviderError(f"Zoho sign-in refused: {data.get('error', resp.status_code)}")
        ttl = max(60, int(data.get("expires_in", 3600)) - 300)
        await self.kv.set(TOKEN_KEY, str(token), ttl)
        return str(token)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = {"account_id": self.account_id, **(params or {})}
        content = dumps(body) if body is not None else None
        for attempt in (0, 1):
            headers = {"Authorization": f"Zoho-oauthtoken {await self._token(fresh=attempt > 0)}"}
            if content is not None:
                headers["Content-Type"] = "application/json"
            try:
                resp = await self.http.request(
                    method, self.base_url + path, params=query, content=content, headers=headers
                )
            except httpx.HTTPError as exc:
                raise ProviderError(f"Zoho {path} unreachable", retryable=True) from exc
            if resp.status_code == 401 and attempt == 0:
                continue  # access token expired early: sign in again once
            break
        try:
            data: dict[str, Any] = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ProviderError(f"Zoho {path}: HTTP {resp.status_code}", retryable=True)
        if resp.status_code >= 400 or data.get("code", 0) != 0:
            code = str(data.get("code", resp.status_code))
            raise ProviderError(f"Zoho {path}: {code} {data.get('message', '')}", code=code)
        return data

    # ---- payments ----

    async def start(self, *, amount_paise: int, reference: str, description: str) -> StartResult:
        try:
            data = await self._call(
                "POST",
                "/paymentsessions",
                body={
                    "amount": _Rupees(amount_paise),
                    "currency": "INR",
                    "description": description[:500],
                    "reference_number": reference[:50],
                    "expires_in": SESSION_TTL_S,
                },
            )
        except ProviderError:
            log.exception("could not start a Zoho payment session")
            return StartResult(False)
        session = data["payments_session"]
        return StartResult(
            True,
            session_ref=str(session["payments_session_id"]),
            expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_TTL_S),
        )

    def client_params(
        self, *, session_ref: str, amount_paise: int, description: str
    ) -> dict[str, Any] | None:
        return {
            "account_id": self.account_id,
            "api_key": self.api_key,
            "domain": "IN",
            "is_test_mode": self.sandbox,
            "payments_session_id": session_ref,
            "amount": to_rupees(amount_paise),
            "currency_code": "INR",
            "description": description[:500],
        }

    @staticmethod
    def payment_info(p: Mapping[str, Any]) -> PaymentInfo:
        return PaymentInfo(
            payment_ref=str(p["payment_id"]),
            session_ref=str(p.get("payments_session_id") or ""),
            reference=str(p.get("reference_number") or ""),
            state=_STATE.get(str(p.get("status")), PaymentState.PENDING),
            amount_paise=to_paise(p.get("amount", "0")),
            refunded_paise=to_paise(p.get("amount_refunded") or "0"),
        )

    async def get_payment(self, payment_ref: str) -> PaymentInfo | None:
        if not payment_ref.isdigit():
            return None
        try:
            data = await self._call("GET", f"/payments/{payment_ref}")
        except ProviderError as exc:
            if exc.retryable:
                raise
            return None
        return self.payment_info(data["payment"])

    async def find_payment(self, reference: str) -> PaymentInfo | None:
        data = await self._call("GET", "/payments", params={"search_text": reference})
        found = [self.payment_info(p) for p in data.get("payments", [])]
        found = [p for p in found if p.reference == reference]
        # Several attempts on one session: a success wins over failures.
        found.sort(key=lambda p: p.state is not PaymentState.SUCCEEDED)
        return found[0] if found else None

    # ---- split: transfers and reversals ----

    async def transfer(
        self, *, payment_ref: str, account_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult:
        try:
            data = await self._call(
                "POST",
                "/transfers",
                body={
                    "payment_id": int(payment_ref),
                    "transfer_split": [
                        {
                            "connected_account_id": account_ref,
                            "amount": _Rupees(amount_paise),
                            "description": reference,
                        }
                    ],
                },
            )
        except ProviderError as exc:
            return MoneyResult(False, retryable=exc.retryable, error=str(exc))
        transfers = data.get("data", data).get("transfers", {})
        splits = transfers.get("splits") or [{}]
        split = splits[0]
        if str(split.get("status", "")).lower() == "failed":
            return MoneyResult(False, error=str(split.get("failure_code") or "transfer failed"))
        return MoneyResult(True, str(split.get("transfer_id", "")))

    async def find_transfer(
        self, *, payment_ref: str, account_ref: str, reference: str
    ) -> str | None:
        data = await self._call(
            "GET",
            "/transfers",
            params={"payment_id": payment_ref, "connected_account_id": account_ref},
        )
        for t in data.get("transfers", []):
            if t.get("description") == reference and t.get("status") != "failed":
                return str(t["transfer_id"])
        return None

    async def reverse_transfer(
        self, *, transfer_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult:
        try:
            data = await self._call(
                "POST",
                "/transferreversals",
                body={
                    "transfer_id": int(transfer_ref),
                    "reversal_amount": _Rupees(amount_paise),
                    "description": reference,
                },
            )
        except ProviderError as exc:
            return MoneyResult(False, retryable=exc.retryable, error=str(exc))
        rev = data.get("transfer_reversal") or data.get("data") or {}
        return MoneyResult(True, str(rev.get("transfer_reversal_id", "")))

    async def reversed_paise(self, transfer_ref: str) -> int:
        data = await self._call("GET", f"/transfers/{transfer_ref}")
        return to_paise((data.get("transfer") or {}).get("reversed_amount") or "0")

    # ---- refunds ----

    async def refund(self, *, payment_ref: str, amount_paise: int, reference: str) -> MoneyResult:
        try:
            data = await self._call(
                "POST",
                f"/payments/{payment_ref}/refunds",
                body={
                    "amount": _Rupees(amount_paise),
                    "reason": "requested_by_customer",
                    "type": "initiated_by_merchant",
                    "description": reference,
                },
            )
        except ProviderError as exc:
            return MoneyResult(False, retryable=exc.retryable, error=str(exc))
        refund = data.get("refund", {})
        if refund.get("status") in ("failed", "canceled"):
            return MoneyResult(False, error=str(refund.get("failure_reason") or "refund failed"))
        return MoneyResult(True, str(refund.get("refund_id", "")))

    # ---- connected accounts ----

    @staticmethod
    def _account(a: Mapping[str, Any]) -> AccountInfo:
        return AccountInfo(
            account_ref=str(a["connected_account_id"]),
            review_status=str(a.get("under_writing_status") or "pending"),
            transfers_enabled=str(a.get("transfer_status")) == "enabled",
        )

    async def create_account(self, details: AccountDetails) -> AccountInfo:
        data = await self._call(
            "POST",
            "/connectedaccounts",
            body={
                "account_name": details.account_name,
                "email_id": details.email,
                "pan": details.pan,
                "mcc": details.mcc,
                "business_description": details.business_description,
                "connected_account_bank_account": {
                    "routing_number": details.ifsc,
                    "account_number": details.account_number,
                },
            },
        )
        return self._account(data["connected_account"])

    async def get_account(self, account_ref: str) -> AccountInfo:
        data = await self._call("GET", f"/connectedaccounts/{account_ref}")
        return self._account(data["connected_account"])
