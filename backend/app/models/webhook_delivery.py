from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Terminal states for one delivery.
STATUS_PROCESSED = "processed"
STATUS_IGNORED = "ignored"
STATUS_FAILED = "failed"


class WebhookDelivery(Base):
    """Ledger of GitHub webhook deliveries, keyed by GitHub's delivery id.

    Its purpose is deduplication: the unique constraint on `delivery_id` is
    what makes a replayed delivery — which carries a still-valid signature —
    impossible to process twice. Rows are inserted *before* handling, so two
    concurrent deliveries of the same id cannot both proceed.

    Payloads are deliberately not stored: they can contain repository names
    and account details, and nothing here needs them after handling.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    # GitHub's X-GitHub-Delivery header (a UUID).
    delivery_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PROCESSED)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
