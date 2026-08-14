from decimal import Decimal

from inventree_assembly_risk.engine import classify_risk, location_is_excluded, spillage_for_part


def test_exact_bom_is_critical():
    r = classify_risk(physical_buffer=0, spillage=5)
    assert r.severity == "critical"
    assert r.label == "Exact BOM quantity"


def test_shortage_beats_buffer():
    r = classify_risk(physical_buffer=50, spillage=5, shortage=2)
    assert r.label == "CRITICAL - UNFILLED"


def test_passive_spillage():
    qty, rule = spillage_for_part("0402", 0, "Resistors")
    assert qty == Decimal("100")
    assert "0402" in rule


def test_rework_descendant_excluded():
    assert location_is_excluded(["Main", "Rework", "Computer Building Area"])


def test_good_location_allowed():
    assert not location_is_excluded(["Main", "Component Room", "Shelf A"])


def test_unlocated_stock_allowed():
    # A StockItem without a location is still physical stock inside InvenTree.
    assert not location_is_excluded([])
    assert not location_is_excluded([""])
