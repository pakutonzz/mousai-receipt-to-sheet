"""Which column carries which field, per Fund.

A Template says nothing about where the data region lies: that differs from Page
to Page even inside one Fund (the petty-cash Pages run 24, 25, 26, 28 and 32
rows) and is read off the Page itself. See CONTEXT.md.
"""

from __future__ import annotations

from dataclasses import dataclass

TOTALS_MARKER = "รวมทั้งสิ้น"


@dataclass(frozen=True)
class Template:
    """Column letters for one Fund's Pages."""

    fund: str
    header_marker: str
    date: str
    sequence: str
    description: str
    received: str
    disbursed: str
    balance: str
    requester: str
    note: str
    totals_marker: str = TOTALS_MARKER

    @property
    def columns(self) -> tuple[str, ...]:
        return (
            self.date,
            self.sequence,
            self.description,
            self.received,
            self.disbursed,
            self.balance,
            self.requester,
            self.note,
        )


PETTY_CASH = Template(
    fund="เงินสดย่อย",
    header_marker="ว/ด/ป",
    date="B",
    sequence="C",
    description="D",
    received="E",
    disbursed="F",
    balance="G",
    requester="H",
    note="I",
)

EMERGENCY = Template(
    fund="เงินฉุกเฉิน",
    header_marker="ว/ด/ป",
    date="A",
    sequence="B",
    description="C",
    received="D",
    disbursed="E",
    balance="F",
    requester="G",
    note="H",
)

# Certificate sheets head their date column differently and carry no balance.
# Out of scope for this phase; here so the difference is recorded rather than
# rediscovered. See .scratch/receipt-to-sheet/spec.md.
CERTIFICATE_HEADER_MARKER = "วันที่"

BY_FUND: dict[str, Template] = {t.fund: t for t in (PETTY_CASH, EMERGENCY)}
