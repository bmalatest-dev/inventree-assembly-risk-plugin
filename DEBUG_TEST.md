# Assembly Risk Debug Test - v0.5.1

Temporary diagnostic update.

The Assembly Risk service now includes a `debug` payload in
`assembly_risk_for_stock_item(build_id, stock_item_id)`.

The payload contains:
- every relevant physical StockItem;
- its full location path;
- whether Assembly Risk excluded it because of location;
- physical quantity;
- total active InvenTree allocations;
- raw and usable free quantities;
- every Production BuildLine for the part;
- BOM remaining demand;
- planned overage and rule;
- existing allocations;
- virtual allocations;
- unfilled demand.

Use together with Packing List v0.2.1, which writes this payload into a temporary
`Assembly Risk Debug` CSV column.
