"""One NSE results XBRL document as plain values: its format, basis, period and the quarter's and
year-to-date figures. Pure: bytes in, `Parsed` out. The rules are in docs/parser-rules.md.

NSE's instances (Reg 33 and Integrated Filing alike) put the whole statement in two contexts that
the document references but often never defines: `OneD`, the quarter, and `FourD`, the financial
year to date. The quarter is read from `OneD` only, never from `FourD` (in a Q3 document `FourD`
holds nine months). The period comes from the document's own `DateOfStartOfReportingPeriod` /
`DateOfEndOfReportingPeriod` facts in each context, not from the listing; Reg 33 bank documents
give only the end, so the quarter starts three months before it.

Tags: revenue is `RevenueFromOperations`, or `InterestEarned` for banks (and where there is no
revenue from operations). Net profit is the profit attributable to the owners of the parent
where a consolidated document tags it, else the period's profit. EPS is basic and diluted from
continuing and discontinued operations (banks: after extraordinary items). Money facts must be
in INR and EPS in INR a share, as the fact's unit declares; values are in rupees whatever the
stated rounding level.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .num import exact

QUARTER_CONTEXT = "OneD"
YTD_CONTEXT = "FourD"
MAX_ABS_VALUE = Decimal(10) ** 15

_UNSAFE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_SCHEMA_REF = re.compile(rb"schemaRef[^>]*?href=\"([^\"]+)\"")
_INTEGRATED_NS = re.compile(rb"/xbrl/IntegratedFinance_([A-Za-z]+)/")
_SCHEMA_FORMATS = (
    ("banking_entry_point", "reg33_banking"),
    ("ind-as_entry_point", "reg33_indas"),
    ("other_than_banks_entry_point", "reg33_non_indas"),
    ("in-bse-fin-", "reg33_nbfc"),
)
_INSURER_VARIANTS = ("li", "gi", "insurance", "lifeinsurance", "generalinsurance")
_XBRLI = "{http://www.xbrl.org/2003/instance}"
INSURANCE = "insurance_skipped"

REVENUE_TAGS = ("RevenueFromOperations", "TotalRevenueFromOperations", "InterestEarned")
BANK_REVENUE_TAGS = ("InterestEarned", "RevenueFromOperations")
INCOME_TAGS = ("Income", "TotalIncome")
OWNERS_PROFIT_TAGS = (
    "ProfitOrLossAttributableToOwnersOfParent",
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
)
PROFIT_TAGS = (
    "ProfitLossForPeriod",
    "ProfitLossForThePeriod",
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
)
BASIC_EPS_TAGS = (
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "BasicEarningsLossPerShareFromContinuingOperations",
    "BasicEarningsPerShareAfterExtraordinaryItems",
    "BasicEarningsPerShareBeforeExtraordinaryItems",
)
DILUTED_EPS_TAGS = (
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "DilutedEarningsLossPerShareFromContinuingOperations",
    "DilutedEarningsPerShareAfterExtraordinaryItems",
    "DilutedEarningsPerShareBeforeExtraordinaryItems",
)
MONEY_UNIT = "iso4217:inr"
EPS_UNIT = "iso4217:inr/xbrli:shares"


# --- classification -------------------------------------------------------------------------


@dataclass(frozen=True)
class XbrlKind:
    format: str  # reg33_* | integrated_* | insurance_skipped | other | not_xbrl
    schema_ref: str


def classify(body: bytes) -> XbrlKind:
    """The taxonomy of an NSE results XBRL instance, from its schemaRef and namespaces."""
    head = body[:20000]
    ref = _SCHEMA_REF.search(head)
    schema = ref.group(1).decode(errors="replace") if ref else ""
    if not schema or b"xbrl" not in head[:2000]:
        return XbrlKind("not_xbrl", schema)
    integrated = _INTEGRATED_NS.search(head)
    if integrated:
        variant = integrated.group(1).decode().lower()
        raw = INSURANCE if variant in _INSURER_VARIANTS else f"integrated_{variant}"
    elif b"/xbrl/Insurance/" in head:
        raw = INSURANCE
    else:
        lowered = schema.lower()
        raw = next(
            (kind for prefix, kind in _SCHEMA_FORMATS if lowered.startswith(prefix)), "other"
        )
    return XbrlKind(raw, schema)


# --- facts ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    text: str
    unit: str  # the unit's measures, lower case ("iso4217:inr"), "" for a non-numeric fact


Facts = dict[str, dict[str, Fact]]  # context id -> local name -> fact (the first one kept)
Periods = dict[str, tuple[date | None, date | None]]


class XbrlError(ValueError):
    """A document that cannot be read; the message is the exclusion reason."""


class _NoDoctype(ET.TreeBuilder):
    """A tree builder that refuses a doctype where the parser meets it, before any entity it
    declares is expanded."""

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise XbrlError("xbrl_doctype")


def read_facts(body: bytes) -> tuple[Facts, Periods]:
    """Every fact by context, and each defined context's period (start, end; an instant has
    only the end)."""
    if _UNSAFE.search(body):
        raise XbrlError("xbrl_doctype")
    try:
        root = ET.fromstring(body, parser=ET.XMLParser(target=_NoDoctype()))  # noqa: S314
    except ET.ParseError as exc:
        raise XbrlError("xbrl_malformed") from exc
    units: dict[str, str] = {}
    periods: Periods = {}
    for unit in root.iter(f"{_XBRLI}unit"):
        measures = [(m.text or "").strip().lower() for m in unit.iter(f"{_XBRLI}measure")]
        units[unit.get("id", "")] = "/".join(measures)
    for context in root.iter(f"{_XBRLI}context"):
        period = context.find(f"{_XBRLI}period")
        if period is None:
            continue
        start = _date(period.findtext(f"{_XBRLI}startDate"))
        end = _date(period.findtext(f"{_XBRLI}endDate") or period.findtext(f"{_XBRLI}instant"))
        periods[context.get("id", "")] = (start, end)
    facts: Facts = {}
    for element in root:
        ref = element.get("contextRef")
        if ref is None:
            continue
        name = element.tag.rsplit("}", 1)[-1]
        unit = units.get(element.get("unitRef") or "", "")
        facts.setdefault(ref, {}).setdefault(name, Fact((element.text or "").strip(), unit))
    return facts, periods


def _date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def _number(fact: Fact | None, unit: str) -> Decimal | None:
    if fact is None or not fact.text:
        return None
    if fact.unit != unit:
        raise XbrlError("unit_not_inr" if unit == MONEY_UNIT else "unit_not_inr_per_share")
    value = exact(fact.text)
    if value is None:
        raise XbrlError("value_not_numeric")
    if abs(value) >= MAX_ABS_VALUE:
        raise XbrlError("value_out_of_range")
    return value


def _first(context: dict[str, Fact], tags: tuple[str, ...], unit: str) -> Decimal | None:
    for tag in tags:
        value = _number(context.get(tag), unit)
        if value is not None:
            return value
    return None


# --- figures --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Figures:
    revenue: Decimal | None
    total_income: Decimal | None
    net_profit: Decimal | None
    eps_basic: Decimal | None
    eps_diluted: Decimal | None

    def minus(self, other: Figures) -> Figures:
        """These figures less `other`'s, field by field (None where either is None)."""

        def sub(a: Decimal | None, b: Decimal | None) -> Decimal | None:
            return None if a is None or b is None else a - b

        return Figures(
            sub(self.revenue, other.revenue),
            sub(self.total_income, other.total_income),
            sub(self.net_profit, other.net_profit),
            sub(self.eps_basic, other.eps_basic),
            sub(self.eps_diluted, other.eps_diluted),
        )

    def key(self) -> tuple[Decimal | None, ...]:
        """The values, normalised (1.50 == 1.5), for comparing two filings."""
        values = (self.revenue, self.total_income, self.net_profit, self.eps_basic)
        return tuple(None if v is None else v.normalize() for v in (*values, self.eps_diluted))


