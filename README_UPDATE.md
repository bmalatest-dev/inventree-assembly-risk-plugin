# Assembly Risk v0.5.0 update

This release makes Assembly Risk allocation-aware and establishes a reusable Production Demand Snapshot for the future Packing List integration.

## Calculation flow

Production Build Orders → BuildLine remaining requirement → standard price/footprint overage → existing BuildItem allocations → outstanding demand → StockItem free balances → virtual allocation of outstanding demand → final buffers.

Key changes:

- Only Build Orders in **Production** status contribute demand.
- Demand is read from the actual `BuildLine` records, including consumed quantity.
- Existing `BuildItem` allocations are credited only to the BuildLine / BO which owns them.
- Exact StockItem IDs for existing allocations are retained in the snapshot.
- A StockItem's free balance is its physical quantity less all active InvenTree allocations (Build, Sales Order and Transfer Order).
- Existing allocated stock is therefore never reused by the virtual allocation simulation.
- Standard overage remains based on the existing footprint / pricing rules.
- Standard overage is included in outstanding Production demand before virtual allocation.
- Risk thresholds are applied to the final buffer after all Production demand and planned overage; overage is not counted twice.
- The plugin remains read-only and never creates or changes allocations.

## Reuse by Packing List

`production_demand_snapshot()` exposes the same cached Production snapshot used by the dashboard and BO panel.

`assembly_risk_for_stock_item(build_id, stock_item_id)` returns the risk context for a specific BO / StockItem pair, including the BO's remaining BOM demand, current allocation, outstanding demand, overall compatible physical buffer, StockItem free quantity before simulation, and StockItem final free quantity.

## Files changed

- `inventree_assembly_risk/plugin.py`
- `inventree_assembly_risk/engine.py`
- `setup.py`
- `tests/test_engine.py`

Plugin version: **0.5.0**
