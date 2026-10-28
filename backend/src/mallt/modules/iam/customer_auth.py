"""Customer sign-in: phone OTP or Google. Customers are separate from staff accounts."""

import hmac
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.enums import ActiveStatus, IdentityKind
from mallt.core.errors import Conflict, RateLimited, Unauthorized
from mallt.core.kv import KV
from mallt.core.phone import mask_phone, normalize_in_phone
from mallt.core.ratelimit import hit
from mallt.core.security import create_access_token, hash_otp, new_otp
from mallt.modules.iam.google import GoogleVerifier
from mallt.modules.iam.models import Customer
from mallt.modules.iam.repository import CustomerRepository
from mallt.modules.iam.sessions import SessionService, SuspendedOnRefresh
from mallt.modules.iam.sms import SmsSender
from mallt.modules.iam.staff_auth import TokenPair

OTP_TTL_S = 300
MAX_VERIFY_TRIES = 5
SEND_PER_PHONE = (3, 600)  # 3 codes per 10 minutes per number


def generate_otp(settings: Settings) -> str:
    # A fixed code makes end-to-end tests deterministic, but it must never exist outside "test".
    if settings.env == "test" and settings.e2e_fixed_otp:
        return settings.e2e_fixed_otp
    return new_otp()


@dataclass(frozen=True)
class CustomerView:
    id: uuid.UUID
    phone: str | None
    name: str | None
    email: str | None

    @property
    def phone_masked(self) -> str | None:
        return mask_phone(self.phone) if self.phone else None


def _view(c: Customer) -> CustomerView:
    return CustomerView(c.id, c.phone, c.name, c.email)


def _otp_key(phone: str) -> str:
    return f"otp:{phone}"


def _tries_key(phone: str) -> str:
    return f"otp-tries:{phone}"


class CustomerAuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        kv: KV,
        sms: SmsSender,
        google: GoogleVerifier,
    ) -> None:
        self.settings = settings
        self.kv = kv
        self.sms = sms
        self.google = google
        self.repo = CustomerRepository(session)
        self.sessions = SessionService(session, settings, kv)

    # ---- one-time passwords ----

    async def request_otp(self, raw_phone: str, *, ip: str | None) -> int:
        phone = normalize_in_phone(raw_phone)
        await hit(self.kv, f"otp-send:{phone}", *SEND_PER_PHONE)
        if ip:
            await hit(self.kv, f"otp-ip:{ip}", self.settings.otp_send_per_ip_hourly, 3600)
        await hit(
            self.kv,
            "otp-global",
            self.settings.otp_send_global_daily,
            86_400,
            "sms_budget_exhausted",
        )
        otp = generate_otp(self.settings)
        await self.kv.set(_otp_key(phone), hash_otp(self.settings, phone, otp), OTP_TTL_S)
        # The guess counter is deliberately NOT reset here: asking for a new code must not hand an
        # attacker a fresh set of guesses.
        try:
            await self.sms.send_otp(phone, otp)
        except BaseException:
            await self.kv.delete(_otp_key(phone))  # nothing usable was delivered
            raise
        return OTP_TTL_S

    async def _consume_otp(self, raw_phone: str, otp: str) -> str:
        """Check a code (at most five tries, then it is burned) and return the clean number."""
        phone = normalize_in_phone(raw_phone)
        tries, retry_after = await self.kv.incr_window(_tries_key(phone), OTP_TTL_S)
        if tries > MAX_VERIFY_TRIES:
            await self.kv.delete(_otp_key(phone))
            raise RateLimited(retry_after, "too_many_attempts")
        stored = await self.kv.get(_otp_key(phone))
        expected = hash_otp(self.settings, phone, otp)
        if stored is None or not hmac.compare_digest(stored, expected):
            raise Unauthorized("invalid_otp", "That code is wrong or has expired.")
        await self.kv.delete(_otp_key(phone))
        await self.kv.delete(_tries_key(phone))
        return phone

    # ---- sessions ----

    async def _start_session(
        self, customer: Customer, *, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        if customer.status != ActiveStatus.ACTIVE:
            raise Unauthorized("account_suspended", "This account is suspended.")
        raw, row = await self.sessions.issue(
            IdentityKind.CUSTOMER, customer.id, user_agent=user_agent, ip=ip
        )
        return self._pair(customer.id, row.family_id, raw)

    def _pair(self, customer_id: uuid.UUID, family_id: uuid.UUID, refresh: str) -> TokenPair:
        access = create_access_token(self.settings, sub=customer_id, typ="customer", sid=family_id)
        return TokenPair(access, refresh, self.settings.access_ttl_s)

    async def verify_otp(
        self, raw_phone: str, otp: str, *, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        phone = await self._consume_otp(raw_phone, otp)
        customer = await self.repo.by_phone(phone)
        if customer is None:
            customer = await self.repo.create(Customer(phone=phone, status=ActiveStatus.ACTIVE))
            customer = customer or await self.repo.by_phone(phone)  # lost a race: use the winner's
        if customer is None:
            raise Unauthorized("invalid_otp", "Please try again.")
        return await self._start_session(customer, user_agent=user_agent, ip=ip)

    async def google_login(
        self, id_token: str, *, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        identity = await self.google.verify(id_token)
        customer = await self.repo.by_google_sub(identity.sub)
        if customer is None:
            created = await self.repo.create(
                Customer(
                    google_sub=identity.sub,
                    email=identity.email,
                    name=identity.name,
                    status=ActiveStatus.ACTIVE,
                )
            )
            customer = created or await self.repo.by_google_sub(identity.sub)
        if customer is None:
            raise Unauthorized("invalid_google_token", "Please try again.")
        return await self._start_session(customer, user_agent=user_agent, ip=ip)

    async def link_phone(
        self,
        customer_id: uuid.UUID,
        raw_phone: str,
        otp: str,
        *,
        user_agent: str | None,
        ip: str | None,
    ) -> TokenPair:
        """Attach a verified phone number. If that number already has an account, the Google
        identity is moved onto that account and the phone-less duplicate is removed."""
        phone = await self._consume_otp(raw_phone, otp)
        me = await self._get(customer_id)
        if me.phone and me.phone != phone:
            raise Conflict("phone_already_set", "This account already has a phone number.")
        owner = await self.repo.by_phone(phone)
        result = me
        if owner is None:
            me.phone = phone
        elif owner.id != me.id:
            if owner.google_sub and owner.google_sub != me.google_sub:
                raise Conflict(
                    "phone_belongs_to_other_account",
                    "That number belongs to an account with a different Google login.",
                )
            google_sub, email, name = me.google_sub, me.email, me.name
            await self.sessions.revoke_all(IdentityKind.CUSTOMER, me.id)
            me.google_sub = None  # frees the unique value before the owner takes it
            await self.repo.delete(me)
            owner.google_sub = google_sub
            owner.email = owner.email or email
            owner.name = owner.name or name
            result = owner
        await self.sessions.revoke_all(IdentityKind.CUSTOMER, customer_id)
        return await self._start_session(result, user_agent=user_agent, ip=ip)

    async def refresh(self, raw: str, *, user_agent: str | None, ip: str | None) -> TokenPair:
        new_raw, row = await self.sessions.rotate(
            IdentityKind.CUSTOMER, raw, user_agent=user_agent, ip=ip
        )
        customer = await self.repo.get(row.subject_id)
        if customer is None or customer.status != ActiveStatus.ACTIVE:
            await self.sessions.revoke_family(row.family_id)
            raise SuspendedOnRefresh
        return self._pair(customer.id, row.family_id, new_raw)

    async def logout(self, raw: str | None) -> None:
        if raw and (family_id := await self.sessions.family_of(raw)):
            await self.sessions.revoke_family(family_id)

    # ---- profile ----

    async def _get(self, customer_id: uuid.UUID) -> Customer:
        customer = await self.repo.get(customer_id)
        if customer is None:
            raise Unauthorized("invalid_token", "Invalid or expired access token.")
        return customer

    async def me(self, customer_id: uuid.UUID) -> CustomerView:
        return _view(await self._get(customer_id))

    async def update_me(
        self, customer_id: uuid.UUID, changes: dict[str, str | None]
    ) -> CustomerView:
        customer = await self._get(customer_id)
        for field, value in changes.items():
            setattr(customer, field, value)
        return _view(customer)
