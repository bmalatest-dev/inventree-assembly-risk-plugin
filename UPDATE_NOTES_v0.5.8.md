# Assembly Risk v0.5.8

Fixes registration of the asynchronous Build Order Assembly Risk endpoint.

v0.5.7 correctly moved the expensive risk calculation out of `get_ui_panels()`,
but used `get_urls()` for the new route. v0.5.8 uses `setup_urls()` so InvenTree
registers `/plugin/assembly-risk/build/<id>/` correctly.

No database migration is required.
