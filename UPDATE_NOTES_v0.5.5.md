# Assembly Risk v0.5.5 — scoped Production demand

This release adds an optional Build Order scope to the existing v0.5.4
allocation-aware calculation engine.

## Why

"All Production BOs" is useful for company-wide planning, but it can overstate
demand when a packing list is being generated for one project or one selected
set of builds.

## Public API

```python
assembly_risk_for_stock_item(
    build_id,
    stock_item_id,
    included_build_ids=None,
)
```

Behavior:

- `included_build_ids=None`
  - legacy behavior
  - all Production BOs contribute future demand
- `included_build_ids=[...]`
  - only those Production BOs contribute future demand
  - the queried `build_id` is always included automatically

Important: allocations belonging to unselected BOs still reduce free physical
stock. This is intentional because already-reserved stock cannot safely be
treated as available to the selected project.

## Cache

The cache key now includes the normalized build scope, preventing a calculation
for one project from being reused for another project.

## Returned scope metadata

The per-StockItem result now includes:

```python
"scope": {
    "mode": "selected_builds" | "all_production",
    "included_build_ids": [...],
    "included_build_refs": [...],
}
```

## Files

- ADD `inventree_assembly_risk/scope.py`
- APPLY `plugin_v0.5.5.patch`
- APPLY `setup_v0.5.5.patch`
- ADD `tests/test_scope.py`
