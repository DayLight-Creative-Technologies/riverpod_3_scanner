"""docs/GUIDE.md's violation table lists every type the scanner can report.

The table said "14 TYPES" while the scanner reported 21: seven types were added
without a row. This pins the table to the enum, so a new ViolationType without
a guide row fails here instead of going undocumented.
"""

import re
from pathlib import Path

from riverpod_3_scanner.models import VIOLATION_SEVERITY, ViolationType

GUIDE = Path(__file__).resolve().parent.parent / 'docs' / 'GUIDE.md'


def test_every_violation_type_has_a_row_in_the_guide():
    guide = GUIDE.read_text()
    missing = [t.value for t in ViolationType if f'| `{t.value}` |' not in guide]
    assert missing == []


def test_the_guide_heading_counts_the_types():
    heading = re.search(r'## 📊 VIOLATION TYPES \((\d+) TYPES\)', GUIDE.read_text())
    assert heading is not None
    assert int(heading.group(1)) == len(ViolationType)


def test_every_violation_type_has_a_severity():
    assert set(VIOLATION_SEVERITY) == set(ViolationType)
