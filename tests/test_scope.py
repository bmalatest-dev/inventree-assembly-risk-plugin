from inventree_assembly_risk.scope import (
    include_queried_build,
    normalize_build_ids,
    scope_cache_suffix,
)


def test_none_means_all_production():
    assert normalize_build_ids(None) is None
    assert scope_cache_suffix(None) == "all-production"


def test_explicit_scope_normalizes_and_deduplicates():
    assert normalize_build_ids([14, "12", 14, None, "bad"]) == (12, 14)


def test_queried_build_is_always_in_explicit_scope():
    assert include_queried_build(13, [14, 15]) == (13, 14, 15)


def test_empty_scope_becomes_current_build_only():
    assert include_queried_build(13, []) == (13,)


def test_cache_suffix_is_order_independent():
    assert scope_cache_suffix([15, 13, 14]) == "builds-13-14-15"
