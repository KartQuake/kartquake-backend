# app/api/v1/watchlist.py

from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.watchlist import WatchlistItem, WatchlistItemRead, WatchedItemWithDrop
from app.models.item_intent import ItemIntent

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ---------- Request models ----------

class WatchlistToggleRequest(BaseModel):
    user_id: UUID
    item_intent_id: UUID


# ---------- Routes ----------

@router.post("/toggle", response_model=WatchlistItemRead)
def toggle_watch(payload: WatchlistToggleRequest, db: Session = Depends(get_db)):
    """
    Toggle a watchlist item for a given user + item_intent.
    - If it exists, flip is_active.
    - If it doesn't exist, create it active.
    """
    # Look up existing row for this user + item
    existing = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.user_id == payload.user_id,
            WatchlistItem.item_intent_id == payload.item_intent_id,
        )
        .first()
    )

    if existing:
        existing.is_active = not existing.is_active
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    # Ensure the item_intent exists (optional safety)
    item = db.query(ItemIntent).filter(ItemIntent.id == payload.item_intent_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="ItemIntent not found")

    new_item = WatchlistItem(
        user_id=payload.user_id,
        item_intent_id=payload.item_intent_id,
        is_active=True,
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.get("/user/{user_id}", response_model=List[WatchedItemWithDrop])
def get_user_watchlist(user_id: UUID, db: Session = Depends(get_db)):
    """
    Return all ACTIVE watchlist items for a user, joined with the ItemIntent
    and including price drop info.

    price_drop = previous_price - last_price
    > 0  => cheaper now than before
    < 0  => more expensive now
    """
    rows = (
        db.query(WatchlistItem, ItemIntent)
        .join(ItemIntent, WatchlistItem.item_intent_id == ItemIntent.id)
        .filter(
            WatchlistItem.user_id == user_id,
            WatchlistItem.is_active == True,  # only active ones
        )
        .all()
    )

    result: list[WatchedItemWithDrop] = []

    for wl, intent in rows:
        last_price = float(wl.last_price) if wl.last_price is not None else None
        previous_price = (
            float(wl.previous_price) if wl.previous_price is not None else None
        )

        price_drop = None
        if last_price is not None and previous_price is not None:
            # positive value means price went DOWN by that amount
            price_drop = previous_price - last_price

        result.append(
            WatchedItemWithDrop(
                item_id=wl.item_intent_id,
                raw_text=intent.raw_text,
                canonical_category=intent.canonical_category,
                last_price=last_price,
                previous_price=previous_price,
                price_drop=price_drop,
            )
        )

    return result


@router.get("/price-drops/{user_id}", response_model=List[WatchedItemWithDrop])
def get_price_drops(user_id: UUID, db: Session = Depends(get_db)):
    """
    Return only items where we have both prices and last_price < previous_price.
    This is useful for a 'price drops' banner or notification.
    """
    rows = (
        db.query(WatchlistItem, ItemIntent)
        .join(ItemIntent, WatchlistItem.item_intent_id == ItemIntent.id)
        .filter(
            WatchlistItem.user_id == user_id,
            WatchlistItem.is_active == True,
            WatchlistItem.last_price.isnot(None),
            WatchlistItem.previous_price.isnot(None),
            WatchlistItem.last_price < WatchlistItem.previous_price,
        )
        .all()
    )

    result: list[WatchedItemWithDrop] = []

    for wl, intent in rows:
        last_price = float(wl.last_price)
        previous_price = float(wl.previous_price)
        price_drop = previous_price - last_price  # > 0

        result.append(
            WatchedItemWithDrop(
                item_id=wl.item_intent_id,
                raw_text=intent.raw_text,
                canonical_category=intent.canonical_category,
                last_price=last_price,
                previous_price=previous_price,
                price_drop=price_drop,
            )
        )

    return result
