"""Build-order scope helpers for Assembly Risk.

``None`` means the legacy / global scope: all Production Build Orders.
An explicit iterable means: only those Production Build Orders, with the queried
build automatically included by the public per-stock-item API.
"""
from __future__ import annotations

from collections.abc import Iterable


def normalize_build_ids(build_ids):
    """Normalize an optional iterable of Build IDs.

    Returns:
        None: global / all-Production scope
        tuple[int, ...]: sorted unique explicit Build IDs
    """
    if build_ids is None:
        return None

    # A single string is not treated as an iterable of characters.
    if isinstance(build_ids, (str, bytes)):
        build_ids = [build_ids]

    normalized = set()

    for value in build_ids:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue

        if value > 0:
            normalized.add(value)

    return tuple(sorted(normalized))


def include_queried_build(queried_build_id, build_ids):
    """Ensure an explicit scope always contains the BO being queried."""
    normalized = normalize_build_ids(build_ids)

    if normalized is None:
        return None

    try:
        queried_build_id = int(queried_build_id)
    except (TypeError, ValueError):
        return normalized

    if queried_build_id <= 0:
        return normalized

    return tuple(sorted(set(normalized) | {queried_build_id}))


def scope_cache_suffix(build_ids):
    """Return a deterministic cache-key suffix for a demand scope."""
    normalized = normalize_build_ids(build_ids)

    if normalized is None:
        return "all-production"

    if not normalized:
        return "none"

    return "builds-" + "-".join(str(value) for value in normalized)
