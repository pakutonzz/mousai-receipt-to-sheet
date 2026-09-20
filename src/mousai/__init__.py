"""Domain logic for recording clinic cash Entries.

Deliberately knows nothing about Google Sheets: `Page` takes a grid of values
and returns the cells to write, so everything that can be wrong is testable
offline against the baseline fixture.
"""

from .page import (
    Formula,
    NoOpeningRow,
    Page,
    PageError,
    Placement,
    RegionFull,
    RegionNotFound,
    Row,
    from_serial,
    to_serial,
)
from .templates import BY_FUND, EMERGENCY, PETTY_CASH, Template

__all__ = [
    "BY_FUND",
    "EMERGENCY",
    "Formula",
    "NoOpeningRow",
    "PETTY_CASH",
    "Page",
    "PageError",
    "Placement",
    "RegionFull",
    "RegionNotFound",
    "Row",
    "Template",
    "from_serial",
    "to_serial",
]
