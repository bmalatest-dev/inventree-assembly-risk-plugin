# InvenTree Assembly Risk Plugin

Read-only InvenTree plugin which flags components where active Build Orders can consume nearly all usable physical stock, leaving little or no contingency for normal assembly loss.

## v0.2.0

This release provides both requested views:

- **Build Order level** — an **Assembly Risk** panel on individual Build Order pages.
- **Global** — an **Assembly Risk - All Open Build Orders** dashboard widget showing risk across all active Build Orders.

The global widget can be added from the InvenTree dashboard using **Add Widget**.

## Calculation behavior

- Reads **all active Build Orders** and their unfinished output quantities.
- Uses **physical StockItems only** for physical assembly risk.
- `On Order` is shown separately and **never** makes current physical risk look safe.
- Excludes blank/null locations, any location containing **Rework**, and the verification / shipping / storage exclusions used by the existing BO consolidator script.
- Respects BOM `Allow Variants` through the InvenTree Part variant tree.
- Performs an in-memory allocation simulation only. It **does not create, modify, or auto-allocate stock**.
- Uses the existing script's spillage thresholds and risk classifications.

## Risk classifications

- **CRITICAL - UNFILLED** — usable physical stock cannot satisfy active BO demand.
- **Exact BOM quantity** — demand can be met, but no physical buffer remains.
- **Critical low buffer** — physical buffer is below planned spillage.
- **Low buffer** — buffer is small / only meets planned spillage.
- **Limited buffer** — buffer is 20 units or less.
- **Normal spillage allowed** — buffer is above 20 units.

## Settings

- **Additional excluded stock locations** — comma-separated location names to exclude in addition to the defaults.
- **Show normal-risk rows on Build Orders** — disabled by default.
- **Show normal-risk rows globally** — disabled by default.

## Installation / update

Install from the Git repository through the InvenTree Plugin Settings UI. After updating the repository, reinstall / update the plugin and reload plugins or restart InvenTree as required by your deployment.

Ensure the InvenTree global **Enable Interface Plugins** setting is enabled.

## Test procedure

1. Open a Build Order and confirm an **Assembly Risk** panel appears in its left-side panel list.
2. On the dashboard, choose **Add Widget** and add **Assembly Risk - All Open Build Orders**.
3. Pick a component required by one or more active BOs.
4. Put exactly enough usable stock in production locations to cover all active demand; expect **Exact BOM quantity**.
5. Add a small amount of physical stock; expect the status to move through Critical Low / Low / Limited according to the existing thresholds.
6. Move the extra stock into a location containing `Rework`; refresh. It must stop contributing to physical buffer.
7. Add incoming PO quantity; `On Order` may increase, but physical buffer / risk must remain unchanged until receipt.

## Scope

Assembly Risk remains intentionally separate from the future Procurement Buy Report. Shared calculation helpers live in `engine.py` so procurement logic can later reuse the same stock-location, spillage and risk rules.
