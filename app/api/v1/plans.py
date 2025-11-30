# app/api/v1/plans.py

from uuid import UUID
from typing import List, Dict, Any, Optional

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from openai import OpenAI

from app.db.session import get_db
from app.models.user import User
from app.models.item_intent import ItemIntent
from app.models.trip_session import (
    get_or_create_trip_session,
    load_constraints,
    save_constraints,
    parse_constraints_from_text,
    PlanConstraints,
)
from app.models.store import StoreLocation, get_or_create_store_location, Store, UserStoreMembership  # NEW: Store, UserStoreMembership
from app.catalog.fredmeyer_demo import (
    FRED_MEYER_STORE_ID,
    FRED_MEYER_STORE_NAME,
    price_from_catalog,
)
from app.services.google_maps import (
    drive_time_minutes_text_to_latlng,
    drive_time_minutes_latlng_to_latlng,
)
from app.models.watchlist import WatchlistItem  # NEW

router = APIRouter(prefix="/plans", tags=["plans"])

client = OpenAI()


# -----------------------------
# Schemas
# -----------------------------

class BuildPlanRequest(BaseModel):
    user_id: UUID
    preference: Optional[str] = None  # e.g. "cheapest", "fewest stores", "1 store only"
    origin: Optional[str] = None      # user-chosen start (zip/address)
    destination: Optional[str] = None # user-chosen end (zip/address); if None, use origin


class PlanResponse(BaseModel):
    user_id: UUID
    items: List[Dict[str, Any]]
    plans: Dict[str, Any]
    recommended_plan: Optional[str] = None
    explanation: Optional[str] = None


# -----------------------------
# Helper: simple local pricing
# -----------------------------

def estimate_price_for_item(intent: ItemIntent, store_kind: str) -> float:
    """
    Very simple fake pricing so we can build plans without real APIs yet.
    Later, replace this with:
      - real store API prices,
      - membership discounts,
      - coupons, etc.
    """
    base = 0.0
    cat = (intent.canonical_category or "other").lower()

    if cat == "milk":
        base = 3.99
    elif cat == "eggs":
        base = 2.49
    elif cat == "cereal":
        base = 4.99
    elif cat == "tablet":
        base = 699.0
    elif cat == "detergent":
        base = 12.99
    else:
        base = 5.0

    # Simple store differences
    kind = store_kind.lower()
    if kind in ("store_a", "fred_meyer"):
        multiplier = 1.0
    elif kind in ("store_b", "warehouse_club"):
        multiplier = 0.92
    else:
        multiplier = 1.05

    return round(base * multiplier * max(intent.quantity, 1), 2)


# -----------------------------
# Helper: call LLM to choose plan
# -----------------------------

def ask_llm_to_choose_plan(
    plans: Dict[str, Any],
    preference: Optional[str],
    constraints: PlanConstraints,
) -> Dict[str, Any]:
    """
    Ask OpenAI to pick between candidate plans based on a textual preference
    AND the parsed constraints.

    Returns:
      {
        "recommended_plan": "<plan_key>",
        "explanation": "<short explanation>"
      }
    """

    system_prompt = """
You are a shopping route planner.

You receive:
- a JSON object describing candidate shopping plans,
- a short text 'preference' from the user,
- a structured 'constraints' object describing rules like:
    - max_stores: int or null
    - avoid_costco: bool
    - include_cheapest_gas: bool
    - optimize_for: "balanced" | "cheapest_overall" | "fastest_drive"
    - must_include_costco: bool

Each plan has:
- number_of_stores (int),
- total_price (float),
- travel_minutes (float),
- stores: [{id, name, distance_minutes, ...}]

Your job:
- Pick the BEST plan key among those provided (e.g. "one_store", "two_store", "three_store").
- Explain *briefly* why, in 1–3 sentences.

Important:
- You MUST respect strict constraints:
    - If avoid_costco = true, you MUST NOT choose a plan that uses the Costco-like store (WarehouseClub).
    - If must_include_costco = true, you MUST prefer a plan that includes WarehouseClub.
    - If max_stores is not null, prefer plans whose number_of_stores <= max_stores.
- Use optimize_for:
    - "cheapest_overall": favor lower total_price, but still consider stores/travel.
    - "fastest_drive": favor lower travel_minutes, but still consider stores/price.
    - "balanced": trade off both reasonably.

OUTPUT:
Respond with ONLY JSON:
{
  "recommended_plan": "<one of the keys in the input 'plans' object>",
  "explanation": "<short explanation>"
}
"""

    user_prompt = {
        "preference": preference or "",
        "constraints": constraints.model_dump(),
        "plans": plans,
    }

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
    )

    content = response.choices[0].message.content
    data = json.loads(content)

    recommended = data.get("recommended_plan")
    explanation = data.get("explanation")
    if recommended not in plans.keys():
        # Fallback: choose the first plan key
        first_key = next(iter(plans.keys()))
        recommended = first_key
        if not explanation:
            explanation = f"I defaulted to the '{first_key}' plan."

    return {
        "recommended_plan": recommended,
        "explanation": explanation,
    }


