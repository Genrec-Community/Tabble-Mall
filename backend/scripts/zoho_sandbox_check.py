"""Check MallT's Zoho Payments integration against the Zoho SANDBOX, one step at a time.

Fill the ZOHO_* values in .env (sandbox keys, ZOHO_SANDBOX=true), then from backend/:

  1. uv run python scripts/zoho_sandbox_check.py check --accounts <connected_account_id> [...]
       OAuth token works; each store's connected account exists and can receive transfers.
  2. uv run python scripts/zoho_sandbox_check.py pay --amount 10.00
       Opens a real Zoho sandbox checkout in your browser (MallT's own widget parameters). Pay with
       a Zoho test card/UPI; the page shows the payment id.
  3. uv run python scripts/zoho_sandbox_check.py split --payment <payment_id> \
         --account <store_A_account> --account <store_B_account>
       The full money cycle MallT runs for a two-store cart, with MallT's real code:
         - read the payment back (checks the rupee amount format),
         - transfer each store its share minus the 0.50% fee (checks a transfer right after
           payment, before settlement),
         - find the transfer again by reference (what a retry relies on),
         - reverse store A's transfer, read back how much was reversed,
         - refund the customer what store A had received (the fee is not refunded),
         - read the payment's refunded amount back.
       Each step prints PASS/FAIL with Zoho's answer. Nothing here touches the MallT database.

Every step is safe to re-run with a new payment. Sandbox only: the script refuses live keys.
"""

import argparse
import asyncio
import sys
import tempfile
import time
import webbrowser
from collections.abc import Awaitable
from pathlib import Path

from mallt.core.config import get_settings
from mallt.modules.orders.pricing import gateway_fee, store_payout
from mallt.modules.payments.money import to_paise, to_rupees
from mallt.modules.payments.provider import ProviderError
from mallt.modules.payments.zoho import ZohoPaymentProvider


class MemoryKV:
    """Enough of core.kv.KV for the OAuth token cache."""

    fast = True

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> str | None:
        value = self._d.get(key)
        return value[0] if value and value[1] > time.time() else None

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._d[key] = (value, time.time() + ttl_s)

    async def delete(self, key: str) -> None:
        self._d.pop(key, None)


failures = 0


