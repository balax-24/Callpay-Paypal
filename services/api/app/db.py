"""Database: Postgres primary, SQLite fallback if Postgres is unreachable at startup."""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

log = logging.getLogger("callpay.db")


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    phone: Mapped[str | None] = mapped_column(String(32))
    menu: Mapped[list["MenuItem"]] = relationship(back_populates="business", lazy="selectin")


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    business: Mapped[Business] = relationship(back_populates="menu")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"))
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    items: Mapped[list] = mapped_column(JSON)  # [{name, quantity, unit_amount}]
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="created")  # created|link_sent|paid|preparing|ready|failed|expired
    call_id: Mapped[str | None] = mapped_column(String(32))
    capture_id: Mapped[str | None] = mapped_column(String(64))
    dispute: Mapped[dict | None] = mapped_column(JSON)  # {id, reason, status, draft_evidence}
    payment_method: Mapped[str | None] = mapped_column(String(20))  # orders|invoice
    paypal_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    pay_link: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Call(Base):
    """One phone or browser call. Status: active|ended|abandoned|recovered."""

    __tablename__ = "calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"))
    channel: Mapped[str] = mapped_column(String(20))  # web|twilio|telnyx
    caller: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="active")
    transcript: Mapped[list] = mapped_column(JSON, default=list)  # [{role, text, agent, provider, ts}]
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # agent memory: cart, stage, flags
    order_id: Mapped[str | None] = mapped_column(String(32), index=True)
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)  # Twilio CallSid etc.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refund(Base):
    """Refund request. Status: pending_approval|approved|sent|failed|rejected."""

    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    paypal_refund_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(1000))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SupportCase(Base):
    __tablename__ = "support_cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    call_id: Mapped[str | None] = mapped_column(String(32))
    order_id: Mapped[str | None] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderEvent(Base):
    __tablename__ = "provider_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    layer: Mapped[str] = mapped_column(String(32))
    from_provider: Mapped[str] = mapped_column(String(32))
    to_provider: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # PayPal event id -> dedupe
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(200))
    paypal_email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(40), default="crew")
    active: Mapped[bool] = mapped_column(default=True)


class Payout(Base):
    """A crew payout batch. Status: pending_approval|approved|sent|completed|failed|rejected."""

    __tablename__ = "payouts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)  # also PayPal sender_batch_id
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    items: Mapped[list] = mapped_column(JSON)  # [{item_id, staff_id, name, email, amount, note}]
    memo: Mapped[str] = mapped_column(String(500), default="")
    policy: Mapped[dict] = mapped_column(JSON, default=dict)  # {decision, reasons}
    paypal_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[str | None] = mapped_column(String(1000))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN call_id VARCHAR(32)",
    "ALTER TABLE orders ADD COLUMN capture_id VARCHAR(64)",
    "ALTER TABLE orders ADD COLUMN dispute JSON",
]


class Database:
    def __init__(self, primary_url: str, fallback_url: str):
        self.primary_url = primary_url
        self.fallback_url = fallback_url
        self.engine: AsyncEngine | None = None
        self.backend = "none"
        self.session: async_sessionmaker | None = None

    async def connect(self) -> None:
        for url, label in ((self.primary_url, "postgres"), (self.fallback_url, "sqlite")):
            if not url:
                continue
            engine = create_async_engine(url, pool_pre_ping=True)
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                    await conn.run_sync(Base.metadata.create_all)
                for stmt in MIGRATIONS:  # additive columns for databases created by older versions
                    try:
                        async with engine.begin() as conn:
                            await conn.execute(text(stmt))
                    except Exception:  # noqa: BLE001 - column already exists
                        pass
            except Exception as e:  # noqa: BLE001
                log.warning("DB %s unavailable (%s); trying fallback", label, e)
                await engine.dispose()
                continue
            self.engine, self.backend = engine, label
            self.session = async_sessionmaker(engine, expire_on_commit=False)
            log.info("Database backend: %s", label)
            return
        raise RuntimeError("No database available")

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
