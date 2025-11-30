# app/api/v1/memberships.py

from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.store import Store, StoreLocation, UserStoreMembership
from app.services.google_maps import find_place_lat_lng

router = APIRouter(prefix="/memberships", tags=["memberships"])


class MembershipCreateRequest(BaseModel):
    user_id: UUID
    store_name: str              # e.g. "Costco", "Safeway"
    location_display_name: Optional[str] = None  # optional label
    membership_type: Optional[str] = None        # e.g. "wholesale", "loyalty"
    external_membership_id: str                  # the card / account number


class MembershipRead(BaseModel):
    id: UUID
    user_id: UUID
    store_name: str
    location_display_name: Optional[str] = None
    membership_type: Optional[str] = None
    external_membership_id: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


@router.post("", response_model=MembershipRead)
def create_membership(
    payload: MembershipCreateRequest,
    db: Session = Depends(get_db),
) -> MembershipRead:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    store_name = payload.store_name.strip()
    if not store_name:
        raise HTTPException(status_code=400, detail="store_name is required")

    # 1) Find or create Store
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.commit()
        db.refresh(store)

    # 2) Find or create StoreLocation (basic)
    display_name = payload.location_display_name or store_name
    loc = (
        db.query(StoreLocation)
        .filter(StoreLocation.store_id == store.id)
        .filter(StoreLocation.display_name == display_name)
        .first()
    )
    if not loc:
        loc = StoreLocation(store_id=store.id, display_name=display_name)

        # Optional: try to resolve some lat/long + address
        try:
            place = find_place_lat_lng(display_name)
        except Exception:
            place = None

        if place:
            loc.address_line1 = place.get("formatted_address")
            lat = place.get("lat")
            lng = place.get("lng")
            if lat is not None and lng is not None:
                loc.latitude = float(lat)
                loc.longitude = float(lng)

        db.add(loc)
        db.commit()
        db.refresh(loc)

    # 3) Create membership
    membership = UserStoreMembership(
        user_id=payload.user_id,
        store_location_id=loc.id,
        membership_type=payload.membership_type,
        external_membership_id=payload.external_membership_id,
        is_active=True,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)

    return MembershipRead(
        id=membership.id,
        user_id=membership.user_id,
        store_name=store.name,
        location_display_name=loc.display_name,
        membership_type=membership.membership_type,
        external_membership_id=membership.external_membership_id,
        is_active=membership.is_active,
    )


@router.get("/{user_id}", response_model=List[MembershipRead])
def list_memberships(
    user_id: UUID,
    db: Session = Depends(get_db),
) -> List[MembershipRead]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    memberships = (
        db.query(UserStoreMembership)
        .join(StoreLocation, UserStoreMembership.store_location_id == StoreLocation.id)
        .join(Store, StoreLocation.store_id == Store.id)
        .filter(UserStoreMembership.user_id == user_id)
        .all()
    )

    results: List[MembershipRead] = []
    for m in memberships:
        results.append(
            MembershipRead(
                id=m.id,
                user_id=m.user_id,
                store_name=m.store_location.store.name,
                location_display_name=m.store_location.display_name,
                membership_type=m.membership_type,
                external_membership_id=m.external_membership_id,
                is_active=m.is_active,
            )
        )

    return results
