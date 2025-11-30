# app/catalog/fredmeyer_demo.py

from __future__ import annotations

from typing import List, Dict, Any, Optional

from app.models.item_intent import ItemIntent

FRED_MEYER_STORE_ID = "fred_meyer_demo"
FRED_MEYER_STORE_NAME = "Fred Meyer (demo)"


# Very small demo catalog: enough to exercise matching & substitutions.
# In a real version, you’d load this from a JSON file or DB.
FRED_MEYER_SKUS: List[Dict[str, Any]] = [
    # Milk
    {
        "sku": "fm_milk_2pct_1gal",
        "canonical_category": "milk",
        "name": "Fred Meyer 2% Milk 1 Gallon",
        "brand": "Fred Meyer",
        "volume": "1 gallon",
        "fat_level": "2%",
        "lactose_free": False,
        "price": 3.79,
    },
    {
        "sku": "fm_milk_2pct_1gal_lf",
        "canonical_category": "milk",
        "name": "Fred Meyer 2% Lactose Free Milk 1 Gallon",
        "brand": "Fred Meyer",
        "volume": "1 gallon",
        "fat_level": "2%",
        "lactose_free": True,
        "price": 4.69,
    },
    {
        "sku": "fm_milk_1pct_1gal",
        "canonical_category": "milk",
        "name": "Fred Meyer 1% Milk 1 Gallon",
        "brand": "Fred Meyer",
        "volume": "1 gallon",
        "fat_level": "1%",
        "lactose_free": False,
        "price": 3.59,
    },

    # Eggs
    {
        "sku": "fm_eggs_large_12",
        "canonical_category": "eggs",
        "name": "Fred Meyer Large Eggs 12 ct",
        "brand": "Fred Meyer",
        "egg_size": "large",
        "count": 12,
        "price": 2.49,
    },
    {
        "sku": "fm_eggs_large_18",
        "canonical_category": "eggs",
        "name": "Fred Meyer Large Eggs 18 ct",
        "brand": "Fred Meyer",
        "egg_size": "large",
        "count": 18,
        "price": 3.59,
    },

    # Cereal
    {
        "sku": "fm_cereal_cornflakes_18oz",
        "canonical_category": "cereal",
        "name": "Kellogg's Corn Flakes 18 oz",
        "brand": "Kellogg",
        "flavor": "corn flakes",
        "size_oz": 18,
        "price": 4.29,
    },
    {
        "sku": "fm_cereal_frootloops_14oz",
        "canonical_category": "cereal",
        "name": "Kellogg's Froot Loops 14 oz",
        "brand": "Kellogg",
        "flavor": "froot loops",
        "size_oz": 14,
        "price": 4.49,
    },

    # Detergent
    {
        "sku": "fm_detergent_tide_pods_42ct",
        "canonical_category": "detergent",
        "name": "Tide Pods Laundry Detergent 42 ct",
        "brand": "Tide",
        "type": "pods",
        "count": 42,
        "price": 14.99,
    },
    {
        "sku": "fm_detergent_tide_liquid_64",
        "canonical_category": "detergent",
        "name": "Tide Liquid Laundry Detergent 64 loads",
        "brand": "Tide",
        "type": "liquid",
        "loads": 64,
        "price": 13.99,
    },
]