def figures(context: dict[str, Fact], kind: str, basis: str) -> Figures:
    """One context's figures under the tag rules above (`kind` the document format)."""
    banking = kind.endswith("banking")
    revenue = _first(context, BANK_REVENUE_TAGS if banking else REVENUE_TAGS, MONEY_UNIT)
    period_profit = _first(context, PROFIT_TAGS, MONEY_UNIT)
    profit = period_profit
    if basis == "consolidated":
        owners = _first(context, OWNERS_PROFIT_TAGS, MONEY_UNIT)
        # a template field left at 0 while the period shows a profit is not the owners' share
        if owners is not None and (owners != 0 or not period_profit):
            profit = owners
    return Figures(
        revenue,
        _first(context, INCOME_TAGS, MONEY_UNIT),
        profit,
        _eps(context, "Basic", BASIC_EPS_TAGS),
        _eps(context, "Diluted", DILUTED_EPS_TAGS),
    )


def _copied_parts(context: dict[str, Fact], kind: str) -> Decimal | None:
    """The continuing-operations EPS when the document copied it into the discontinued field
    (both equal, non-zero, and the total their sum, a filing error seen in a real Q4 document:
    12.50 + 12.50 = 25.00 with no discontinued operations), else None."""
    stem = f"{kind}EarningsLossPerShareFrom"
    total = _number(context.get(stem + "ContinuingAndDiscontinuedOperations"), EPS_UNIT)
    cont = _number(context.get(stem + "ContinuingOperations"), EPS_UNIT)
    disc = _number(context.get(stem + "DiscontinuedOperations"), EPS_UNIT)
    if None in (total, cont, disc) or cont == 0 or cont != disc or total != cont + disc:
        return None
    return cont