# -----------------------------
# Helper: augment plans with drive times (Maps)
# -----------------------------

def augment_plan_with_drive_times(
    db: Session,
    plan: Dict[str, Any],
    origin_text: Optional[str],
    destination_text: Optional[str],
) -> None:
    """
    - Resolve each store in plan["stores"] to a StoreLocation (lat/lng).
    - Compute:
        - store["distance_minutes"]: drive time from origin_text → store
        - plan["travel_minutes"]: total route origin → store1 → store2 → ... → destination
    If origin/destination missing or Maps fails, keep existing stub values.
    """
    stores = plan.get("stores") or []
    if not stores:
        return

    origin_text = (origin_text or "").strip()
    destination_text = (destination_text or "").strip()
    if not origin_text and not destination_text:
        # Nothing to do
        return

    # If destination is empty, treat it as same as origin
    if not destination_text:
        destination_text = origin_text

    # 1) Resolve each store to a StoreLocation with latitude/longitude
    store_locations: List[StoreLocation] = []
    for s in stores:
        brand = s.get("name") or "Unknown"
        name = s.get("name") or "Unknown"
        # Search text: "<name> near <origin>"
        search_text = origin_text and f"{name} near {origin_text}" or name

        loc = get_or_create_store_location(db, brand=brand, name=name, search_text=search_text)
        store_locations.append(loc)

    # If any store is missing latitude/longitude, we can't do route math reliably
    if any(loc.latitude is None or loc.longitude is None for loc in store_locations):
        return

    # 2) Per-store distance from origin
    total_travel = 0.0
    for s, loc in zip(stores, store_locations):
        if origin_text:
            mins = drive_time_minutes_text_to_latlng(origin_text, loc.latitude, loc.longitude)
        else:
            mins = None
        if mins is not None:
            s["distance_minutes"] = round(float(mins), 1)

    # 3) Total route: origin → store1 → store2 → ... → destination

    # origin → first store
    first = store_locations[0]
    if origin_text:
        leg1 = drive_time_minutes_text_to_latlng(origin_text, first.latitude, first.longitude)
    else:
        leg1 = None
    if leg1 is not None:
        total_travel += leg1

    # between stores
    for prev_loc, next_loc in zip(store_locations[:-1], store_locations[1:]):
        leg = drive_time_minutes_latlng_to_latlng(
            prev_loc.latitude, prev_loc.longitude,
            next_loc.latitude, next_loc.longitude,
        )
        if leg is not None:
            total_travel += leg

    # last store → destination
    last = store_locations[-1]
    if destination_text:
        leg_last = drive_time_minutes_text_to_latlng(destination_text, last.latitude, last.longitude)
    else:
        leg_last = None
    if leg_last is not None:
        total_travel += leg_last

    if total_travel > 0:
        plan["travel_minutes"] = round(total_travel, 1)


# -----------------------------
# NEW: Watchlist price tracking
# -----------------------------

