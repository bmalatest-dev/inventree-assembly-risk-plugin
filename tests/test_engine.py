from decimal import Decimal

from inventree_assembly_risk.engine import classify_risk, location_is_excluded, outstanding_requirement, spillage_for_part


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


def test_fully_allocated_line_does_not_add_spillage_demand():
    unallocated, outstanding = outstanding_requirement(22, 22, 5)
    assert unallocated == Decimal("0")
    assert outstanding == Decimal("0")


def test_partially_allocated_line_adds_spillage_to_remaining_bom_only():
    unallocated, outstanding = outstanding_requirement(22, 10, 2)
    assert unallocated == Decimal("12")
    assert outstanding == Decimal("14")


def test_unallocated_line_adds_standard_spillage():
    unallocated, outstanding = outstanding_requirement(62, 0, 2)
    assert unallocated == Decimal("62")
    assert outstanding == Decimal("64")
