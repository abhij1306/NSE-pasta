"""Trim a real NSE XBRL document to the facts pasta reads, for a test fixture.

    uv run python scripts/trim_fixture.py IN.xml OUT.xml

Keeps the XML declaration, the root element (its namespaces), the schemaRef, the `OneD` and
`FourD` contexts, every unit, and the facts in those contexts that the parser reads, one element
a line. The output is still the company's own figures, only fewer of them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

KEEP = {
    "NatureOfReportStandaloneConsolidated",
    "DateOfStartOfReportingPeriod",
    "DateOfEndOfReportingPeriod",
    "DateOfStartOfFinancialYear",
    "DateOfEndOfFinancialYear",
    "RevenueFromOperations",
    "TotalRevenueFromOperations",
    "InterestEarned",
    "Income",
    "TotalIncome",
    "ProfitOrLossAttributableToOwnersOfParent",
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
    "ProfitLossForPeriod",
    "ProfitLossForThePeriod",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "BasicEarningsPerShareAfterExtraordinaryItems",
    "DilutedEarningsPerShareAfterExtraordinaryItems",
    "SymbolOfCompany",
}
_ROOT = re.compile(r"<xbrli:xbrl\b[^>]*>")
_SCHEMA = re.compile(r"<link:schemaRef[^>]*/>")
_UNIT = re.compile(r"<xbrli:unit\b.*?</xbrli:unit>", re.DOTALL)
_CONTEXT = re.compile(r'<xbrli:context id="(\w+)">.*?</xbrli:context>', re.DOTALL)
_FACT = re.compile(
    r'<([\w-]+):(\w+)\s[^>]*?contextRef="(\w+)"[^>]*?(?:/>|>[^<]*</\1:\2>)', re.DOTALL
)
CONTEXTS = ("OneD", "FourD")


def trim(text: str) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', _ROOT.search(text)[0]]
    out += [m[0] for m in (_SCHEMA.search(text),) if m]
    out += [m[0] for m in _CONTEXT.finditer(text) if m[1] in CONTEXTS]
    out += [m[0] for m in _UNIT.finditer(text)]
    out += [m[0] for m in _FACT.finditer(text) if m[2] in KEEP and m[3] in CONTEXTS]
    return "\n".join([*out, "</xbrli:xbrl>"]) + "\n"


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(trim(Path(sys.argv[1]).read_text(encoding="utf-8")), "utf-8")
