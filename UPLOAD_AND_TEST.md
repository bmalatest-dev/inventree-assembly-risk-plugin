# Assembly Risk v0.5.5 scoped API fix

The current repository has two mismatches:

- `plugin.py` displays v0.5.5 but still has the old two-argument
  `assembly_risk_for_stock_item` API.
- `setup.py` still reports package version 0.5.4.

This bundle makes v0.5.5 real.

## Add / replace

Add:
- `inventree_assembly_risk/scope.py`
- `tests/test_scope.py`

Replace:
- `setup.py`

For `plugin.py`, run the supplied conservative updater against the current
repository source:

    python apply_v0_5_5.py inventree_assembly_risk/plugin.py

The updater creates `plugin.py.bak` and aborts if the expected current-source
blocks are not found exactly once.

Then upload / commit the modified `plugin.py` along with the files above.

## Verify after reinstall/update

    docker exec inventree-test sh -lc     'python -m pip show inventree-assembly-risk'

Expected:
    Version: 0.5.5

Then:

    docker exec inventree-test sh -lc     'grep -A6 -n "def assembly_risk_for_stock_item"     /usr/local/lib/python3.14/site-packages/inventree_assembly_risk/plugin.py'

Expected to show:
    included_build_ids=None

And:

    docker exec inventree-test sh -lc     'ls /usr/local/lib/python3.14/site-packages/inventree_assembly_risk/scope.py'

Packing List v0.2.3 can then use Current Build, Same Parent Build, or All
Production scope without changing the Assembly Risk allocation engine.
