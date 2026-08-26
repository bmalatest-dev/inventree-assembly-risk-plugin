"""Build-order scope helpers for Assembly Risk."""

from __future__ import annotations


def normalize_build_ids(build_ids):
    """Normalize an optional iterable of Build IDs."""
    if build_ids is None:
        return None

    if isinstance(build_ids, (str, bytes)):
        build_ids = [build_ids]

    result = set()

    for value in build_ids:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue

        if value > 0:
            result.add(value)

    return tuple(sorted(result))


def include_queried_build(queried_build_id, build_ids):
    """Ensure the queried Build Order is always in an explicit scope."""
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
    """Return a deterministic cache suffix for one demand scope."""
    normalized = normalize_build_ids(build_ids)

    if normalized is None:
        return "all-production"

    if not normalized:
        return "none"

    return "builds-" + "-".join(str(value) for value in normalized)