def update_watchlist_prices_from_plans(
    db: Session,
    user_id: UUID,
    plans: Dict[str, Any],
) -> None:
    """
    For each watched ItemIntent, update last_price / previous_price using
    the estimated_price from the candidate plans.

    We take the *lowest* price seen across plans for each item.
    """
    from uuid import UUID as UUIDType

    latest_prices: Dict[UUIDType, float] = {}

    for plan in plans.values():
        for item in plan.get("items", []):
            item_id_str = item.get("id")
            price = item.get("estimated_price")
            if not item_id_str or price is None:
                continue
            try:
                item_uuid = UUIDType(item_id_str)
            except Exception:
                continue

            price_f = float(price)
            if item_uuid not in latest_prices or price_f < latest_prices[item_uuid]:
                latest_prices[item_uuid] = price_f

    if not latest_prices:
        return

    watched_items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user_id)
        .filter(WatchlistItem.is_active == True)  # noqa: E712
        .filter(WatchlistItem.item_intent_id.in_(list(latest_prices.keys())))
        .all()
    )

    for wl in watched_items:
        new_price = latest_prices.get(wl.item_intent_id)
        if new_price is None:
            continue
        if wl.last_price is not None:
            wl.previous_price = wl.last_price
        wl.last_price = new_price
        db.add(wl)

    db.commit()


# -----------------------------
# NEW: Memberships + coupons rule engine
# -----------------------------

def apply_memberships_and_coupons(
    db: Session,
    user: User,
    plans: Dict[str, Any],
) -> None:
    """
    Very simple static rule engine for MVP:

    - If user has membership for brand "WarehouseClub" → 5% off items at WarehouseClub.
    - If basket at Fred Meyer (FRED_MEYER_STORE_NAME) ≥ $50 → $5 off.

    We update plan["total_price"] in-place and add a "discounts": [ ... ] list.
    """
    # Find store brands this user has active memberships for
    memberships = (
        db.query(UserStoreMembership)
        .join(StoreLocation, UserStoreMembership.store_location_id == StoreLocation.id)
        .join(Store, StoreLocation.store_id == Store.id)
        .filter(UserStoreMembership.user_id == user.id)
        .filter(UserStoreMembership.is_active == True)  # noqa: E712
        .all()
    )

    member_brands = set()
    for m in memberships:
        if m.store_location and m.store_location.store:
            member_brands.add(m.store_location.store.name)

    for key, plan in plans.items():
        items = plan.get("items", [])
        stores = plan.get("stores", [])

        # Map store_name → subtotal
        subtotal_by_store: Dict[str, float] = {}

        # If an item doesn't have explicit store_name, default to the plan's first store
        default_store_name = stores[0]["name"] if stores else "Unknown"

        for item in items:
            store_name = item.get("store_name") or default_store_name
            price = float(item.get("estimated_price") or 0.0)
            subtotal_by_store.setdefault(store_name, 0.0)
            subtotal_by_store[store_name] += price

        total_discount = 0.0
        discounts: List[str] = []

        # Rule 1: membership discount at WarehouseClub (Costco-like)
        if "WarehouseClub" in member_brands:
            wc_subtotal = subtotal_by_store.get("WarehouseClub", 0.0)
            if wc_subtotal > 0:
                discount_wc = 0.05 * wc_subtotal
                total_discount += discount_wc
                discounts.append(
                    f"5% membership discount at WarehouseClub (−${discount_wc:.2f})"
                )

        # Rule 2: $5 off if Fred Meyer basket >= $50
        fm_subtotal = subtotal_by_store.get(FRED_MEYER_STORE_NAME, 0.0)
        if fm_subtotal >= 50.0:
            total_discount += 5.0
            discounts.append(f"$5 coupon applied at {FRED_MEYER_STORE_NAME} (basket ≥ $50)")

        if total_discount > 0:
            original_total = float(plan.get("total_price", 0.0))
            new_total = max(original_total - round(total_discount, 2), 0.0)
            plan["total_price"] = round(new_total, 2)
            plan["discounts"] = discounts
        else:
            if "discounts" not in plan:
                plan["discounts"] = []


# -----------------------------
# Main endpoint
# -----------------------------


