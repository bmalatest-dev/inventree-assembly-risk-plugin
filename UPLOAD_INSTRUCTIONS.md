# Upload instructions for v0.5.4

The current GitHub source already contains the corrected final-buffer risk
classification. Do not restore the older logic which subtracts spillage from
physical_buffer inside classify_risk().

## GitHub changes

Upload / replace:
- inventree_assembly_risk/engine.py
- tests/test_engine.py
- setup.py
- UPDATE_NOTES_v0.5.4.md

For `inventree_assembly_risk/plugin.py`, apply the changes in
`plugin_v0.5.4.patch`:
1. import `audit_totals`
2. change VERSION from 0.5.3 to 0.5.4
3. add the `audit = audit_totals(...)` block immediately after `demand_debug`
   is built
4. return `"audit": audit` immediately before the existing `"debug": {...}`

## Validation

Run:
    pytest -q

Then reinstall/update Assembly Risk in InvenTree and verify:
- Plugin version is 0.5.4
- A fully allocated BO line shows zero new outstanding demand
- ADM7150 reconciliation produces 67 usable free, 64 demand, final buffer 3
- Rework / excluded locations do not contribute usable free stock
