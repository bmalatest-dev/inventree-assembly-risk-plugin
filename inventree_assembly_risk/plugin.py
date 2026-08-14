"""InvenTree Assembly Risk plugin.

This is intentionally read-only: it simulates demand against physical stock and
never creates or changes BuildItem allocations.
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
    VERSION = "0.1.0"
    AUTHOR = "Per Vices Corporation"
    WEBSITE = "https://github.com/HMHepburn"

    SETTINGS = {
        "EXTRA_EXCLUDED_LOCATIONS": {
            "name": _("Additional excluded stock locations"),
            "description": _("Comma-separated location names to exclude in addition to Rework / verification / shipping / storage exclusions."),
            "default": "",
        },
        "SHOW_NORMAL": {
            "name": _("Show normal-risk rows"),
            "description": _("Show components with more than 20 units of physical buffer. Disable to focus the panel on risk."),
            "default": False,
            "validator": bool,
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
        # Variants are represented by the Part MPTT tree. Prefer the complete tree
        # so either a template or a sibling variant can satisfy an allow-variants BOM.
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
                value = price_range[-1] if isinstance(price_range, (tuple, list)) else getattr(price_range, "maximum", None)
                if value is not None:
                    return dec(value.amount if hasattr(value, "amount") else value)
        except Exception:
            pass
        return Decimal("0")

    @staticmethod
    def _on_order_qty(part):
        # Display-only. It never contributes to physical buffer.
        for attr in ("on_order", "quantity_on_order", "on_order_quantity"):
            value = getattr(part, attr, None)
            if value is not None and not callable(value):
                return dec(value)
        return Decimal("0")

    def _open_requirements(self):
        """Build all BOM requirements for active Build Orders.

        Demand is based on remaining build outputs rather than original BO quantity,
        so completed output quantity no longer contributes to future component demand.
        """
        builds = list(
            Build.objects.filter(status__in=BuildStatusGroups.ACTIVE_CODES)
            .select_related("part")
            .order_by("priority", "reference")
        )
        requirements = []
        for build in builds:
            remaining_build_qty = dec(getattr(build, "remaining", 0))
            if remaining_build_qty <= 0:
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
                    self._part_footprint(part), self._pricing_max(part), self._part_category(part)
                )
                requirements.append({
                    "build_id": build.pk,
                    "build_ref": build.reference,
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
                })
        return requirements

    def _calculate(self):
        requirements = self._open_requirements()
        stock_items = self._usable_stock_items()

        # Shared physical stock pool. This is only an in-memory simulation.
        remaining_stock = {item["id"]: item["qty"] for item in stock_items}
        stock_part = {item["id"]: item["part_id"] for item in stock_items}

        # The script's priority semantics: explicit BO priority, then larger demand.
        ordered = sorted(requirements, key=lambda r: (r["priority"], -r["required"], r["build_ref"], r["part_id"]))
        for req in ordered:
            need = req["required"]
            candidates = [sid for sid, pid in stock_part.items() if pid in req["candidate_ids"] and remaining_stock[sid] > 0]
            # Real stock only, larger StockItems first. Partial use is simulation-only.
            candidates.sort(key=lambda sid: (-remaining_stock[sid], sid))
            for sid in candidates:
                if need <= 0:
                    break
                take = min(need, remaining_stock[sid])
                remaining_stock[sid] -= take
                need -= take
            req["unfilled"] = max(need, Decimal("0"))

        shortage_by_part = defaultdict(Decimal)
        builds_by_part = defaultdict(set)
        for req in requirements:
            shortage_by_part[req["part_id"]] += req.get("unfilled", Decimal("0"))
            builds_by_part[req["part_id"]].add(req["build_ref"])

        # Remaining buffer available to each required part / allowed-variant group.
        for req in requirements:
            req["physical_buffer"] = sum(
                qty for sid, qty in remaining_stock.items() if stock_part[sid] in req["candidate_ids"]
            )
            req["global_shortage"] = shortage_by_part[req["part_id"]]
            req["builds"] = sorted(builds_by_part[req["part_id"]])
            req["risk"] = classify_risk(
                physical_buffer=req["physical_buffer"],
                spillage=req["spillage"],
                shortage=req["global_shortage"],
            )
        return requirements

    def _rows_for_build(self, build_id):
        rows = []
        for req in self._calculate():
            if req["build_id"] != build_id:
                continue
            risk = req["risk"]
            if risk.severity == "ok" and not self.get_setting("SHOW_NORMAL"):
                continue
            message = risk.message
            if len(req["builds"]) > 1:
                message += " Open demand also exists on: " + ", ".join(x for x in req["builds"] if x != req["build_ref"])
            rows.append({
                "part_id": req["part_id"],
                "part": req["part_name"],
                "description": str(req["part_full_name"]),
                "required_this_build": fmt(req["required"]),
                "physical_buffer": fmt(req["physical_buffer"]),
                "planned_spillage": fmt(req["spillage"]),
                "on_order": fmt(req["on_order"]),
                "severity": risk.severity,
                "risk": risk.label,
                "message": message,
            })
        rank = {"critical": 0, "warning": 1, "ok": 2}
        rows.sort(key=lambda r: (rank.get(r["severity"], 9), r["part"]))
        return rows

    # ---------- UI ----------
    def get_ui_panels(self, request, context, **kwargs):
        context = context or {}
        target_model = str(context.get("target_model") or "").lower()
        target_id = context.get("target_id")

        # Current InvenTree UI uses target_model='build'. Accept aliases so the
        # plugin remains tolerant of older / downstream UI naming.
        if target_model not in {"build", "buildorder", "build_order"} or target_id is None:
            return []
        try:
            build_id = int(target_id)
            Build.objects.only("pk").get(pk=build_id)
        except Exception:
            return []

        rows = self._rows_for_build(build_id)
        return [{
            "key": "assembly-risk-panel",
            "title": _("Assembly Risk"),
            "description": _("Physical stock buffer after satisfying all active Build Orders"),
            "icon": "ti:alert-triangle:outline",
            "source": self.plugin_static_file("assembly_risk.js:renderPanel"),
            "context": {"rows": rows, "build_id": build_id},
        }]
