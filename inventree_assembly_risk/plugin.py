"""InvenTree Assembly Risk plugin.

Read-only production planning helper. The plugin simulates *Production* Build
Order component demand against usable physical stock and never creates or
modifies BuildItem allocations.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from plugin import InvenTreePlugin
from plugin.mixins import SettingsMixin, UserInterfaceMixin

from build.models import Build
from build.status_codes import BuildStatus
from stock.models import StockItem

from .engine import classify_risk, dec, fmt, location_is_excluded, spillage_for_part


class AssemblyRiskPlugin(SettingsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "AssemblyRisk"
    SLUG = "assembly-risk"
    TITLE = "Assembly Risk"
    DESCRIPTION = "Flags components with little or no physical stock buffer across Production Build Orders."
    VERSION = "0.4.0"
    AUTHOR = "Per Vices Corporation"
    WEBSITE = "https://github.com/bmalatest-dev/inventree-assembly-risk-plugin"

    SETTINGS = {
        "EXTRA_EXCLUDED_LOCATIONS": {
            "name": _("Additional excluded stock locations"),
            "description": _(
                "Comma-separated location names to exclude in addition to Rework / "
                "verification / shipping / storage exclusions."
            ),
            "default": "",
        },
        "CACHE_SECONDS": {
            "name": _("Calculation cache duration"),
            "description": _(
                "Seconds to reuse an Assembly Risk production snapshot. A short cache "
                "prevents the dashboard and Build Order panel from repeating the same "
                "expensive calculation back-to-back. Set to 0 to disable caching."
            ),
            "default": 30,
            "validator": int,
        },
    }

    # ---------- InvenTree data adapters ----------
    def _extra_excluded_locations(self):
        raw = self.get_setting("EXTRA_EXCLUDED_LOCATIONS") or ""
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    def _cache_seconds(self) -> int:
        try:
            return max(int(self.get_setting("CACHE_SECONDS") or 0), 0)
        except Exception:
            return 30

    @staticmethod
    def _production_status_value():
        """Return the DB value for BuildStatus.PRODUCTION across InvenTree releases."""
        value = getattr(BuildStatus.PRODUCTION, "value", BuildStatus.PRODUCTION)
        # Some status implementations expose ``value`` as a tuple where the first
        # item is the integer DB code.
        if isinstance(value, (tuple, list)) and value:
            value = value[0]
        try:
            return int(value)
        except Exception:
            # Official InvenTree BuildStatus.PRODUCTION code.
            return 20

    @classmethod
    def _is_production_build(cls, build) -> bool:
        try:
            return int(getattr(build, "status", -1)) == cls._production_status_value()
        except Exception:
            return False

    @staticmethod
    def _location_path_parts(location):
        if location is None:
            return []
        try:
            return [str(x.name) for x in location.get_ancestors(include_self=True)]
        except Exception:
            return [str(getattr(location, "name", ""))]

    def _usable_stock_by_part(self, relevant_part_ids):
        """Return usable physical stock aggregated by part ID.

        Only StockItems for parts which can satisfy current Production BO demand
        are inspected. Location exclusion is cached per location, avoiding an
        ancestor lookup for every StockItem in large production databases.
        """
        relevant_part_ids = {int(x) for x in relevant_part_ids if x is not None}
        if not relevant_part_ids:
            return {}

        qs = (
            StockItem.objects.filter(StockItem.IN_STOCK_FILTER, part_id__in=relevant_part_ids)
            .select_related("location")
            .only("id", "part_id", "quantity", "location_id", "location__name")
        )

        extra = self._extra_excluded_locations()
        location_excluded = {}
        quantities = defaultdict(Decimal)

        for item in qs.iterator(chunk_size=2000):
            location_id = item.location_id
            if location_id not in location_excluded:
                location_excluded[location_id] = location_is_excluded(
                    self._location_path_parts(item.location), extra
                )
            if location_excluded[location_id]:
                continue

            qty = dec(item.quantity)
            if qty > 0:
                quantities[item.part_id] += qty

        return dict(quantities)

    @staticmethod
    def _candidate_part_ids(part, allow_variants: bool):
        ids = {part.pk}
        if not allow_variants:
            return ids
        # Allow the complete variant tree when BOM line permits variants.
        try:
            root = part.get_root()
            ids.update(root.get_descendants(include_self=True).values_list("pk", flat=True))
        except Exception:
            try:
                ids.update(part.get_descendants(include_self=True).values_list("pk", flat=True))
            except Exception:
                pass
        return ids

    @staticmethod
    def _part_category(part):
        try:
            return str(part.category.name)
        except Exception:
            return ""

    @staticmethod
    def _part_footprint(part):
        try:
            params = part.parameters_map()
        except Exception:
            params = {}
        for key in ("Case/Package", "Case Package", "Package", "Footprint"):
            value = params.get(key)
            if isinstance(value, dict):
                value = value.get("data") or value.get("value") or value.get("text")
            if value:
                return str(value)
        return ""

    @staticmethod
    def _pricing_max(part):
        # Different InvenTree releases expose pricing through different helpers.
        for attr in ("pricing_max", "pricing_maximum", "max_price"):
            value = getattr(part, attr, None)
            if value not in (None, ""):
                try:
                    return dec(value.amount if hasattr(value, "amount") else value)
                except Exception:
                    pass
        try:
            price_range = part.get_price_range()
            if price_range:
                value = (
                    price_range[-1]
                    if isinstance(price_range, (tuple, list))
                    else getattr(price_range, "maximum", None)
                )
                if value is not None:
                    return dec(value.amount if hasattr(value, "amount") else value)
        except Exception:
            pass
        return Decimal("0")

    @staticmethod
    def _on_order_qty(part):
        """Display-only planning value; never contributes to physical buffer."""
        for attr in ("on_order", "quantity_on_order", "on_order_quantity"):
            value = getattr(part, attr, None)
            if value is not None and not callable(value):
                return dec(value)
        return Decimal("0")

    @staticmethod
    def _remaining_build_quantity(build):
        """Return unfinished output quantity with compatibility fallbacks."""
        value = getattr(build, "remaining", None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if value is not None:
            return max(dec(value), Decimal("0"))

        total = dec(getattr(build, "quantity", 0))
        completed = Decimal("0")
        for attr in ("completed", "completed_quantity", "quantity_completed"):
            value = getattr(build, attr, None)
            if value is not None and not callable(value):
                completed = dec(value)
                break
        return max(total - completed, Decimal("0"))

    def _production_requirements(self):
        """Build component demand for Build Orders whose status is Production.

        BOM metadata is calculated once per assembly part, then reused by all
        Production Build Orders for that assembly. Per-component variant,
        spillage, pricing and parameter lookups are also memoized for this run.
        """
        production_status = self._production_status_value()
        builds = list(
            Build.objects.filter(status=production_status)
            .select_related("part")
            .order_by("priority", "reference")
        )

        requirements = []
        bom_cache = {}
        component_meta = {}

        for build in builds:
            remaining_build_qty = self._remaining_build_quantity(build)
            if remaining_build_qty <= 0 or build.part_id is None:
                continue

            if build.part_id not in bom_cache:
                try:
                    bom_items = list(
                        build.part.get_bom_items().select_related(
                            "sub_part", "sub_part__category"
                        )
                    )
                except Exception:
                    bom_items = list(build.part.get_bom_items())

                templates = []
                for bom in bom_items:
                    part = bom.sub_part
                    if part is None:
                        continue
                    bom_qty = dec(getattr(bom, "quantity", 0))
                    if bom_qty <= 0:
                        continue

                    allow_variants = bool(getattr(bom, "allow_variants", False))
                    meta_key = (part.pk, allow_variants)
                    if meta_key not in component_meta:
                        spillage, rule = spillage_for_part(
                            self._part_footprint(part),
                            self._pricing_max(part),
                            self._part_category(part),
                        )
                        component_meta[meta_key] = {
                            "part": part,
                            "part_id": part.pk,
                            "part_name": getattr(part, "IPN", None) or part.name,
                            "part_full_name": getattr(part, "full_name", str(part)),
                            "allow_variants": allow_variants,
                            "candidate_ids": self._candidate_part_ids(part, allow_variants),
                            "spillage": spillage,
                            "spillage_rule": rule,
                            "on_order": self._on_order_qty(part),
                        }
                    templates.append((bom_qty, component_meta[meta_key]))
                bom_cache[build.part_id] = templates

            for bom_qty, meta in bom_cache[build.part_id]:
                required = bom_qty * remaining_build_qty
                if required <= 0:
                    continue
                requirements.append(
                    {
                        "build_id": build.pk,
                        "build_ref": str(build.reference),
                        "priority": int(getattr(build, "priority", 0) or 0),
                        "part_id": meta["part_id"],
                        "part_name": meta["part_name"],
                        "part_full_name": meta["part_full_name"],
                        "allow_variants": meta["allow_variants"],
                        "candidate_ids": set(meta["candidate_ids"]),
                        "required": required,
                        "spillage": meta["spillage"],
                        "spillage_rule": meta["spillage_rule"],
                        "on_order": meta["on_order"],
                    }
                )
        return requirements

    @staticmethod
    def _allocate_aggregated_stock(requirements, stock_by_part):
        """Simulate Production BO demand against quantity aggregated by part.

        This intentionally does not choose physical StockItem IDs. Assembly Risk
        only needs to know whether sufficient physical quantity exists and what
        buffer remains; StockItem-specific allocation remains InvenTree's job.
        """
        remaining_stock = defaultdict(Decimal)
        remaining_stock.update({pid: dec(qty) for pid, qty in stock_by_part.items()})

        ordered = sorted(
            requirements,
            key=lambda r: (r["priority"], -r["required"], r["build_ref"], r["part_id"]),
        )
        for req in ordered:
            need = req["required"]
            candidate_parts = [
                pid for pid in req["candidate_ids"] if remaining_stock.get(pid, Decimal("0")) > 0
            ]
            # Consume the largest available compatible source first. This keeps
            # the number of touched part pools small and mirrors the previous
            # largest-source-first simulation without scanning StockItems.
            candidate_parts.sort(
                key=lambda pid: (-remaining_stock.get(pid, Decimal("0")), pid)
            )
            for pid in candidate_parts:
                if need <= 0:
                    break
                available = remaining_stock.get(pid, Decimal("0"))
                take = min(need, available)
                remaining_stock[pid] = available - take
                need -= take
            req["unfilled"] = max(need, Decimal("0"))

        return remaining_stock

    def _calculate_uncached(self):
        """Run the optimized read-only Production stock allocation simulation."""
        requirements = self._production_requirements()
        relevant_part_ids = set()
        for req in requirements:
            relevant_part_ids.update(req["candidate_ids"])

        stock_by_part = self._usable_stock_by_part(relevant_part_ids)
        remaining_stock = self._allocate_aggregated_stock(requirements, stock_by_part)

        shortage_by_part = defaultdict(Decimal)
        builds_by_part = defaultdict(set)
        for req in requirements:
            shortage_by_part[req["part_id"]] += req.get("unfilled", Decimal("0"))
            builds_by_part[req["part_id"]].add(req["build_ref"])

        for req in requirements:
            req["physical_buffer"] = sum(
                remaining_stock.get(pid, Decimal("0")) for pid in req["candidate_ids"]
            )
            req["global_shortage"] = shortage_by_part[req["part_id"]]
            req["builds"] = sorted(builds_by_part[req["part_id"]])
            req["risk"] = classify_risk(
                physical_buffer=req["physical_buffer"],
                spillage=req["spillage"],
                shortage=req["global_shortage"],
            )
        return requirements

    def _calculate(self):
        """Return a short-lived cached Production Assembly Risk snapshot."""
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

    # ---------- report formatting ----------
    @staticmethod
    def _sort_rows(rows):
        rank = {"critical": 0, "warning": 1, "ok": 2}
        rows.sort(key=lambda r: (rank.get(r["severity"], 9), r.get("part", "")))
        return rows

    @staticmethod
    def _should_show_global_requirement(req):
        """Global dashboard only shows zero-buffer conditions needing spillage."""
        spillage = dec(req.get("spillage", 0))
        physical_buffer = dec(req.get("physical_buffer", 0))
        return spillage > 0 and physical_buffer <= 0

    def _rows_for_build(self, build_id):
        rows = []
        for req in self._calculate():
            if req["build_id"] != build_id:
                continue
            risk = req["risk"]

            message = risk.message
            other_builds = [x for x in req["builds"] if x != req["build_ref"]]
            if other_builds:
                message += " Production demand also exists on: " + ", ".join(other_builds)

            rows.append(
                {
                    "part_id": req["part_id"],
                    "part": req["part_name"],
                    "description": str(req["part_full_name"]),
                    "required_this_build": fmt(req["required"]),
                    "physical_buffer": fmt(req["physical_buffer"]),
                    "planned_spillage": fmt(req["spillage"]),
                    "on_order": fmt(req["on_order"]),
                    "affected_builds": ", ".join(req["builds"]),
                    "severity": risk.severity,
                    "risk": risk.label,
                    "message": message,
                }
            )
        return self._sort_rows(rows)

    def _rows_global(self):
        """Return one global exception row per required part in Production."""
        calculated = self._calculate()
        grouped = {}
        for req in calculated:
            key = req["part_id"]
            if key not in grouped:
                grouped[key] = {
                    "part_id": key,
                    "part": req["part_name"],
                    "description": str(req["part_full_name"]),
                    "open_demand": Decimal("0"),
                    "physical_buffer": req["physical_buffer"],
                    "planned_spillage": Decimal("0"),
                    "on_order": req["on_order"],
                    "shortage": Decimal("0"),
                    "builds": set(),
                }
            row = grouped[key]
            row["open_demand"] += req["required"]
            row["planned_spillage"] += req["spillage"]
            row["shortage"] += req.get("unfilled", Decimal("0"))
            row["builds"].add(req["build_ref"])
            row["physical_buffer"] = min(row["physical_buffer"], req["physical_buffer"])
            row["on_order"] = max(row["on_order"], req["on_order"])

        rows = []
        for row in grouped.values():
            risk = classify_risk(
                physical_buffer=row["physical_buffer"],
                spillage=row["planned_spillage"],
                shortage=row["shortage"],
            )
            if not self._should_show_global_requirement(row):
                continue
            rows.append(
                {
                    "part_id": row["part_id"],
                    "part": row["part"],
                    "description": row["description"],
                    "open_demand": fmt(row["open_demand"]),
                    "physical_buffer": fmt(row["physical_buffer"]),
                    "planned_spillage": fmt(row["planned_spillage"]),
                    "on_order": fmt(row["on_order"]),
                    "affected_builds": ", ".join(sorted(row["builds"])),
                    "severity": risk.severity,
                    "risk": risk.label,
                    "message": risk.message,
                }
            )
        return self._sort_rows(rows)

    # ---------- UI ----------
    @staticmethod
    def _normalized_target_model(value):
        text = str(value or "").strip().lower()
        for ch in ("_", "-", " ", ".", "/", "\\"):
            text = text.replace(ch, "")
        return text

    def get_ui_panels(self, request, context, **kwargs):
        """Add Assembly Risk to individual Build Order pages."""
        context = context or {}
        target_model = self._normalized_target_model(context.get("target_model"))
        target_id = context.get("target_id")

        is_build = target_model in {
            "build",
            "buildorder",
            "buildmodelsbuild",
            "buildbuild",
        } or target_model.endswith("build") or target_model.endswith("buildorder")

        if not is_build or target_id in (None, ""):
            return []
        try:
            build_id = int(target_id)
        except (TypeError, ValueError):
            return []

        notice = ""
        try:
            build = Build.objects.only("id", "status").get(pk=build_id)
            if not self._is_production_build(build):
                rows = []
                error = ""
                notice = (
                    "This Build Order is not in Production and is excluded from the "
                    "Assembly Risk calculation."
                )
            else:
                rows = self._rows_for_build(build_id)
                error = ""
        except Exception as exc:
            rows = []
            error = f"Assembly Risk calculation error: {type(exc).__name__}: {exc}"

        return [
            {
                "key": "assembly-risk-panel",
                "title": _("Assembly Risk"),
                "description": _(
                    "Physical stock buffer after satisfying all Production Build Orders"
                ),
                "icon": "ti:alert-triangle:outline",
                "source": self.plugin_static_file("assembly_risk.js:renderPanel"),
                "context": {
                    "mode": "build",
                    "rows": rows,
                    "build_id": build_id,
                    "error": error,
                    "notice": notice,
                    "plugin_version": self.VERSION,
                },
            }
        ]

    def get_ui_dashboard_items(self, request, context, **kwargs):
        """Provide a global Assembly Risk exception report for Production BOs."""
        try:
            rows = self._rows_global()
            error = ""
        except Exception as exc:
            rows = []
            error = f"Assembly Risk calculation error: {type(exc).__name__}: {exc}"

        return [
            {
                "key": "assembly-risk-global",
                "title": _("Assembly Risk - Production Build Orders"),
                "description": _(
                    "Zero-buffer physical-stock risks across Build Orders in Production."
                ),
                "icon": "ti:alert-triangle:outline",
                "source": self.plugin_static_file(
                    "assembly_risk.js:renderDashboardItem"
                ),
                "context": {
                    "mode": "global",
                    "rows": rows,
                    "error": error,
                    "plugin_version": self.VERSION,
                },
                "options": {"width": 6, "height": 4},
            }
        ]
