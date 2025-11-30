# backend/constraints_nlp.py
import re

from .models import PlanConstraints


def _parse_int_after_word(text: str, word: str) -> int | None:
    """
    e.g. "only 2 stores", "max 3 shops" -> 2 or 3
    """
    pattern = rf"{word}\s+(\d+)"
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def extract_constraints_from_message(
    message: str,
    existing: PlanConstraints | None = None,
) -> PlanConstraints:
    """
    Reads a natural-language message and updates PlanConstraints.

    Examples:
      - "only 2 stores"         -> max_stores = 2
      - "avoid costco"          -> avoid_costco = True
      - "cheapest gas also"     -> include_cheapest_gas = True
      - "cheapest overall"      -> optimize_for = "cheapest_overall"
      - "fastest drive"         -> optimize_for = "fastest_drive"
      - "I only want Costco + one grocery store"
                                -> must_include_costco = True, max_stores = 2
    """
    text = message.lower()
    c = existing or PlanConstraints()

    # --- max stores / "only N stores" / "max N stores" ---
    for trigger in ["only", "max", "at most"]:
        n = _parse_int_after_word(text, trigger)
        if n is not None:
            c.max_stores = n
            break

    # --- avoid Costco ---
    if (
        "avoid costco" in text
        or "no costco" in text
        or "dont go to costco" in text
        or "don't go to costco" in text
    ):
        c.avoid_costco = True
        c.must_include_costco = False  # override if previously set

    # --- "I only want costco + one grocery store" style ---
    if (
        "only costco" in text
        or "costco + one grocery" in text
        or "costco and one grocery" in text
        or "costco and one other grocery" in text
    ):
        c.must_include_costco = True
        c.max_stores = 2
        c.avoid_costco = False

    # --- cheapest gas ---
    if "cheapest gas" in text or "cheap gas" in text:
        c.include_cheapest_gas = True

    # --- optimize_for: cheapest overall / fastest drive ---
    if (
        "cheapest overall" in text
        or "lowest total cost" in text
        or "as cheap as possible" in text
    ):
        c.optimize_for = "cheapest_overall"
    elif (
        "fastest drive" in text
        or "fastest route" in text
        or "as fast as possible" in text
    ):
        c.optimize_for = "fastest_drive"

    # You can keep extending this rule set over time when you see real user phrases.

    return c
