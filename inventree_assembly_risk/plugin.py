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

from build.models import Build, BuildLine
from build.status_codes import BuildStatus
from stock.models import StockItem

from .engine import classify_risk, dec, fmt, location_is_excluded, outstanding_requirement, spillage_for_part


class AssemblyRiskPlugin(SettingsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "AssemblyRisk"
    SLUG = "assembly-risk"
    TITLE = "Assembly Risk"
    DESCRIPTION = "Flags components with little or no physical stock buffer across Production Build Orders."
    VERSION = "0.5.5"
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

    def _stock_inventory_snapshot(self, relevant_part_ids):
        """Return usable stock plus a diagnostic record for every physical StockItem.

        The diagnostic side of this method is intentionally verbose. It records
        the exact location path, whether the location was excluded, physical
        quantity, active allocation total and resulting free quantity. This is
        used by the temporary Packing List debug column to reconcile Assembly
        Risk against InvenTree's visible stock totals.
        """
        relevant_part_ids = {int(x) for x in relevant_part_ids if x is not None}
        if not relevant_part_ids:
            return {}, {}

        qs = (
            StockItem.objects.filter(
                StockItem.IN_STOCK_FILTER, part_id__in=relevant_part_ids
            )
            .select_related("location")
            .only("id", "part_id", "quantity", "location_id", "location__name")
        )
        items = list(qs.iterator(chunk_size=2000))
        if not items:
            return {}, {}

        try:
            allocated_by_item = StockItem.bulk_allocation_count(items)
        except Exception:
            allocated_by_item = {}
            for item in items:
                try:
                    allocated_by_item[item.pk] = dec(item.allocation_count())
                except Exception:
                    try:
                        allocated_by_item[item.pk] = max(
                            dec(item.quantity) - dec(item.unallocated_quantity()),
                            Decimal("0"),
                        )
                    except Exception:
                        allocated_by_item[item.pk] = Decimal("0")

        extra = self._extra_excluded_locations()
        usable = {}
        diagnostic = {}

        for item in items:
            location_parts = self._location_path_parts(item.location)
            excluded = location_is_excluded(location_parts, extra)

            quantity = max(dec(item.quantity), Decimal("0"))
            allocated = max(dec(allocated_by_item.get(item.pk, 0)), Decimal("0"))
            raw_free = max(quantity - allocated, Decimal("0"))
            usable_free = Decimal("0") if excluded else raw_free

            diagnostic[item.pk] = {
                "stock_item_id": item.pk,
                "part_id": item.part_id,
                "location_path": " > ".join(location_parts),
                "excluded_by_location": excluded,
                "quantity": quantity,
                "allocated": allocated,
                "raw_free": raw_free,
                "usable_free": usable_free,
            }

            if excluded:
                continue

            usable[item.pk] = {
                "stock_item_id": item.pk,
                "part_id": item.part_id,
                "quantity": quantity,
                "allocated": allocated,
                "free": raw_free,
                "final_free": raw_free,
            }

        return usable, diagnostic

    def _usable_stock_items(self, relevant_part_ids):
        """Compatibility wrapper returning only usable StockItems."""
        usable, _ = self._stock_inventory_snapshot(relevant_part_ids)
        return usable

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
    def _money_amount(value):
        """Convert Decimal / Money-like values to Decimal."""
        if value in (None, ""):
            return None

        try:
            amount = value.amount if hasattr(value, "amount") else value
            return dec(amount)
        except Exception:
            return None

    def _pricing_max(self, part):
        """Return the best available unit price plus its source.

        Prefer real StockItem purchase prices because this is the same price data
        exposed by the Packing List exporter. The maximum non-zero purchase price
        for in-stock StockItems of the exact required part is used conservatively.

        Part-level price helpers are retained as fallbacks.
        """
        prices = []

        try:
            # Do not use .only("purchase_price") here. purchase_price can differ
            # between InvenTree releases / implementations, so load the StockItem
            # normally and access the public attribute.
            qs = StockItem.objects.filter(
                StockItem.IN_STOCK_FILTER,
                part_id=part.pk,
            )

            for item in qs.iterator(chunk_size=1000):
                value = self._money_amount(
                    getattr(item, "purchase_price", None)
                )

                if value is not None and value > 0:
                    prices.append(value)
        except Exception:
            prices = []

        if prices:
            return max(prices), "stock_item_purchase_price_max"

        # Different InvenTree releases expose Part pricing through different helpers.
        for attr in ("pricing_max", "pricing_maximum", "max_price"):
            value = self._money_amount(getattr(part, attr, None))

            if value is not None and value > 0:
                return value, f"part_{attr}"

        try:
            price_range = part.get_price_range()

            if price_range:
                candidates = []

                if isinstance(price_range, (tuple, list)):
                    candidates.extend(price_range)
                else:
                    value = getattr(price_range, "maximum", None)
                    if value is not None:
                        candidates.append(value)

                converted = [
                    self._money_amount(value)
                    for value in candidates
                ]
                converted = [
                    value
                    for value in converted
                    if value is not None and value > 0
                ]

                if converted:
                    return max(converted), "part_get_price_range"
        except Exception:
            pass

        return Decimal("0"), "missing_price"

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
        """Build allocation-aware demand for all Production Build Orders.

        Demand is sourced from BuildLine rather than reconstructed from the BOM:

            BOM remaining = BuildLine.quantity - BuildLine.consumed
            outstanding   = BOM remaining + planned spillage - existing allocations

        BuildItem allocations are retained with their exact StockItem IDs. This
        both credits the BO which owns the allocation and lets downstream users
        (notably Packing List) ask for risk for a specific BO / StockItem pair.
        """
        production_status = self._production_status_value()
        lines = (
            BuildLine.objects.filter(build__status=production_status)
            .select_related(
                "build",
                "bom_item",
                "bom_item__sub_part",
                "bom_item__sub_part__category",
            )
            .prefetch_related("allocations__stock_item")
            .order_by("build__priority", "build__reference", "pk")
        )

        requirements = []
        component_meta = {}
        for line in lines:
            build = line.build
            bom = line.bom_item
            part = getattr(bom, "sub_part", None)
            if part is None:
                continue

            bom_remaining = max(
                dec(getattr(line, "quantity", 0)) - dec(getattr(line, "consumed", 0)),
                Decimal("0"),
            )
            if bom_remaining <= 0:
                continue

            allow_variants = bool(getattr(bom, "allow_variants", False))
            meta_key = (part.pk, allow_variants)
            if meta_key not in component_meta:
                pricing_max, pricing_source = self._pricing_max(part)
                spillage, rule = spillage_for_part(
                    self._part_footprint(part),
                    pricing_max,
                    self._part_category(part),
                )
                component_meta[meta_key] = {
                    "part_id": part.pk,
                    "part_name": getattr(part, "IPN", None) or part.name,
                    "part_full_name": getattr(part, "full_name", str(part)),
                    "allow_variants": allow_variants,
                    "candidate_ids": self._candidate_part_ids(part, allow_variants),
                    "spillage": spillage,
                    "spillage_rule": rule,
                    "pricing_max": pricing_max,
                    "pricing_source": pricing_source,
                    "on_order": self._on_order_qty(part),
                }
            meta = component_meta[meta_key]

            allocation_details = []
            allocated = Decimal("0")
            for allocation in line.allocations.all():
                qty = max(dec(getattr(allocation, "quantity", 0)), Decimal("0"))
                if qty <= 0:
                    continue
                allocated += qty
                stock_item = getattr(allocation, "stock_item", None)
                allocation_details.append(
                    {
                        "allocation_id": allocation.pk,
                        "stock_item_id": getattr(allocation, "stock_item_id", None),
                        "stock_part_id": getattr(stock_item, "part_id", None),
                        "quantity": qty,
                    }
                )

            unallocated_bom, outstanding = outstanding_requirement(
                bom_remaining,
                allocated,
                meta["spillage"],
            )

            applied_spillage = (
                meta["spillage"]
                if unallocated_bom > 0
                else Decimal("0")
            )

            gross_requirement = unallocated_bom + applied_spillage

            requirements.append(
                {
                    "build_id": build.pk,
                    "build_ref": str(build.reference),
                    "priority": int(getattr(build, "priority", 0) or 0),
                    "build_line_id": line.pk,
                    "part_id": meta["part_id"],
                    "part_name": meta["part_name"],
                    "part_full_name": meta["part_full_name"],
                    "allow_variants": meta["allow_variants"],
                    "candidate_ids": set(meta["candidate_ids"]),
                    "bom_remaining": bom_remaining,
                    "allocated": allocated,
                    "unallocated_bom": unallocated_bom,
                    "required": outstanding,
                    "gross_requirement": gross_requirement,
                    "spillage": applied_spillage,
                    "standard_spillage": meta["spillage"],
                    "spillage_rule": meta["spillage_rule"],
                    "pricing_max": meta["pricing_max"],
                    "pricing_source": meta["pricing_source"],
                    "on_order": meta["on_order"],
                    "existing_allocations": allocation_details,
                    "virtual_allocations": [],
                }
            )
        return requirements

    @staticmethod
    def _allocate_free_stock_items(requirements, stock_items):
        """Virtually satisfy outstanding Production demand from free StockItems.

        Existing allocations have already been removed from each StockItem's free
        quantity and from the owning BO's outstanding requirement. The simulation
        is read-only and records which free StockItems would satisfy each remaining
        requirement so the snapshot can later answer BO / StockItem risk queries.
        """
        remaining = {
            stock_id: dec(data.get("free", 0)) for stock_id, data in stock_items.items()
        }
        ordered = sorted(
            requirements,
            key=lambda r: (r["priority"], -r["required"], r["build_ref"], r["part_id"]),
        )
        for req in ordered:
            need = max(dec(req.get("required", 0)), Decimal("0"))
            candidates = [
                stock_id
                for stock_id, data in stock_items.items()
                if data.get("part_id") in req["candidate_ids"]
                and remaining.get(stock_id, Decimal("0")) > 0
            ]
            candidates.sort(
                key=lambda stock_id: (
                    -remaining.get(stock_id, Decimal("0")),
                    stock_id,
                )
            )
            virtual = []
            for stock_id in candidates:
                if need <= 0:
                    break
                available = remaining.get(stock_id, Decimal("0"))
                take = min(need, available)
                if take <= 0:
                    continue
                remaining[stock_id] = available - take
                need -= take
                virtual.append({"stock_item_id": stock_id, "quantity": take})
            req["virtual_allocations"] = virtual
            req["unfilled"] = max(need, Decimal("0"))

        for stock_id, data in stock_items.items():
            data["final_free"] = remaining.get(stock_id, Decimal("0"))
        return remaining

    def _calculate_uncached(self):
        """Run the allocation-aware Production Demand Snapshot."""
        requirements = self._production_requirements()
        relevant_part_ids = set()
        for req in requirements:
            relevant_part_ids.update(req["candidate_ids"])

        stock_items, stock_inventory_debug = self._stock_inventory_snapshot(
            relevant_part_ids
        )
        self._allocate_free_stock_items(requirements, stock_items)

        shortage_by_part = defaultdict(Decimal)
        builds_by_part = defaultdict(set)
        for req in requirements:
            shortage_by_part[req["part_id"]] += req.get("unfilled", Decimal("0"))
            builds_by_part[req["part_id"]].add(req["build_ref"])

        for req in requirements:
            compatible_items = [
                data
                for data in stock_items.values()
                if data.get("part_id") in req["candidate_ids"]
            ]
            req["physical_buffer"] = sum(
                dec(data.get("final_free", 0)) for data in compatible_items
            )
            req["global_shortage"] = shortage_by_part[req["part_id"]]
            req["builds"] = sorted(builds_by_part[req["part_id"]])
            req["stock_items"] = {
                data["stock_item_id"]: {
                    "part_id": data["part_id"],
                    "quantity": data["quantity"],
                    "allocated": data["allocated"],
                    "free": data["free"],
                    "final_free": data["final_free"],
                }
                for data in compatible_items
            }
            req["stock_inventory_debug"] = [
                dict(data)
                for data in stock_inventory_debug.values()
                if data.get("part_id") in req["candidate_ids"]
            ]
            req["risk"] = classify_risk(
                physical_buffer=req["physical_buffer"],
                spillage=req["spillage"],
                shortage=req["global_shortage"],
            )
        return requirements

    def production_demand_snapshot(self):
        """Public read-only snapshot for reuse by other plugin features.

        This is intentionally a stable wrapper around the cached calculation so a
        Packing List integration can consume the exact same Production-demand logic.
        """
        return self._calculate()

    def assembly_risk_for_stock_item(self, build_id, stock_item_id):
        """Return Assembly Risk context for a specific BO / StockItem pair.

        Version 0.5.1 also returns a temporary ``debug`` object containing:
        - every relevant physical StockItem and its location-exclusion decision;
        - active allocation totals and free quantities;
        - each Production BO BuildLine demand / overage / allocation calculation;
        - virtual allocation and unfilled quantities.

        This diagnostic payload is read-only and is intended to make discrepancies
        such as location filtering or double-counted demand easy to reconcile.
        """
        try:
            build_id = int(build_id)
            stock_item_id = int(stock_item_id)
        except (TypeError, ValueError):
            return None

        calculated = self._calculate()

        for req in calculated:
            if req["build_id"] != build_id:
                continue

            existing_ids = {
                x.get("stock_item_id") for x in req.get("existing_allocations", [])
            }
            virtual_ids = {
                x.get("stock_item_id") for x in req.get("virtual_allocations", [])
            }
            debug_inventory_ids = {
                x.get("stock_item_id") for x in req.get("stock_inventory_debug", [])
            }

            if (
                stock_item_id not in req.get("stock_items", {})
                and stock_item_id not in existing_ids
                and stock_item_id not in virtual_ids
                and stock_item_id not in debug_inventory_ids
            ):
                continue

            item = req.get("stock_items", {}).get(stock_item_id, {})
            risk = req["risk"]

            # Collect all Production demand which competes for the same required
            # part. This provides a direct reconciliation of the global shortage.
            demand_debug = []
            for other in calculated:
                if other["part_id"] != req["part_id"]:
                    continue
                demand_debug.append(
                    {
                        "build_id": other["build_id"],
                        "build_ref": other["build_ref"],
                        "build_line_id": other["build_line_id"],
                        "bom_remaining": other["bom_remaining"],
                        "existing_allocated_to_line": other["allocated"],
                        "unallocated_bom_demand": other.get(
                            "unallocated_bom", Decimal("0")
                        ),
                        "standard_spillage": other.get(
                            "standard_spillage", other["spillage"]
                        ),
                        "planned_spillage_applied": other["spillage"],
                        "spillage_rule": other["spillage_rule"],
                        "pricing_max": other.get("pricing_max", Decimal("0")),
                        "pricing_source": other.get("pricing_source", ""),
                        "gross_requirement": other["gross_requirement"],
                        "outstanding_before_virtual_allocation": other["required"],
                        "existing_allocations": other.get("existing_allocations", []),
                        "virtual_allocations": other.get("virtual_allocations", []),
                        "unfilled": other.get("unfilled", Decimal("0")),
                    }
                )

            return {
                "build_id": req["build_id"],
                "build_ref": req["build_ref"],
                "part_id": req["part_id"],
                "part": req["part_name"],
                "bom_remaining": req["bom_remaining"],
                "allocated_to_build_line": req["allocated"],
                "outstanding": req["required"],
                "planned_spillage": req["spillage"],
                "standard_spillage": req.get(
                    "standard_spillage", req["spillage"]
                ),
                "pricing_max": req.get("pricing_max", Decimal("0")),
                "pricing_source": req.get("pricing_source", ""),
                "physical_buffer": req["physical_buffer"],
                "global_shortage": req["global_shortage"],
                "stock_item_id": stock_item_id,
                "stock_item_quantity": item.get("quantity"),
                "stock_item_allocated_total": item.get("allocated"),
                "stock_item_free_before_simulation": item.get("free"),
                "stock_item_final_free": item.get("final_free"),
                "severity": risk.severity,
                "risk": risk.label,
                "message": risk.message,
                "debug": {
                    "queried_build_id": build_id,
                    "queried_stock_item_id": stock_item_id,
                    "stock_inventory": req.get("stock_inventory_debug", []),
                    "production_demand": demand_debug,
                    "physical_buffer_after_all_production_demand": req["physical_buffer"],
                    "global_shortage": req["global_shortage"],
                },
            }

        return None

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
                    "required_this_build": fmt(req["bom_remaining"]),
                    "allocated_this_build": fmt(req["allocated"]),
                    "outstanding_this_build": fmt(req["required"]),
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
