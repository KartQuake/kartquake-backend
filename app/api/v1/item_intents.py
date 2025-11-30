from typing import List
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.item_intent import (
    ItemIntent,
    ItemIntentCreate,
    ItemIntentRead,
    ItemIntentUpdate,
)

router = APIRouter(
    prefix="/item-intents",
    tags=["item_intents"],
)


@router.post("", response_model=ItemIntentRead, status_code=status.HTTP_201_CREATED)
def create_item_intent(payload: ItemIntentCreate, db: Session = Depends(get_db)):
    item = ItemIntent(
        user_id=payload.user_id,
        raw_text=payload.raw_text,
        canonical_category=payload.canonical_category,
        attributes=payload.attributes,
        quantity=payload.quantity,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=List[ItemIntentRead])
def list_item_intents(user_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(ItemIntent)
    if user_id:
        query = query.filter(ItemIntent.user_id == user_id)
    items = query.order_by(ItemIntent.created_at.desc()).all()
    return items


@router.patch("/{item_intent_id}", response_model=ItemIntentRead)
def update_item_intent(
    item_intent_id: UUIDType,
    payload: ItemIntentUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(ItemIntent).filter(ItemIntent.id == item_intent_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ItemIntent not found.",
        )

    if payload.canonical_category is not None:
        item.canonical_category = payload.canonical_category
    if payload.attributes is not None:
        item.attributes = payload.attributes
    if payload.quantity is not None:
        item.quantity = payload.quantity
    if payload.status is not None:
        item.status = payload.status

    db.commit()
    db.refresh(item)
    return item
