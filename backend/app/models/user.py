import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    member = "member"


class UserStatus(str, enum.Enum):
    active = "active"
    pending = "pending"
    disabled = "disabled"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="users_role_check"),
        CheckConstraint(
            "status IN ('active', 'pending', 'disabled')", name="users_status_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="google", server_default="google"
    )
    google_sub: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserRole.member.value
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserStatus.active.value
    )
    total_queries: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    quota_remaining: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    quota_initial: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