@router.post("/build", response_model=PlanResponse)
def build_plan(
    payload: BuildPlanRequest,
    db: Session = Depends(get_db),
) -> PlanResponse:
    """
    Build candidate plans (multi-store) and let OpenAI choose the best,
    with awareness of per-user trip constraints and drive times from Maps,
    plus memberships/coupons and watchlist price tracking.

    NEW:
    - Free tier gating:
        * free_plan_runs_limit / free_plan_runs_used
        * free users only see 1-store plan
    - Costco gating:
        * only allow WarehouseClub if user.has_costco_membership or user.has_costco_addon
    """

    # 1. Ensure user exists
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # -----------------------------
    # NEW: determine plan / Costco access
    # -----------------------------
    is_free = (user.plan or "free") == "free"
    allow_costco = bool(user.has_costco_membership or user.has_costco_addon)

    # FREE: limit how many times they can run planning
    if is_free:
        if user.free_plan_runs_used >= user.free_plan_runs_limit:
            raise HTTPException(
                status_code=402,  # Payment Required
                detail=(
                    f"Free tier plan runs exhausted "
                    f"({user.free_plan_runs_limit} used). Upgrade to Premium for unlimited planning."
                ),
            )
        # increment usage counter
        user.free_plan_runs_used += 1
        db.add(user)
        db.commit()

    # 2. Ensure / get trip session + constraints for this user
    trip_session = get_or_create_trip_session(db, user.id)
    existing_constraints: PlanConstraints = load_constraints(trip_session)

    # 3. Also parse any extra planning language in "preference"
    if payload.preference:
        updated_constraints = parse_constraints_from_text(payload.preference, existing_constraints)
        if updated_constraints.model_dump() != existing_constraints.model_dump():
            save_constraints(db, trip_session, updated_constraints)
            constraints_used = updated_constraints
        else:
            constraints_used = existing_constraints
    else:
        constraints_used = existing_constraints

    # 4. Get this user's pending items
    intents: List[ItemIntent] = (
        db.query(ItemIntent)
        .filter(ItemIntent.user_id == payload.user_id)
        .filter(ItemIntent.status == "pending")
        .order_by(ItemIntent.created_at.asc())
        .all()
    )

    if not intents:
        raise HTTPException(status_code=400, detail="No pending items to plan for")

    # -----------------------------
    # NEW: free tier item limit
    # -----------------------------
    if is_free and len(intents) > user.free_items_limit:
        # We keep it simple for now:
        # - only plan for the first N items (oldest)
        # - the rest are ignored in this build
        intents = intents[: user.free_items_limit]

    # Convert items to simple dicts for the response
    items_for_response: List[Dict[str, Any]] = []
    for i in intents:
        items_for_response.append(
            {
                "id": str(i.id),
                "raw_text": i.raw_text,
                "canonical_category": i.canonical_category,
                "quantity": i.quantity,
                "attributes": i.attributes or {},
                "status": i.status,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
        )

    # 5. Build candidate plans (same as before, plus item id + store_name for discounts/watchlist)

    substitution_notes: List[str] = []

    origin_text = (payload.origin or "").strip()
    destination_text = (payload.destination or "").strip()
    if not destination_text and origin_text:
        destination_text = origin_text

    # ---- One-store plan: everything at Fred Meyer ----
    one_items = []
    one_total = 0.0
    for i in intents:
        # Try live-ish price from Fred Meyer demo catalog
        cat_price_info = price_from_catalog(i)
        if cat_price_info["price"] is not None:
            price = cat_price_info["price"]
            note = cat_price_info.get("note")
            if note:
                substitution_notes.append(note)
        else:
            # Fallback to simple estimator
            price = estimate_price_for_item(i, "fred_meyer")
        one_total += price
        one_items.append(
            {
                "id": str(i.id),  # NEW
                "raw_text": i.raw_text,
                "canonical_category": i.canonical_category,
                "quantity": i.quantity,
                "estimated_price": price,
                "store_id": FRED_MEYER_STORE_ID,
                "store_name": FRED_MEYER_STORE_NAME,
            }
        )

    one_store_plan = {
        "label": "One-store plan (Fred Meyer)",
        "stores": [
            {
                "id": FRED_MEYER_STORE_ID,
                "name": FRED_MEYER_STORE_NAME,
                "distance_minutes": 10.0,  # will be overwritten by Maps if origin provided
            }
        ],
        "number_of_stores": 1,
        "total_price": round(one_total, 2),
        "travel_minutes": 10.0,  # stub; overwritten by Maps if possible
        "items": one_items,
    }

    # ---- Two-store plan: Fred Meyer + WarehouseClub (Costco-like) ----
    two_items = []
    two_total = 0.0
    for i in intents:
        cat = (i.canonical_category or "other").lower()
        if cat in ("milk", "eggs", "cereal", "detergent"):
            store_kind = "warehouse_club"
            store_id = "warehouse_club"
            store_name = "WarehouseClub"
            travel_for_this = 18.0
        else:
            store_kind = "fred_meyer"
            store_id = FRED_MEYER_STORE_ID
            store_name = FRED_MEYER_STORE_NAME
            travel_for_this = 10.0

        # For Fred Meyer items, still try the catalog; for WarehouseClub, use estimator
        if store_kind == "fred_meyer":
            cat_price_info = price_from_catalog(i)
            if cat_price_info["price"] is not None:
                price = cat_price_info["price"]
                note = cat_price_info.get("note")
                if note:
                    substitution_notes.append(note)
            else:
                price = estimate_price_for_item(i, store_kind)
        else:
            price = estimate_price_for_item(i, store_kind)

        two_total += price
        two_items.append(
            {
                "id": str(i.id),  # NEW
                "raw_text": i.raw_text,
                "canonical_category": i.canonical_category,
                "quantity": i.quantity,
                "store_id": store_id,
                "store_name": store_name,
                "estimated_price": price,
                "travel_minutes": travel_for_this,
            }
        )

    two_travel = 18.0  # stub
    two_store_plan = {
        "label": "Two-store plan (Fred Meyer + WarehouseClub)",
        "stores": [
            {
                "id": FRED_MEYER_STORE_ID,
                "name": FRED_MEYER_STORE_NAME,
                "distance_minutes": 10.0,
            },
            {
                "id": "warehouse_club",
                "name": "WarehouseClub",
                "distance_minutes": 18.0,
            },
        ],
        "number_of_stores": 2,
        "total_price": round(two_total, 2),
        "travel_minutes": two_travel,
        "items": two_items,
    }

    # ---- Three-store demo: Fred Meyer + WarehouseClub + NeighborhoodMarket ----
    three_items = []
    three_total = 0.0
    for i in intents:
        cat = (i.canonical_category or "other").lower()
        if cat in ("milk", "eggs", "cereal"):
            store_kind = "warehouse_club"
            store_id = "warehouse_club"
            store_name = "WarehouseClub"
            travel_for_this = 18.0
        elif cat == "detergent":
            store_kind = "fred_meyer"
            store_id = FRED_MEYER_STORE_ID
            store_name = FRED_MEYER_STORE_NAME
            travel_for_this = 10.0
        else:
            store_kind = "neighborhood"
            store_id = "neighborhood_market"
            store_name = "NeighborhoodMarket"
            travel_for_this = 12.0

        # Catalog only for Fred Meyer items
        if store_kind == "fred_meyer":
            cat_price_info = price_from_catalog(i)
            if cat_price_info["price"] is not None:
                price = cat_price_info["price"]
                note = cat_price_info.get("note")
                if note:
                    substitution_notes.append(note)
            else:
                price = estimate_price_for_item(i, store_kind)
        else:
            price = estimate_price_for_item(i, store_kind)

        three_total += price
        three_items.append(
            {
                "id": str(i.id),  # NEW
                "raw_text": i.raw_text,
                "canonical_category": i.canonical_category,
                "quantity": i.quantity,
                "store_id": store_id,
                "store_name": store_name,
                "estimated_price": price,
                "travel_minutes": travel_for_this,
            }
        )

    three_travel = 20.0  # stub
    three_store_plan = {
        "label": "Three-store demo plan",
        "stores": [
            {
                "id": FRED_MEYER_STORE_ID,
                "name": FRED_MEYER_STORE_NAME,
                "distance_minutes": 10.0,
            },
            {
                "id": "warehouse_club",
                "name": "WarehouseClub",
                "distance_minutes": 18.0,
            },
            {
                "id": "neighborhood_market",
                "name": "NeighborhoodMarket",
                "distance_minutes": 12.0,
            },
        ],
        "number_of_stores": 3,
        "total_price": round(three_total, 2),
        "travel_minutes": three_travel,
        "items": three_items,
    }

    # 6. Apply Maps drive times (if origin/destination given)

    if origin_text or destination_text:
        augment_plan_with_drive_times(db, one_store_plan, origin_text, destination_text)
        augment_plan_with_drive_times(db, two_store_plan, origin_text, destination_text)
        augment_plan_with_drive_times(db, three_store_plan, origin_text, destination_text)

    # 7. Apply constraints to which plans are even allowed

    plans: Dict[str, Any] = {}

    def plan_allowed(plan_dict: Dict[str, Any]) -> bool:
        n = plan_dict.get("number_of_stores", 0)

        # Respect user constraints
        if constraints_used.max_stores is not None and n > constraints_used.max_stores:
            return False

        # Original constraints: avoid / must include costco
        if constraints_used.avoid_costco:
            for s in plan_dict.get("stores", []):
                if s.get("name") == "WarehouseClub":
                    return False
        if constraints_used.must_include_costco:
            has_warehouse = any(
                s.get("name") == "WarehouseClub" for s in plan_dict.get("stores", [])
            )
            if not has_warehouse:
                return False

        # -----------------------------
        # NEW: free plan → only 1 store
        # -----------------------------
        if is_free and n > 1:
            return False

        # -----------------------------
        # NEW: Costco gate by user flags
        # -----------------------------
        if not allow_costco:
            # user has neither membership nor addon; do not allow plans using WarehouseClub
            for s in plan_dict.get("stores", []):
                if s.get("name") == "WarehouseClub":
                    return False

        return True

    if plan_allowed(one_store_plan):
        plans["one_store"] = one_store_plan
    if plan_allowed(two_store_plan):
        plans["two_store"] = two_store_plan
    if plan_allowed(three_store_plan):
        plans["three_store"] = three_store_plan

    # If nothing survived constraints, fall back to one_store
    if not plans:
        plans["one_store"] = one_store_plan

    # 8. NEW: apply memberships + coupons on the surviving plans
    apply_memberships_and_coupons(db, user, plans)

    # 9. NEW: update watchlist price history from these plans
    update_watchlist_prices_from_plans(db, payload.user_id, plans)

    # 10. Choose recommended plan
    try:
        if len(plans) == 1:
            # Only one candidate -> no need to ask LLM
            recommended_plan = next(iter(plans.keys()))
            explanation = (
                f"I selected the '{recommended_plan}' plan because the others "
                f"did not satisfy your constraints or your current plan tier."
            )
        else:
            llm_choice = ask_llm_to_choose_plan(plans, payload.preference, constraints_used)
            recommended_plan = llm_choice.get("recommended_plan")
            explanation = llm_choice.get("explanation")
    except Exception:
        # If LLM fails, just default to first plan
        recommended_plan = next(iter(plans.keys()))
        explanation = (
            f"I defaulted to the '{recommended_plan}' plan because I could "
            "not evaluate preferences."
        )

    # 11. Append substitution notes (if any) to the explanation
    if substitution_notes:
        notes_block = "\n".join(f"- {n}" for n in substitution_notes)
        if explanation:
            explanation = (
                explanation
                + "\n\nSubstitutions & availability notes:\n"
                + notes_block
            )
        else:
            explanation = "Substitutions & availability notes:\n" + notes_block

    return PlanResponse(
        user_id=payload.user_id,
        items=items_for_response,
        plans=plans,
        recommended_plan=recommended_plan,
        explanation=explanation,
    )

@router.post("/price", response_model=PlanResponse)
def price_plan(
    payload: BuildPlanRequest,
    db: Session = Depends(get_db),
) -> PlanResponse:
    return build_plan(payload, db)
