from decimal import Decimal

from sqlalchemy import Integer, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppSettings(Base):
    """Singleton table — one row enforced by application logic (id always 1)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_concurrent_transcriptions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    monthly_cost_cap_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # keyword-index-mode: T1 hit count at/above which the index-mode T2 section
    # collapses to a single "+N 集亦有命中" chip in the UI. Presentation hint
    # read per keyword-search request; admin-tunable via /admin/settings.
    keyword_t2_collapse_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
