from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4, UUID as UUIDType

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from pydantic import BaseModel

from app.db.base_class import Base


# ============================================================
# SQLAlchemy model
# ============================================================

class ItemIntent(Base):
    __tablename__ = "item_intents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    raw_text = Column(String, nullable=False)
    canonical_category = Column(String, nullable=True)
    attributes = Column(JSONB, default=dict)
    quantity = Column(Integer, nullable=False, default=1)

    status = Column(String, nullable=False, default="pending")  # pending, resolved, etc.

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Back-reference to User
    user = relationship("User", back_populates="item_intents")


# ============================================================
# Pydantic schemas
# ============================================================

class ItemIntentBase(BaseModel):
    raw_text: str
    canonical_category: Optional[str] = None
    attributes: Dict[str, Any] = {}
    quantity: int = 1
    status: Optional[str] = "pending"


class ItemIntentCreate(ItemIntentBase):
    user_id: UUIDType


class ItemIntentUpdate(BaseModel):
    canonical_category: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    quantity: Optional[int] = None
    status: Optional[str] = None


class ItemIntentRead(ItemIntentBase):
    id: UUIDType
    user_id: UUIDType
    created_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2 replacement for orm_mode
