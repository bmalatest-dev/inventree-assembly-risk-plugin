from decimal import Decimal

from inventree_assembly_risk.engine import (
    audit_totals,
    classify_risk,
    location_is_excluded,
    outstanding_requirement,
    spillage_for_part,
)


def test_exact_planned_quantity_is_critical():
    r = classify_risk(physical_buffer=0, spillage=5)
    assert r.severity == "critical"
    assert r.label == "Exact planned quantity"


def test_shortage_beats_buffer():
    r = classify_risk(physical_buffer=50, spillage=5, shortage=2)
    assert r.label == "CRITICAL - UNFILLED"


def test_final_buffer_thresholds_do_not_double_count_spillage():
    assert classify_risk(physical_buffer=2, spillage=100).label == "Critical low buffer"
    assert classify_risk(physical_buffer=5, spillage=100).label == "Low buffer"
    assert classify_risk(physical_buffer=20, spillage=100).label == "Limited buffer"
    assert classify_risk(physical_buffer=21, spillage=100).label == "Normal spillage allowed"


def test_passive_spillage():
    qty, rule = spillage_for_part("0402", 0, "Resistors")
    assert qty == Decimal("100")
    assert "0402" in rule


def test_rework_descendant_excluded():
    assert location_is_excluded(["Main", "Rework", "Computer Building Area"])


def test_good_location_allowed():
    assert not location_is_excluded(["Main", "Component Room", "Shelf A"])


def test_unlocated_stock_allowed():
    assert not location_is_excluded([])
    assert not location_is_excluded([""])


def test_fully_allocated_line_has_no_new_overage_demand():
    unallocated, outstanding = outstanding_requirement(22, 22, 5)
    assert unallocated == Decimal("0")
    assert outstanding == Decimal("0")


def test_partial_allocation_applies_overage_to_remaining_bom():
    unallocated, outstanding = outstanding_requirement(22, 10, 2)
    assert unallocated == Decimal("12")
    assert outstanding == Decimal("14")


def test_unallocated_line_applies_standard_overage():
    unallocated, outstanding = outstanding_requirement(62, 0, 2)
    assert unallocated == Decimal("62")
    assert outstanding == Decimal("64")


def test_audit_totals_distinguish_gross_allocated_excluded_and_usable():
    inventory = [
        {
            "quantity": Decimal("73"),
            "allocated": Decimal("36"),
            "raw_free": Decimal("37"),
            "usable_free": Decimal("37"),
            "excluded_by_location": False,
        },
        {
            "quantity": Decimal("30"),
            "allocated": Decimal("0"),
            "raw_free": Decimal("30"),
            "usable_free": Decimal("30"),
            "excluded_by_location": False,
        },
        {
            "quantity": Decimal("10"),
            "allocated": Decimal("0"),
            "raw_free": Decimal("10"),
            "usable_free": Decimal("0"),
            "excluded_by_location": True,
        },
    ]
    demand = [
        {"outstanding_before_virtual_allocation": Decimal("0")},
        {"outstanding_before_virtual_allocation": Decimal("64")},
    ]

    totals = audit_totals(inventory, demand)

    assert totals["gross_physical_quantity"] == Decimal("113")
    assert totals["existing_allocations"] == Decimal("36")
    assert totals["free_before_location_exclusions"] == Decimal("77")
    assert totals["excluded_free_stock"] == Decimal("10")
    assert totals["usable_free_before_demand"] == Decimal("67")
    assert totals["outstanding_production_demand"] == Decimal("64")


def test_audit_totals_match_adm7150_reconciliation():
    inventory = [
        {
            "quantity": 73,
            "allocated": 36,
            "raw_free": 37,
            "usable_free": 37,
            "excluded_by_location": False,
        },
        {
            "quantity": 30,
            "allocated": 0,
            "raw_free": 30,
            "usable_free": 30,
            "excluded_by_location": False,
        },
    ]
    demand = [
        {"outstanding_before_virtual_allocation": 0},
        {"outstanding_before_virtual_allocation": 64},
    ]

    totals = audit_totals(inventory, demand)

    assert totals["usable_free_before_demand"] - totals["outstanding_production_demand"] == Decimal("3")
