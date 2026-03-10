"""Data models for the Riverpod 3.0 Safety Scanner."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


# Type alias for method identification
MethodKey = Tuple[str, str, str]  # (file_path, class_name, method_name)


class Severity(Enum):
    """Violation severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    DEFENSIVE = "defensive"


class ViolationType(Enum):
    """Types of Riverpod 3.0 violations."""
    FIELD_CACHING = "field_caching"
    LAZY_GETTER = "lazy_getter"
    ASYNC_GETTER = "async_getter"
    REF_READ_BEFORE_MOUNTED = "ref_read_before_mounted"
    MISSING_MOUNTED_AFTER_AWAIT = "missing_mounted_after_await"
    MISSING_MOUNTED_IN_CATCH = "missing_mounted_in_catch"
    NULLABLE_FIELD_ACCESS = "nullable_field_access"
    REF_IN_LIFECYCLE_CALLBACK = "ref_in_lifecycle_callback"
    REF_LISTEN_OUTSIDE_BUILD = "ref_listen_outside_build"
    REF_WATCH_OUTSIDE_BUILD = "ref_watch_outside_build"
    WIDGET_LIFECYCLE_UNSAFE_REF = "widget_lifecycle_unsafe_ref"
    DEFERRED_CALLBACK_UNSAFE_REF = "deferred_callback_unsafe_ref"
    UNTYPED_LAZY_GETTER = "untyped_lazy_getter"
    MOUNTED_VS_REF_MOUNTED_CONFUSION = "mounted_vs_ref_mounted_confusion"
    INITSTATE_FIELD_ACCESS_BEFORE_CACHING = "initstate_field_access_before_caching"
    SYNC_METHOD_WITHOUT_MOUNTED_CHECK = "sync_method_without_mounted_check"
    REF_STORED_AS_FIELD = "ref_stored_as_field"


VIOLATION_SEVERITY = {
    ViolationType.FIELD_CACHING: Severity.CRITICAL,
    ViolationType.LAZY_GETTER: Severity.CRITICAL,
    ViolationType.ASYNC_GETTER: Severity.CRITICAL,
    ViolationType.REF_READ_BEFORE_MOUNTED: Severity.CRITICAL,
    ViolationType.MISSING_MOUNTED_AFTER_AWAIT: Severity.CRITICAL,
    ViolationType.MISSING_MOUNTED_IN_CATCH: Severity.CRITICAL,
    ViolationType.NULLABLE_FIELD_ACCESS: Severity.CRITICAL,
    ViolationType.REF_IN_LIFECYCLE_CALLBACK: Severity.CRITICAL,
    ViolationType.REF_LISTEN_OUTSIDE_BUILD: Severity.CRITICAL,
    ViolationType.REF_WATCH_OUTSIDE_BUILD: Severity.WARNING,
    ViolationType.WIDGET_LIFECYCLE_UNSAFE_REF: Severity.WARNING,
    ViolationType.DEFERRED_CALLBACK_UNSAFE_REF: Severity.WARNING,
    ViolationType.UNTYPED_LAZY_GETTER: Severity.DEFENSIVE,
    ViolationType.MOUNTED_VS_REF_MOUNTED_CONFUSION: Severity.DEFENSIVE,
    ViolationType.INITSTATE_FIELD_ACCESS_BEFORE_CACHING: Severity.CRITICAL,
    ViolationType.SYNC_METHOD_WITHOUT_MOUNTED_CHECK: Severity.CRITICAL,
    ViolationType.REF_STORED_AS_FIELD: Severity.CRITICAL,
}


@dataclass
class Violation:
    """Represents a detected violation."""
    file_path: str
    class_name: str
    violation_type: ViolationType
    line_number: int
    context: str
    code_snippet: str
    fix_instructions: str


@dataclass
class MethodMetadata:
    """Metadata for a tracked method."""
    has_ref_read: bool
    has_mounted_check: bool
    is_async: bool
    is_lifecycle_method: bool
    method_body: str
    is_consumer_state: bool
