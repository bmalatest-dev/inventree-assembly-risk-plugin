#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 match, found {count}. "
            "Source file is not the expected current Assembly Risk plugin.py."
        )
    return text.replace(old, new, 1)


if len(sys.argv) != 2:
    raise SystemExit("Usage: python apply_v0_5_5.py path/to/inventree_assembly_risk/plugin.py")

path = Path(sys.argv[1])
text = path.read_text()

old = "from .engine import classify_risk, dec, fmt, location_is_excluded, outstanding_requirement, spillage_for_part\n"
new = old + "from .scope import include_queried_build, normalize_build_ids, scope_cache_suffix\n"
text = replace_once(text, old, new, "scope import")

old = """    def _production_requirements(self):
        \"""Build allocation-aware demand for all Production Build Orders.
"""
new = """    def _production_requirements(self, included_build_ids=None):
        \"""Build allocation-aware demand for selected Production Build Orders.

        ``included_build_ids=None`` retains the legacy all-Production behavior.
        An explicit iterable restricts future demand to those Build Orders.

        Existing StockItem allocations are still removed globally from physical
        free stock by ``_stock_inventory_snapshot``. This is intentional: stock
        reserved to an unrelated BO is not available to the selected scope.
"""
text = replace_once(text, old, new, "production requirements signature")

old = """        production_status = self._production_status_value()
        lines = (
            BuildLine.objects.filter(build__status=production_status)
"""
new = """        production_status = self._production_status_value()
        included_build_ids = normalize_build_ids(included_build_ids)

        line_filter = {"build__status": production_status}

        if included_build_ids is not None:
            line_filter["build_id__in"] = included_build_ids

        lines = (
            BuildLine.objects.filter(**line_filter)
"""
text = replace_once(text, old, new, "production requirements filter")

old = """    def _calculate_uncached(self):
        \"""Run the allocation-aware Production Demand Snapshot.\"""
        requirements = self._production_requirements()
"""
new = """    def _calculate_uncached(self, included_build_ids=None):
        \"""Run the allocation-aware Production Demand Snapshot for one scope.\"""
        requirements = self._production_requirements(included_build_ids)
"""
text = replace_once(text, old, new, "uncached calculation")

old = """    def production_demand_snapshot(self):
        \"""Public read-only snapshot for reuse by other plugin features.

        This is intentionally a stable wrapper around the cached calculation so a
        Packing List integration can consume the exact same Production-demand logic.
        \"""
        return self._calculate()
"""
new = """    def production_demand_snapshot(self, included_build_ids=None):
        \"""Public read-only snapshot for reuse by other plugin features.

        ``included_build_ids=None`` means all Production BOs. An explicit iterable
        calculates only the selected Production demand scope.
        \"""
        return self._calculate(included_build_ids=included_build_ids)
"""
text = replace_once(text, old, new, "public snapshot")

old = """    def assembly_risk_for_stock_item(self, build_id, stock_item_id):
        \"""Return Assembly Risk context for a specific BO / StockItem pair.
"""
new = """    def assembly_risk_for_stock_item(
        self,
        build_id,
        stock_item_id,
        included_build_ids=None,
    ):
        \"""Return Assembly Risk context for a specific BO / StockItem pair.

        Scope behavior:
        - ``included_build_ids=None``: all Production BOs (legacy behavior)
        - explicit iterable: only those Production BOs contribute future demand

        For an explicit scope, the queried ``build_id`` is always included.
"""
text = replace_once(text, old, new, "stock item API signature")

marker = "    def assembly_risk_for_stock_item(\n"
before, after = text.split(marker, 1)
old = "        calculated = self._calculate()\n"
new = """        included_build_ids = include_queried_build(
            build_id,
            included_build_ids,
        )
        calculated = self._calculate(
            included_build_ids=included_build_ids,
        )
"""
after = replace_once(after, old, new, "scoped stock-item calculation")
text = before + marker + after

old = """                "severity": risk.severity,
                "risk": risk.label,
                "message": risk.message,
                "debug": {
"""
new = """                "severity": risk.severity,
                "risk": risk.label,
                "message": risk.message,
                "scope": {
                    "mode": (
                        "all_production"
                        if included_build_ids is None
                        else "selected_builds"
                    ),
                    "included_build_ids": (
                        None
                        if included_build_ids is None
                        else list(included_build_ids)
                    ),
                    "included_build_refs": sorted(
                        {other["build_ref"] for other in calculated}
                    ),
                },
                "debug": {
"""
text = replace_once(text, old, new, "scope metadata")

old = """    def _calculate(self):
        \"""Return a short-lived cached Production Assembly Risk snapshot.\"""
        seconds = self._cache_seconds()
        if seconds <= 0:
            return self._calculate_uncached()
        cache_key = f"inventree-assembly-risk:{self.VERSION}:production-snapshot"
        result = cache.get(cache_key)
        if result is None:
            result = self._calculate_uncached()
            try:
                cache.set(cache_key, result, seconds)
            except Exception:
                # Cache failure must never prevent the report from loading.
                pass
        return result
"""
new = """    def _calculate(self, included_build_ids=None):
        \"""Return a short-lived cached Production Assembly Risk snapshot.

        The cache key includes the normalized demand scope so calculations for
        different packing-list groups cannot reuse one another.
        \"""
        included_build_ids = normalize_build_ids(included_build_ids)
        seconds = self._cache_seconds()

        if seconds <= 0:
            return self._calculate_uncached(included_build_ids)

        cache_key = (
            f"inventree-assembly-risk:{self.VERSION}:production-snapshot:"
            f"{scope_cache_suffix(included_build_ids)}"
        )

        result = cache.get(cache_key)

        if result is None:
            result = self._calculate_uncached(included_build_ids)
            try:
                cache.set(cache_key, result, seconds)
            except Exception:
                # Cache failure must never prevent the report from loading.
                pass

        return result
"""
text = replace_once(text, old, new, "scope-aware cache")

backup = path.with_suffix(path.suffix + ".bak")
shutil.copy2(path, backup)
path.write_text(text)

print(f"Updated: {path}")
print(f"Backup:  {backup}")
print("Assembly Risk API is now scoped-build capable.")