def report(ok: bool, step: str, detail: object = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {step}" + (f"\n        {detail}" if detail else ""))


async def safe[T](step: str, call: Awaitable[T]) -> T | None:
    """Run one Zoho call; an error from Zoho becomes a FAIL line instead of a crash."""
    try:
        return await call
    except ProviderError as exc:
        report(False, step, exc)
        return None


def provider() -> ZohoPaymentProvider:
    s = get_settings()
    missing = [
        name
        for name, value in (
            ("ZOHO_ACCOUNT_ID", s.zoho_account_id),
            ("ZOHO_CLIENT_ID", s.zoho_client_id),
            ("ZOHO_CLIENT_SECRET", s.zoho_client_secret),
            ("ZOHO_REFRESH_TOKEN", s.zoho_refresh_token),
            ("ZOHO_API_KEY", s.zoho_api_key),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Fill these in .env first: {', '.join(missing)}")
    if not s.zoho_sandbox:
        sys.exit("ZOHO_SANDBOX is not true. This script only runs against the sandbox.")
    return ZohoPaymentProvider(
        account_id=s.zoho_account_id,
        client_id=s.zoho_client_id,
        client_secret=s.zoho_client_secret,
        refresh_token=s.zoho_refresh_token,
        api_key=s.zoho_api_key,
        kv=MemoryKV(),  # type: ignore[arg-type]  # only get/set are used
        sandbox=True,
    )


async def check(accounts: list[str]) -> None:
    z = provider()
    try:
        await z._token(fresh=True)
        report(True, "OAuth refresh token gives an access token")
    except Exception as exc:  # noqa: BLE001 - report anything
        report(False, "OAuth refresh token gives an access token", exc)
        return
    for ref in accounts:
        try:
            info = await z.get_account(ref)
            report(
                info.transfers_enabled,
                f"connected account {ref} can receive transfers",
                f"review={info.review_status} transfers_enabled={info.transfers_enabled}",
            )
        except Exception as exc:  # noqa: BLE001
            report(False, f"connected account {ref} exists", exc)


PAGE = """<!doctype html><meta charset="utf-8"><title>MallT Zoho sandbox payment</title>
<body style="font-family:sans-serif;max-width:40rem;margin:2rem auto">
<h1>MallT: Zoho sandbox payment of Rs {amount}</h1>
<p>Click Pay and use a Zoho sandbox test card or UPI id.</p>
<button id="pay" style="font-size:1.2rem">Pay</button>
<pre id="out" style="font-size:1.1rem"></pre>
<script src="https://static.zohocdn.com/zpay/zpay-js/v1/zpayments.js"></script>
<script>
document.getElementById("pay").onclick = async () => {{
  const out = document.getElementById("out");
  const z = new window.ZPayments({{ account_id: "{account_id}", domain: "IN",
    otherOptions: {{ api_key: "{api_key}", is_test_mode: true }} }});
  try {{
    const r = await z.requestPaymentMethod({{ amount: "{amount}", currency_code: "INR",
      payments_session_id: "{session}", description: "MallT sandbox check" }});
    out.textContent = "Paid. Payment id:\\n\\n" + r.payment_id +
      "\\n\\nNow run:\\nuv run python scripts/zoho_sandbox_check.py split --payment " +
      r.payment_id + " --account <store A> --account <store B>";
  }} catch (e) {{ out.textContent = "Not paid: " + JSON.stringify(e); }}
  finally {{ await z.close(); }}
}};
</script>"""


async def pay(amount: str) -> None:
    z = provider()
    paise = to_paise(amount)
    started = await z.start(
        amount_paise=paise, reference=f"sandbox-{int(time.time())}", description="MallT check"
    )
    report(started.ok, "payment session created", f"session={started.session_ref}")
    if not started.ok:
        return
    params = z.client_params(
        session_ref=started.session_ref or "", amount_paise=paise, description="MallT check"
    )
    if params is None:
        return
    html = PAGE.format(
        amount=params["amount"],
        account_id=params["account_id"],
        api_key=params["api_key"],
        session=params["payments_session_id"],
    )
    path = Path(tempfile.gettempdir()) / "mallt-zoho-sandbox.html"
    path.write_text(html, encoding="utf-8")
    print(f"Opening {path} in your browser. Pay there, then run the 'split' step it shows.")
    webbrowser.open(path.as_uri())


async def split(payment_ref: str, accounts: list[str], fee_bps: int) -> None:
    z = provider()
    payment = await safe("read the payment", z.get_payment(payment_ref))
    report(
        payment is not None and payment.state.value == "succeeded",
        "payment read back as succeeded",
        payment,
    )
    if payment is None:
        return
    total = payment.amount_paise
    report(total > 0, f"amount parsed from rupees: {to_rupees(total)} = {total} paise")

    # Split the payment evenly between the stores, as a multi-store cart would.
    shares = [total // len(accounts)] * len(accounts)
    shares[-1] += total - sum(shares)
    transfers: list[tuple[str, str, int]] = []
    for i, (account, share) in enumerate(zip(accounts, shares, strict=True)):
        fee = gateway_fee(share, fee_bps)
        payout = store_payout(share, fee)
        reference = f"so:sandbox-{payment_ref}-{i}"
        result = await z.transfer(
            payment_ref=payment_ref, account_ref=account, amount_paise=payout, reference=reference
        )
        report(
            result.ok,
            f"transfer {to_rupees(payout)} to {account} (share {to_rupees(share)}, "
            f"fee {to_rupees(fee)})",
            result,
        )
        if result.ok:
            transfers.append((account, result.ref, payout))
            found = await safe(
                "find the transfer by reference",
                z.find_transfer(payment_ref=payment_ref, account_ref=account, reference=reference),
            )
            report(found == result.ref, "transfer found again by reference (retry safety)", found)
    if not transfers:
        return

    account, transfer_ref, payout = transfers[0]
    reversal = await z.reverse_transfer(
        transfer_ref=transfer_ref, amount_paise=payout, reference=f"so:sandbox-{payment_ref}-0"
    )
    report(reversal.ok, f"reverse {to_rupees(payout)} from {account}", reversal)
    reversed_paise = await safe("read the reversal back", z.reversed_paise(transfer_ref)) or 0
    report(reversed_paise >= payout, f"reversal read back: {to_rupees(reversed_paise)}")

    before = payment.refunded_paise
    refund = await z.refund(
        payment_ref=payment_ref, amount_paise=payout, reference=f"so:sandbox-{payment_ref}-0"
    )
    report(refund.ok, f"refund the customer {to_rupees(payout)} (the fee is not refunded)", refund)
    after = await safe("read the payment back", z.get_payment(payment_ref))
    refunded = after.refunded_paise if after else 0
    report(refunded >= before + payout, f"payment shows {to_rupees(refunded)} refunded")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="step", required=True)
    c = sub.add_parser("check")
    c.add_argument("--accounts", nargs="*", default=[])
    p = sub.add_parser("pay")
    p.add_argument("--amount", default="10.00", help="rupees, e.g. 10.00")
    s = sub.add_parser("split")
    s.add_argument("--payment", required=True)
    s.add_argument("--account", action="append", required=True, help="a store's connected account")
    args = parser.parse_args()
    if args.step == "check":
        asyncio.run(check(args.accounts))
    elif args.step == "pay":
        asyncio.run(pay(args.amount))
    else:
        asyncio.run(split(args.payment, args.account, get_settings().gateway_fee_bps))
    print(
        "\nAll steps passed."
        if failures == 0
        else f"\n{failures} step(s) failed. Send me the output."
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