def _eps(context: dict[str, Fact], kind: str, tags: tuple[str, ...]) -> Decimal | None:
    copied = _copied_parts(context, kind)
    return copied if copied is not None else _first(context, tags, EPS_UNIT)


def eps_corrected(context: dict[str, Fact]) -> bool:
    """Whether `figures` replaced the context's basic EPS total (`_copied_parts`)."""
    return _copied_parts(context, "Basic") is not None


# --- the document ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Parsed:
    kind: XbrlKind
    basis: str  # from NatureOfReportStandaloneConsolidated; "" when absent
    period_start: date | None
    period_end: date | None
    quarter: Figures | None  # None for an insurer, or a Q4 document with only the year
    ytd_start: date | None
    ytd: Figures | None
    annual: Figures | None  # a Q4 document with only the year: the year's figures
    nine_month: Figures | None  # ... and nine months, when the document carries them
    fy_start: date | None
    eps_corrected: bool = False  # the quarter's EPS total was a filing error (`_copied_parts`)


def quarter_start(end: date) -> date:
    """The first day of the three-month quarter ending on `end` (a month end)."""
    month = end.month - 2
    year = end.year
    if month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _span_days(start: date | None, end: date | None) -> int | None:
    return None if start is None or end is None else (end - start).days


def _period(
    context: dict[str, Fact], defined: tuple[date | None, date | None] | None
) -> tuple[date | None, date | None]:
    start = _date(_text(context, "DateOfStartOfReportingPeriod"))
    end = _date(_text(context, "DateOfEndOfReportingPeriod"))
    if defined is not None:
        start = start or defined[0]
        end = end or defined[1]
    return start, end


def _text(context: dict[str, Fact], name: str) -> str:
    fact = context.get(name)
    return fact.text if fact else ""


def basis_of_document(facts: Facts) -> str:
    for ref in (QUARTER_CONTEXT, YTD_CONTEXT):
        text = _text(facts.get(ref, {}), "NatureOfReportStandaloneConsolidated").lower()
        if text.startswith("consolidated"):
            return "consolidated"
        if text.startswith("standalone"):
            return "standalone"
    return ""


def parse(body: bytes) -> Parsed:
    """The document's format, basis, period and figures; raises `XbrlError` (its message the
    exclusion reason) when the quarter cannot be read."""
    kind = classify(body)
    if kind.format == "not_xbrl":
        raise XbrlError("not_xbrl")
    facts, periods = read_facts(body)
    basis = basis_of_document(facts)
    one = facts.get(QUARTER_CONTEXT, {})
    four = facts.get(YTD_CONTEXT, {})
    start, end = _period(one, periods.get(QUARTER_CONTEXT))
    ytd_start, ytd_end = _period(four, periods.get(YTD_CONTEXT))
    fy_start = _date(_text(one, "DateOfStartOfFinancialYear"))
    ytd_start = ytd_start or (fy_start if ytd_end else None)
    if kind.format == INSURANCE:
        return Parsed(kind, basis, start, end, None, ytd_start, None, None, None, fy_start)
    if end is None:
        raise XbrlError("period_missing")
    if not one:
        raise XbrlError("quarter_context_missing")
    quarter = figures(one, kind.format, basis)
    ytd = figures(four, kind.format, basis) if four else None
    if _annual_only(start, end, fy_start, ytd_start, quarter, ytd):
        nine = _nine_month(facts, periods, kind.format, basis, end)
        q_start = quarter_start(end)
        return Parsed(
            kind, basis, q_start, end, None, fy_start or start, quarter, quarter, nine, fy_start
        )
    q_start = start or quarter_start(end)
    return Parsed(
        kind, basis, q_start, end, quarter, ytd_start, ytd, None, None, fy_start, eps_corrected(one)
    )


def _annual_only(
    start: date | None,
    end: date,
    fy_start: date | None,
    ytd_start: date | None,
    quarter: Figures,
    ytd: Figures | None,
) -> bool:
    """Whether the quarter context holds the whole year (a Q4 document with only annual
    figures): it spans more than a quarter, or it starts the financial year, ends the year and
    equals the year to date (in Q1 the two are equal legitimately, but Q1 does not end a year)."""
    span = _span_days(start, end)
    if span is not None:
        return span > 100
    year_start = fy_start or ytd_start
    if year_start is None or (end - year_start).days < 300 or ytd is None:
        return False
    return quarter == ytd


def _nine_month(facts: Facts, periods: Periods, kind: str, basis: str, end: date) -> Figures | None:
    """The nine months to the end of Q3 when the document carries them in some context."""
    for ref, context in facts.items():
        if ref in (QUARTER_CONTEXT, YTD_CONTEXT):
            continue
        start, stop = _period(context, periods.get(ref))
        span = _span_days(start, stop)
        if span is None or stop is None or not 250 <= span <= 290:
            continue
        if 88 <= (end - stop).days <= 92:
            found = figures(context, kind, basis)
            if found.revenue is not None:
                return found
    return None
