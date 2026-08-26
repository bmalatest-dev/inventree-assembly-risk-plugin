# Assembly Risk v0.5.4

v0.5.4 is a validation / integration cleanup release built on the known-good
v0.5.3 allocation-aware Production Demand Snapshot.

## Calculation behavior retained

- Existing BuildItem allocations are removed from StockItem free quantity.
- Existing allocations are also credited against the owning BuildLine.
- A fully allocated BuildLine contributes zero additional overage demand.
- Planned overage is included in outstanding Production demand before virtual
  allocation.
- Risk classification uses the final physical buffer and does not subtract
  planned overage a second time.
- Explicitly excluded / Rework stock remains outside usable physical stock.

## New: concise audit totals

`assembly_risk_for_stock_item()` now returns an `audit` object alongside the
existing temporary verbose `debug` object.

The new audit object contains:

- `gross_physical_quantity`
- `existing_allocations`
- `free_before_location_exclusions`
- `excluded_free_stock`
- `usable_free_before_demand`
- `outstanding_production_demand`
- `physical_buffer_after_all_production_demand`
- `global_shortage`

These fields are intended for the Packing List plugin so it can display concise,
human-readable quantities without parsing the full diagnostic JSON.

## ADM7150 validation case

The regression test includes the reconciled example:

- StockItem gross quantity: 73
- Existing allocation: 36
- Free on that StockItem: 37
- Additional usable free stock: 30
- Total usable free stock: 67
- Outstanding Production demand including overage: 64
- Final physical buffer: 3

This is expected to classify as Low buffer.

## Files to update

1. Replace `inventree_assembly_risk/engine.py`
2. Apply `plugin_v0.5.4.patch` to `inventree_assembly_risk/plugin.py`
3. Replace `tests/test_engine.py`
4. Replace root `setup.py`
5. Add `UPDATE_NOTES_v0.5.4.md`

After updating GitHub, reinstall/update the plugin in InvenTree and confirm the
Plugin Detail page reports version 0.5.4.
