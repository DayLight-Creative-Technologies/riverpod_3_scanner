"""Fixture corpus regression tests.

Every fixture file in tests/fixtures/ has a pinned expectation: the exact
(violation_type, line_number) pairs the scanner must produce for it. A
``*_violations.dart`` fixture asserts every documented violation is caught at
the documented line; a ``*_passing.dart`` fixture asserts zero false
positives. Any drift in either direction is a regression.
"""

from pathlib import Path

import pytest

from riverpod_3_scanner.scanner import RiverpodScanner

FIXTURES = Path(__file__).parent / "fixtures"

# The pinned corpus: fixture file -> exact sorted (type, line) expectations.
EXPECTED = {
    "async_star_provider_passing.dart": [],
    "async_star_provider_violations.dart": [
        ("async_star_ref_before_mounted", 14),
        ("async_star_ref_before_mounted", 21),
        ("async_star_ref_before_mounted", 28),
        ("async_star_ref_before_mounted", 37),
        ("async_star_ref_before_mounted", 45),
    ],
    # build() is exempt from the ENTRY-GUARD check (VIOLATION 4) — the
    # framework calls it while the provider is being created, so a pre-await
    # ref op cannot throw. The violations fixture pins that the dangerous
    # shapes are still caught: a ref op AFTER an await inside build() (owned by
    # VIOLATION 5) and the ordinary non-build entry-guard miss. SSK gap #728.
    "build_ref_op_passing.dart": [],
    "build_ref_op_violations.dart": [
        ("missing_mounted_after_await", 23),
        ("ref_read_before_mounted", 40),
    ],
    "catch_block_passing.dart": [],
    "catch_block_violations.dart": [
        ("missing_mounted_in_catch", 20),
        ("missing_mounted_in_catch", 32),
        ("missing_mounted_in_catch", 44),
    ],
    # Log-first catch blocks (log through a logger captured while mounted, THEN
    # guard): VIOLATION 6 judges the WHOLE catch body — leftmost ref/state use vs
    # leftmost guard — so a ref/state use after a multi-line log is caught, and
    # a captured-logger call / a message or comment that merely MENTIONS ref or
    # state before the guard is not. A POSITIVE check (`if (mounted) { ... }`)
    # guards only its own block — a use in the `else` branch or after the block
    # is still unguarded.
    "catch_block_log_first_passing.dart": [],
    "catch_block_log_first_violations.dart": [
        ("missing_mounted_in_catch", 24),
        ("missing_mounted_in_catch", 41),
        ("missing_mounted_in_catch", 58),
        ("missing_mounted_in_catch", 73),
        ("missing_mounted_in_catch", 89),
        ("missing_mounted_in_catch", 106),
        ("missing_mounted_in_catch", 136),
        ("missing_mounted_in_catch", 154),
        # `$state` / `${state}` inside a message is a state read (v1.14.1: v1.14.0
        # blanked the `$identifier` shorthand and missed it).
        ("missing_mounted_in_catch", 183),
        ("missing_mounted_in_catch", 196),
        ("missing_mounted_in_catch", 210),
    ],
    "event_handler_params_passing.dart": [],
    "event_handler_params_violations.dart": [
        ("deferred_callback_unsafe_ref", 15),
        ("deferred_callback_unsafe_ref", 23),
    ],
    "field_caching_bang_passing.dart": [],
    "field_caching_bang_violations.dart": [
        ("field_caching", 23),
        ("field_caching", 49),
    ],
    "hook_consumer_widget_passing.dart": [],
    "hook_consumer_widget_violations.dart": [
        ("deferred_callback_unsafe_ref", 14),
        ("deferred_callback_unsafe_ref", 33),
    ],
    "offframe_async_passing.dart": [],
    "offframe_async_violations.dart": [
        ("deferred_callback_unsafe_ref", 32),
        ("deferred_callback_unsafe_ref", 57),
        ("deferred_callback_unsafe_ref", 81),
        ("deferred_callback_unsafe_ref", 107),
    ],
    "ref_into_plain_class_passing.dart": [],
    "ref_into_plain_class_violations.dart": [
        ("ref_passed_to_plain_class", 23),
        ("ref_passed_to_plain_class", 28),
        ("ref_passed_to_plain_class", 34),
        ("ref_stored_as_field", 12),
        ("ref_stored_as_field", 18),
    ],
    "state_access_passing.dart": [],
    "state_access_violations.dart": [
        ("ref_read_before_mounted", 36),
    ],
    "state_assign_await_passing.dart": [],
    "state_assign_await_violations.dart": [
        ("state_assign_await", 16),
        ("state_assign_await", 22),
    ],
}


def test_every_fixture_has_an_expectation():
    """A fixture without a pinned expectation is an untested fixture."""
    on_disk = {f.name for f in FIXTURES.glob("*.dart")}
    assert on_disk == set(EXPECTED), (
        "Fixture corpus and EXPECTED table drifted apart"
    )


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED))
def test_fixture_produces_exact_expected_violations(fixture_name):
    scanner = RiverpodScanner()
    violations = scanner.scan_file(FIXTURES / fixture_name)
    got = sorted((v.violation_type.value, v.line_number) for v in violations)
    assert got == sorted(EXPECTED[fixture_name])
