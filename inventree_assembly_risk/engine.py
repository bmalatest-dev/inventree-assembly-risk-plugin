"""Pure assembly-risk calculation helpers.

The Django-facing data collection stays in plugin.py. Keeping the classification
logic here makes it testable without an InvenTree installation and provides a
future shared base for a Procurement Buy Report plugin.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

PASSIVE_FOOTPRINT_SPILLAGE = {
    "0201": Decimal("200"),
    "0402": Decimal("100"),
    "0603": Decimal("50"),
    "0805": Decimal("25"),
    "1206": Decimal("20"),
    "1210": Decimal("20"),
}

DEFAULT_EXCLUDED_LOCATION_NAMES = {
    "not verified assembly room",
    "not verified component room",
    "not verified rework area",
    "rework area",
    "rework room- eval boards",
    "shipping room",
    "storage room",
}


def dec(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def fmt(value: Decimal) -> str:
    value = dec(value)
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def normalize_footprint(value: str) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"\b(0201|0402|0603|0805|1206|1210)\b", text)
    return match.group(1) if match else text


def is_basic_passive(category: str) -> bool:
    text = str(category or "").strip().lower()
    return any(word in text for word in ("resistor", "capacitor", "inductor"))


def outstanding_requirement(bom_remaining, allocated, spillage) -> tuple[Decimal, Decimal]:
    """Calculate outstanding Production demand for one BuildLine.

    Overage is only required while actual BOM demand remains unallocated.

    Examples:
        BOM 22, allocated 22, overage 5 -> outstanding 0
        BOM 22, allocated 10, overage 2 -> outstanding 14
        BOM 62, allocated 0, overage 2  -> outstanding 64
    """
    bom_remaining = max(dec(bom_remaining), Decimal("0"))
    allocated = max(dec(allocated), Decimal("0"))
    spillage = max(dec(spillage), Decimal("0"))

    unallocated_bom = max(bom_remaining - allocated, Decimal("0"))

    if unallocated_bom <= 0:
        return Decimal("0"), Decimal("0")

    return unallocated_bom, unallocated_bom + spillage


def spillage_for_part(footprint: str, pricing_max, category: str) -> tuple[Decimal, str]:
    """Port of the spillage rules from inventree_bo_stock_consolidator."""
    fp = normalize_footprint(footprint)
    price = dec(pricing_max)

    if price <= 0:
        if is_basic_passive(category) and fp in PASSIVE_FOOTPRINT_SPILLAGE:
            return PASSIVE_FOOTPRINT_SPILLAGE[fp], f"missing_price_passive_footprint_{fp}"
        if is_basic_passive(category):
            return Decimal("5"), "missing_price_passive_unknown_footprint_default_5"
        return Decimal("5"), "missing_price_non_passive_default_5"

    if fp in PASSIVE_FOOTPRINT_SPILLAGE:
        return PASSIVE_FOOTPRINT_SPILLAGE[fp], f"footprint_{fp}"
    if price > 200:
        return Decimal("0"), "price_over_200"
    if price > 50:
        return Decimal("1"), "price_50_to_200"
    if price > 10:
        return Decimal("2"), "price_10_to_50"
    return Decimal("5"), "price_under_10_or_unknown"


@dataclass(frozen=True)
class RiskResult:
    severity: str
    label: str
    message: str


def classify_risk(*, physical_buffer, spillage=0, shortage=0) -> RiskResult:
    """Classify the final buffer after BOM demand and planned overage are applied.

    ``spillage`` remains an accepted argument for backwards compatibility and
    display context, but it is not subtracted again here. The Production Demand
    Snapshot already includes planned spillage / overage in outstanding demand.
    """
    physical_buffer = max(dec(physical_buffer), Decimal("0"))
    shortage = max(dec(shortage), Decimal("0"))

    if shortage > 0:
        return RiskResult(
            "critical",
            "CRITICAL - UNFILLED",
            f"{fmt(shortage)} of Production demand (including planned overage) is not covered by usable physical stock.",
        )
    if physical_buffer <= 0:
        return RiskResult(
            "critical",
            "Exact planned quantity",
            "No physical buffer remains after all Production demand and planned overage; minimize setup loss and return all unused parts.",
        )
    if physical_buffer <= 2:
        return RiskResult(
            "critical",
            "Critical low buffer",
            f"Only {fmt(physical_buffer)} extra remain after all Production demand and planned overage.",
        )
    if physical_buffer <= 5:
        return RiskResult(
            "warning",
            "Low buffer",
            f"Only {fmt(physical_buffer)} extra remain after all Production demand and planned overage.",
        )
    if physical_buffer <= 20:
        return RiskResult(
            "warning",
            "Limited buffer",
            f"{fmt(physical_buffer)} extra remain after all Production demand and planned overage.",
        )
    return RiskResult(
        "ok",
        "Normal spillage allowed",
        f"{fmt(physical_buffer)} extra remain after all Production demand and planned overage.",
    )


def location_is_excluded(path_parts: Iterable[str], extra_names: Iterable[str] = ()) -> bool:
    """Return True for the same excluded stock-location semantics as the script."""
    names = DEFAULT_EXCLUDED_LOCATION_NAMES | {str(x).strip().lower() for x in extra_names if str(x).strip()}
    values = [str(x or "").strip() for x in path_parts]
    # A StockItem with no location is still physical stock. The original CSV
    # workflow excluded blank locations because location hygiene was uncertain,
    # but inside InvenTree itself the StockItem record is authoritative. Only
    # explicitly excluded locations (including any Rework ancestor) are ignored.
    if not any(values):
        return False
    for value in values:
        norm = value.lower()
        if not norm:
            continue
        if "rework" in norm:
            return True
        if norm in names:
            return True
    return False
