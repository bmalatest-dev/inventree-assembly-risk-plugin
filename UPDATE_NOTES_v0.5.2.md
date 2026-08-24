# Assembly Risk v0.5.2

This update fixes two issues identified from the ADM7150ACPZ-5.0-R7 debug case.

## 1. Price source

Assembly Risk now prefers the maximum non-zero `StockItem.purchase_price` for
in-stock StockItems of the required part. This aligns the overage price band with
the purchase-price data visible in the Packing List.

If no StockItem purchase price exists, Part-level pricing remains a fallback.

The debug output now reports:
- `pricing_max`
- `pricing_source`

## 2. Overage on fully allocated BuildLines

Old behavior:

    outstanding = BOM remaining + overage - allocated

This could create new overage demand even when the BOM requirement was already
fully allocated.

New behavior:

    unallocated BOM = max(BOM remaining - allocated, 0)

    if unallocated BOM > 0:
        outstanding = unallocated BOM + overage
    else:
        outstanding = 0

Thus, a fully allocated Production BuildLine contributes no new demand.

## Debug

The v0.5.1 debug payload is retained so the next Packing List export can verify:
- pricing source and value
- location exclusions
- existing allocations
- unallocated BOM demand
- applied overage
- virtual allocation
- final buffer / shortage

Packing List debug v0.2.1 does not need to be changed.
