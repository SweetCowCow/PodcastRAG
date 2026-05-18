"""SQLAlchemy model for the account_appeals table.

Each row records one appeal submission from a disabled user. Inserted by
``POST /auth/appeal`` (anonymous endpoint) only when the email matches a
``users`` row whose ``status='disabled'`` — silent-drop for unknown / active
emails to avoid account-existence enumeration.

The ``appeal_digest`` Celery beat task scans rows with
``notified_at IS NULL AND created_at >= now() - 25 hours`` once per day and
emails admins via ZSend, then stamps ``notified_at`` to avoid re-sending.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AccountAppeal(Base):
    __tablename__ = "account_appeals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    client_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_disabled_at_snapshot: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
