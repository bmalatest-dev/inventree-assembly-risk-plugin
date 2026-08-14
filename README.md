# InvenTree Assembly Risk Plugin

Read-only InvenTree plugin which flags components where all active Build Orders can consume nearly all usable physical stock, leaving little or no contingency for normal assembly loss.

## Scope of v0.1.0

- Adds an **Assembly Risk** panel to Build Order pages.
- Reads **all active Build Orders** and their current remaining output quantities.
- Uses **physical StockItems only**. `On Order` is displayed separately and never makes current physical risk look safe.
- Excludes blank/null stock locations, all locations containing **Rework**, and the same verification / shipping / storage locations used by the existing BO consolidator script.
- Respects `Allow Variants` using the InvenTree Part variant tree.
- Performs an in-memory allocation simulation only. It **does not create, modify, or auto-allocate stock in InvenTree**.
- Ports the existing script's spillage thresholds and Assembly Risk classifications.
- Normal (>20 buffer) rows are hidden by default and can be enabled in plugin settings.

## Risk classifications

- **CRITICAL - UNFILLED**: usable physical stock cannot satisfy active BO demand.
- **Exact BOM quantity**: all demand can be met, but no physical buffer remains.
- **Critical low buffer**: physical buffer is below planned spillage.
- **Low buffer**: buffer is small / only meets planned spillage.
- **Limited buffer**: buffer is 20 units or less.
- **Normal spillage allowed**: buffer is above 20 units.

## Installation for development / internal review

From the repository root:

```bash
pip install -e .
```

Then restart InvenTree, scan for plugins if necessary, activate **Assembly Risk**, and ensure the global **Enable Interface Plugins** setting is enabled.

For a GitHub-hosted repository, InvenTree's plugin installer can install it using the package/repository URL in the same way as other Git-hosted plugins.

## Test procedure

1. Pick a component required by one or more active BOs.
2. Put exactly enough usable stock in verified production locations to cover all active demand.
3. Open one of the affected Build Orders. The Assembly Risk panel should show **Exact BOM quantity**.
4. Add a small amount of stock; the status should move through Critical Low / Low / Limited according to the existing script thresholds.
5. Move the extra stock to a location containing `Rework`; refresh the BO. It must no longer count in the physical buffer.
6. Add quantity to an incoming PO. The **On Order** column may show it, but physical buffer / risk must remain unchanged until stock is received.

## Important implementation note

This first version intentionally separates Assembly Risk from the Procurement Buy Report. The reusable calculation helpers live in `engine.py` so procurement logic can later share the same location, spillage and risk rules without merging the two UI features.

## Compatibility / developer review

The plugin targets the current InvenTree plugin API (`UserInterfaceMixin`) and current Build / Stock model interfaces. Because it reads InvenTree Django models directly, it should be validated against the exact production InvenTree version before rollout. The code is read-only and does not mutate inventory or Build Orders.
