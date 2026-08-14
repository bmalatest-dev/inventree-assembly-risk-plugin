"""InvenTree Assembly Risk plugin.

Read-only production planning helper. The plugin simulates active Build Order
component demand against usable physical stock and never creates or modifies
BuildItem allocations.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from plugin import InvenTreePlugin
from plugin.mixins import SettingsMixin, UserInterfaceMixin

from build.models import Build
from build.status_codes import BuildStatusGroups
from stock.models import StockItem

from .engine import classify_risk, dec, fmt, location_is_excluded, spillage_for_part


class AssemblyRiskPlugin(SettingsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "AssemblyRisk"
    SLUG = "assembly-risk"
    TITLE = "Assembly Risk"
    DESCRIPTION = "Flags components with little or no physical stock buffer across open Build Orders."
    VERSION = "0.3.0"
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
    }

    # ---------- InvenTree data adapters ----------
    def _extra_excluded_locations(self):
        raw = self.get_setting("EXTRA_EXCLUDED_LOCATIONS") or ""
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    @staticmethod
    def _location_path_parts(location):
        if location is None:
            return []
        try:
            return [str(x.name) for x in location.get_ancestors(include_self=True)]
        except Exception:
            return [str(getattr(location, "name", ""))]

    def _usable_stock_items(self):
        """Return usable physical stock only; On Order is deliberately excluded."""
        qs = StockItem.objects.filter(StockItem.IN_STOCK_FILTER).select_related("part", "location")
        extra = self._extra_excluded_locations()
        items = []
        for item in qs.iterator():
            if location_is_excluded(self._location_path_parts(item.location), extra):
                continue
            qty = dec(item.quantity)
            if qty <= 0:
                continue
            items.append({"id": item.pk, "part_id": item.part_id, "qty": qty})
        return items

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

        # Conservative compatibility fallback for releases where ``remaining`` is
        # not exposed directly as a property.
        total = dec(getattr(build, "quantity", 0))
        completed = Decimal("0")
        for attr in ("completed", "completed_quantity", "quantity_completed"):
            value = getattr(build, attr, None)
            if value is not None and not callable(value):
                completed = dec(value)
                break
        return max(total - completed, Decimal("0"))

    def _open_requirements(self):
        """Build component demand for active Build Orders."""
        builds = list(
            Build.objects.filter(status__in=BuildStatusGroups.ACTIVE_CODES)
            .select_related("part")
            .order_by("priority", "reference")
        )
        requirements = []

        for build in builds:
            remaining_build_qty = self._remaining_build_quantity(build)
            if remaining_build_qty <= 0 or build.part_id is None:
                continue

            try:
                bom_items = build.part.get_bom_items().select_related("sub_part", "sub_part__category")
            except Exception:
                bom_items = build.part.get_bom_items()

            for bom in bom_items:
                part = bom.sub_part
                if part is None:
                    continue
                bom_qty = dec(getattr(bom, "quantity", 0))
                required = bom_qty * remaining_build_qty
                if required <= 0:
                    continue

                allow_variants = bool(getattr(bom, "allow_variants", False))
                spillage, rule = spillage_for_part(
                    self._part_footprint(part),
                    self._pricing_max(part),
                    self._part_category(part),
                )
                requirements.append(
                    {
                        "build_id": build.pk,
                        "build_ref": str(build.reference),
                        "priority": int(getattr(build, "priority", 0) or 0),
                        "part": part,
                        "part_id": part.pk,
                        "part_name": getattr(part, "IPN", None) or part.name,
                        "part_full_name": getattr(part, "full_name", str(part)),
                        "allow_variants": allow_variants,
                        "candidate_ids": self._candidate_part_ids(part, allow_variants),
                        "required": required,
                        "spillage": spillage,
                        "spillage_rule": rule,
                        "on_order": self._on_order_qty(part),
                    }
                )
        return requirements

    def _calculate(self):
        """Run the read-only global stock allocation simulation."""
        requirements = self._open_requirements()
        stock_items = self._usable_stock_items()

        remaining_stock = {item["id"]: item["qty"] for item in stock_items}
        stock_part = {item["id"]: item["part_id"] for item in stock_items}

        # Existing script semantics: BO priority first, then larger requirement.
        ordered = sorted(
            requirements,
            key=lambda r: (r["priority"], -r["required"], r["build_ref"], r["part_id"]),
        )
        for req in ordered:
            need = req["required"]
            candidates = [
                sid
                for sid, pid in stock_part.items()
                if pid in req["candidate_ids"] and remaining_stock[sid] > 0
            ]
            candidates.sort(key=lambda sid: (-remaining_stock[sid], sid))
            for sid in candidates:
                if need <= 0:
                    break
                take = min(need, remaining_stock[sid])
                remaining_stock[sid] -= take
                need -= take
            req["unfilled"] = max(need, Decimal("0"))

        # Group shortage / affected BO data by required part identity.
        shortage_by_part = defaultdict(Decimal)
        builds_by_part = defaultdict(set)
        for req in requirements:
            shortage_by_part[req["part_id"]] += req.get("unfilled", Decimal("0"))
            builds_by_part[req["part_id"]].add(req["build_ref"])

        for req in requirements:
            req["physical_buffer"] = sum(
                qty
                for sid, qty in remaining_stock.items()
                if stock_part[sid] in req["candidate_ids"]
            )
            req["global_shortage"] = shortage_by_part[req["part_id"]]
            req["builds"] = sorted(builds_by_part[req["part_id"]])
            req["risk"] = classify_risk(
                physical_buffer=req["physical_buffer"],
                spillage=req["spillage"],
                shortage=req["global_shortage"],
            )
        return requirements

    # ---------- report formatting ----------
    @staticmethod
    def _sort_rows(rows):
        rank = {"critical": 0, "warning": 1, "ok": 2}
        rows.sort(key=lambda r: (rank.get(r["severity"], 9), r.get("part", "")))
        return rows

    @staticmethod
    def _should_show_global_requirement(req):
        """Return True for actionable zero-buffer conditions on the global widget.

        The global dashboard is intentionally an exception report. It only shows
        a part when the normal spillage model expects a positive contingency
        quantity but there is no physical buffer left after all active Build Order
        demand is satisfied. This includes both a true shortage (CRITICAL -
        UNFILLED) and an exactly-covered BOM (Exact BOM quantity).

        Positive-buffer states such as Critical Low Buffer, Low Buffer, Limited
        Buffer and Normal Spillage are deliberately omitted from the dashboard.
        They remain visible on the individual Build Order panel.
        """
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
                message += " Open demand also exists on: " + ", ".join(other_builds)

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
        """Return one global risk row per required part."""
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
            visibility_probe = {
                "spillage": row["planned_spillage"],
                "physical_buffer": row["physical_buffer"],
                "shortage": row["shortage"],
            }
            if not self._should_show_global_requirement(visibility_probe):
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
        # UI model names have changed over InvenTree releases; collapse separators
        # and package/model prefixes and match defensively.
        text = str(value or "").strip().lower()
        for ch in ("_", "-", " ", ".", "/", "\\"):
            text = text.replace(ch, "")
        return text

    def get_ui_panels(self, request, context, **kwargs):
        """Add Assembly Risk to individual Build Order pages."""
        context = context or {}
        target_model = self._normalized_target_model(context.get("target_model"))
        target_id = context.get("target_id")

        # Accept the names observed across modern / older InvenTree frontends.
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

        # Do not reject the feature if an incidental DB lookup fails during panel
        # discovery. The calculation itself will determine what rows are available.
        try:
            rows = self._rows_for_build(build_id)
            error = ""
        except Exception as exc:  # Fail visible instead of silently hiding the panel.
            rows = []
            error = f"Assembly Risk calculation error: {type(exc).__name__}: {exc}"

        return [
            {
                "key": "assembly-risk-panel",
                "title": _("Assembly Risk"),
                "description": _("Physical stock buffer after satisfying all active Build Orders"),
                "icon": "ti:alert-triangle:outline",
                "source": self.plugin_static_file("assembly_risk.js:renderPanel"),
                "context": {
                    "mode": "build",
                    "rows": rows,
                    "build_id": build_id,
                    "error": error,
                    "plugin_version": self.VERSION,
                },
            }
        ]

    def get_ui_dashboard_items(self, request, context, **kwargs):
        """Provide a global Assembly Risk report across all active Build Orders."""
        try:
            rows = self._rows_global()
            error = ""
        except Exception as exc:
            rows = []
            error = f"Assembly Risk calculation error: {type(exc).__name__}: {exc}"

        return [
            {
                "key": "assembly-risk-global",
                "title": _("Assembly Risk - All Open Build Orders"),
                "description": _(
                    "Global physical-stock risk after satisfying all active Build Orders."
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
