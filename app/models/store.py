from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4, UUID as UUIDType

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Numeric,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Session

from pydantic import BaseModel

from app.db.base_class import Base
from app.services.google_maps import find_place_lat_lng


# ============================================================
# SQLAlchemy MODELS
# ============================================================


class Store(Base):
    __tablename__ = "stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)  # e.g. grocery, electronics, wholesale
    website_url = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # One store → many locations
    locations = relationship(
        "StoreLocation",
        back_populates="store",
        cascade="all, delete-orphan",
    )


class StoreLocation(Base):
    __tablename__ = "store_locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    display_name = Column(String, nullable=True)  # e.g. "Safeway #123 - Beaverton"
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    country = Column(String, nullable=True, default="US")

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Simple flags
    supports_online_orders = Column(Boolean, default=False)
    supports_instore_coupons = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    store = relationship("Store", back_populates="locations")

    memberships = relationship(
        "UserStoreMembership",
        back_populates="store_location",
        cascade="all, delete-orphan",
    )

    coupons = relationship(
        "Coupon",
        back_populates="store_location",
        cascade="all, delete-orphan",
    )


class UserStoreMembership(Base):
    __tablename__ = "user_store_memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("store_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    membership_type = Column(
        String,
        nullable=True,
    )  # e.g. "loyalty", "wholesale_access", "premium"
    external_membership_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships (VERY IMPORTANT names)
    user = relationship("User", back_populates="store_memberships")
    store_location = relationship("StoreLocation", back_populates="memberships")


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    store_location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("store_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source = Column(
        String,
        nullable=True,
    )  # e.g. "store_app", "manufacturer", "third_party"
    code = Column(String, nullable=True)  # may be NULL for automatic discounts
    description = Column(String, nullable=True)

    discount_type = Column(
        String,
        nullable=False,
        default="amount",  # "amount" or "percent"
    )
    discount_value = Column(Numeric(10, 2), nullable=False, default=0)

    min_purchase_amount = Column(Numeric(10, 2), nullable=True)

    # 🚫 'metadata' is reserved by SQLAlchemy → use extra_metadata instead
    extra_metadata = Column(JSONB, default=dict)

    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationship back to StoreLocation
    store_location = relationship("StoreLocation", back_populates="coupons")


# ============================================================
# Google Maps helper for StoreLocation (used by plans.py)
# ============================================================


def get_or_create_store_location(
    db: Session,
    brand: str,
    name: str,
    search_text: str,
) -> StoreLocation:
    """
    Used by the planning logic to make sure we have a Store + StoreLocation with lat/long.

    - 'brand' maps to Store.name (e.g. 'Fred Meyer', 'WarehouseClub').
    - 'name' maps to StoreLocation.display_name (e.g. 'Fred Meyer (demo)').
    - 'search_text' is passed to Google Places Text Search once to fill lat/long.

    This reuses your existing Store/StoreLocation tables instead of creating a new model.
    """
    brand_norm = (brand or "").strip()
    name_norm = (name or "").strip()

    # 1) Find or create Store
    store = db.query(Store).filter(Store.name == brand_norm).first()
    if not store:
        store = Store(name=brand_norm or name_norm or "Unknown")
        db.add(store)
        db.commit()
        db.refresh(store)

    # 2) Find or create StoreLocation for this Store + display_name
    loc = (
        db.query(StoreLocation)
        .filter(StoreLocation.store_id == store.id)
        .filter(StoreLocation.display_name == (name_norm or None))
        .first()
    )

    if loc and loc.latitude is not None and loc.longitude is not None:
        return loc

    if not loc:
        loc = StoreLocation(
            store_id=store.id,
            display_name=name_norm or brand_norm or "Unknown",
        )
        db.add(loc)
        db.commit()
        db.refresh(loc)

    # 3) If we still don't have lat/long, call Google Places
    try:
        place = find_place_lat_lng(search_text)
    except Exception:
        place = None

    if place:
        # We only have a single address_line1 string here; that's fine for now
        formatted_address = place.get("formatted_address")
        if formatted_address:
            loc.address_line1 = formatted_address

        lat = place.get("lat")
        lng = place.get("lng")
        if lat is not None and lng is not None:
            loc.latitude = float(lat)
            loc.longitude = float(lng)

        db.add(loc)
        db.commit()
        db.refresh(loc)

    return loc


# ============================================================
# Pydantic SCHEMAS
# ============================================================


class StoreBase(BaseModel):
    name: str
    type: Optional[str] = None
    website_url: Optional[str] = None


class StoreCreate(StoreBase):
    pass


class StoreRead(StoreBase):
    id: UUIDType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StoreLocationBase(BaseModel):
    store_id: UUIDType
    display_name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = "US"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    supports_online_orders: bool = False
    supports_instore_coupons: bool = True


class StoreLocationCreate(StoreLocationBase):
    pass


class StoreLocationRead(StoreLocationBase):
    id: UUIDType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserStoreMembershipBase(BaseModel):
    user_id: UUIDType
    store_location_id: UUIDType
    membership_type: Optional[str] = None
    external_membership_id: Optional[str] = None
    is_active: bool = True


class UserStoreMembershipCreate(UserStoreMembershipBase):
    pass


class UserStoreMembershipRead(UserStoreMembershipBase):
    id: UUIDType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CouponBase(BaseModel):
    store_location_id: UUIDType
    source: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    discount_type: str = "amount"
    discount_value: float = 0.0
    min_purchase_amount: Optional[float] = None
    extra_metadata: Dict[str, Any] = {}
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class CouponCreate(CouponBase):
    pass


class CouponRead(CouponBase):
    id: UUIDType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