def _score_sku(intent: ItemIntent, sku: Dict[str, Any]) -> int:
    """
    Simple heuristic matching score between an ItemIntent and a SKU.
    Higher is better.
    """
    score = 0
    attrs = intent.attributes or {}

    # Category must match to be considered at all
    cat_intent = (intent.canonical_category or "").lower()
    cat_sku = (sku.get("canonical_category") or "").lower()
    if cat_intent and cat_intent == cat_sku:
        score += 5
    else:
        # no category match -> we effectively won't consider this
        return 0

    # Fat level (milk)
    fat_intent = attrs.get("fat_level")
    if fat_intent and fat_intent == sku.get("fat_level"):
        score += 3

    # Volume (milk)
    vol_intent = attrs.get("volume")
    if vol_intent and vol_intent.lower() == str(sku.get("volume", "")).lower():
        score += 2

    # Lactose-free (milk)
    lf_intent = attrs.get("lactose_free")
    if lf_intent is not None and bool(lf_intent) == bool(sku.get("lactose_free")):
        score += 2

    # Brand
    brand_intent = attrs.get("brand")
    if brand_intent:
        if brand_intent.lower() in (sku.get("brand", "") or "").lower():
            score += 2
        if brand_intent.lower() in (sku.get("name", "") or "").lower():
            score += 1

    # Egg size
    egg_size_intent = attrs.get("egg_size")
    if egg_size_intent and egg_size_intent == sku.get("egg_size"):
        score += 2

    # Cereal flavor
    flavor_intent = attrs.get("flavor")
    if flavor_intent and flavor_intent.lower() in (sku.get("flavor", "") or "").lower():
        score += 2

    # Detergent type
    dtype_intent = attrs.get("type")
    if dtype_intent and dtype_intent.lower() == (sku.get("type", "") or "").lower():
        score += 2

    return score


def match_skus_for_intent(intent: ItemIntent) -> Dict[str, Any]:
    """
    Return best SKU + a few alternatives for this intent in Fred Meyer.

    Returns:
      {
        "exact": SKU dict or None,
        "alternatives": [SKU dict, ...],
        "note": Optional[str]
      }
    """
    cat = (intent.canonical_category or "").lower()
    if not cat:
        return {"exact": None, "alternatives": [], "note": None}

    # Filter SKUs by category first
    candidates = [
        sku for sku in FRED_MEYER_SKUS
        if (sku.get("canonical_category") or "").lower() == cat
    ]
    if not candidates:
        return {"exact": None, "alternatives": [], "note": None}

    # Score and sort
    scored = []
    for sku in candidates:
        s = _score_sku(intent, sku)
        if s > 0:
            scored.append((s, sku))

    if not scored:
        return {"exact": None, "alternatives": [], "note": None}

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_sku = scored[0]
    alt_skus = [sku for (_s, sku) in scored[1:4]]

    # Decide if "exact" or "approximate"
    attrs = intent.attributes or {}
    exact = True

    for key in ["fat_level", "volume", "lactose_free", "egg_size", "flavor", "type"]:
        if key in attrs:
            if attrs[key] != best_sku.get(key):
                exact = False
                break

    note: Optional[str] = None
    if not exact:
        # Build human-friendly note for substitutions
        intent_desc = intent.raw_text or (intent.canonical_category or "item")
        alt_names = ", ".join(s["name"] for s in alt_skus) if alt_skus else ""
        if alt_names:
            note = (
                f'At {FRED_MEYER_STORE_NAME}, I couldn’t find an exact match for "{intent_desc}". '
                f'I suggest "{best_sku["name"]}" instead. Other close options: {alt_names}.'
            )
        else:
            note = (
                f'At {FRED_MEYER_STORE_NAME}, I couldn’t find an exact match for "{intent_desc}". '
                f'I suggest "{best_sku["name"]}" as the closest alternative.'
            )

    return {
        "exact": best_sku if exact else None,
        "alternatives": [best_sku] + alt_skus,
        "note": note,
    }


def price_from_catalog(intent: ItemIntent) -> Dict[str, Any]:
    """
    Try to price an intent from the Fred Meyer demo catalog.

    Returns:
      {
        "price": float | None,
        "note": Optional[str]
      }
    """
    matches = match_skus_for_intent(intent)
    # No viable candidates
    if not matches["exact"] and not matches["alternatives"]:
        return {"price": None, "note": None}

    # If we have an exact match, use that; otherwise use the best alternative
    sku = matches["exact"] or matches["alternatives"][0]
    qty = max(intent.quantity or 1, 1)
    price = round(float(sku["price"]) * qty, 2)
    return {"price": price, "note": matches["note"]}
