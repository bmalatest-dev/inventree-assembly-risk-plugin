# Assembly Risk v0.5.7

## Fix: Build Order plugin panel loading timeout

In v0.5.6, `get_ui_panels()` calculated Assembly Risk rows before returning
the panel definition. InvenTree aggregates plugin panel definitions into one
request, so the Assembly Risk calculation could delay other Build Order
plugins (including Smart Build Allocation) long enough for the frontend
request to time out.

v0.5.7 changes the Build Order panel to:

1. Register the Assembly Risk panel immediately with no risk calculation.
2. Load Assembly Risk data asynchronously after the panel has rendered.
3. Perform the existing calculation through `/plugin/assembly-risk/build/<id>/`.
4. Preserve the existing risk calculation and dashboard behavior.

No database migration is required.
