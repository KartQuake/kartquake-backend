# app/api/v1/billing.py

import os
import json
from typing import Literal
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User

router = APIRouter(prefix="/billing", tags=["billing"])

# Stripe config from env
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# NEW: only two paid products: premium + costco_addon
PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM")          # $11.99
PRICE_COSTCO_ADDON = os.getenv("STRIPE_PRICE_COSTCO_ADDON")  # $5.99

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Checkout session creation ----------

class CheckoutSessionRequest(BaseModel):
    user_id: UUID
    # only two billable things now: premium subscription, costco add-on
    plan: Literal["premium", "costco_addon"]


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(
    payload: CheckoutSessionRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Map logical plan → Stripe price ID
    if payload.plan == "premium":
        price_id = PRICE_PREMIUM
    elif payload.plan == "costco_addon":
        price_id = PRICE_COSTCO_ADDON
    else:
        raise HTTPException(status_code=400, detail="Unknown plan")

    if not price_id:
        raise HTTPException(status_code=500, detail="Stripe price ID not configured")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            metadata={
                "user_id": str(user.id),
                "plan": payload.plan,  # "premium" or "costco_addon"
            },
            success_url=f"{FRONTEND_BASE_URL}/?billing=success",
            cancel_url=f"{FRONTEND_BASE_URL}/?billing=cancel",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")

    return CheckoutSessionResponse(checkout_url=session.url)


# ---------- Webhook handler ----------

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhook events.

    Uses STRIPE_WEBHOOK_SECRET (from .env) to verify signature.
    On checkout.session.completed:
      - read metadata.user_id + metadata.plan
      - update User.plan and has_costco_addon / limits in DB.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # 1) Verify event signature
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            # Fallback: no verification (NOT recommended for production)
            event = stripe.Event.construct_from(
                json.loads(payload.decode("utf-8")),
                stripe.api_key,
            )
    except ValueError:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    print(f"Stripe webhook event: {event_type}")

    # 2) Handle checkout.session.completed
    if event_type == "checkout.session.completed":
        session_obj = data_object
        metadata = session_obj.get("metadata") or {}
        user_id_str = metadata.get("user_id")
        plan = metadata.get("plan")  # "premium" or "costco_addon"

        if not user_id_str or not plan:
            return {"status": "no-user-or-plan-metadata"}

        try:
            user_uuid = UUID(user_id_str)
        except Exception:
            return {"status": "invalid-user-id"}

        user = db.query(User).filter(User.id == user_uuid).first()
        if not user:
            return {"status": "user-not-found"}

        # --- Update user plan / flags based on what they purchased ---
        if plan == "premium":
            # Mark user as premium, effectively removing free limits
            user.plan = "premium"
            user.free_items_limit = 999999
            user.free_plan_runs_limit = 999999
        elif plan == "costco_addon":
            # Only toggle Costco add-on; base plan can still be "free" or "premium"
            user.has_costco_addon = True
            # If you want: treat this as "virtual Costco membership":
            # user.has_costco_membership = True

        db.add(user)
        db.commit()
        print(f"Updated user {user.id}: plan={user.plan}, costco_addon={user.has_costco_addon}")

    # You can handle other event types here if needed

    return {"status": "ok"}
