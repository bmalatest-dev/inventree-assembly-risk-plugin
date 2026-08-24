# Assembly Risk v0.5.3

v0.5.3 is rebuilt directly from the known-good v0.5.1 plugin structure.

This intentionally avoids carrying forward the suspect v0.5.2 installation while
retaining the two required calculation fixes.

## Fix 1 - Unit price

Assembly Risk now prefers actual non-zero StockItem purchase prices for the exact
required part.

This allows the standard overage price bands to use the same underlying price
data visible in the Packing List.

Debug output reports:
- pricing_max
- pricing_source

## Fix 2 - Overage only on unallocated BOM demand

New calculation:

    unallocated_bom = max(bom_remaining - existing_allocations, 0)

    if unallocated_bom > 0:
        outstanding = unallocated_bom + standard_overage
    else:
        outstanding = 0

A fully allocated BuildLine therefore contributes no additional overage demand.

## Debug

The v0.5.1 diagnostic payload remains enabled for the next validation export.

For ADM7150ACPZ-5.0-R7, the next test should show:
- fully allocated BO lines with zero outstanding demand;
- a non-zero pricing_max;
- a price-based overage rather than missing_price_non_passive_default_5.
