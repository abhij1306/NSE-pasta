"""Writing and reading the output tables: each one a CSV (plain text, exact decimals) and a
Parquet file (typed: decimals as decimal128, times as UTC timestamps) with the same columns.
docs/schema.md lists every column."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .layout import atomic_write, write_text

# column kinds
TEXT, DAY, TIME, MONEY, RATIO, INT, BOOL = "text", "date", "time", "money", "ratio", "int", "bool"
MONEY_SCALE = 4  # rupees and rupees a share, to 1/100 paisa
RATIO_SCALE = 6
_ARROW = {
    TEXT: pa.string(),
    DAY: pa.date32(),
    TIME: pa.timestamp("s", tz="UTC"),
    MONEY: pa.decimal128(24, MONEY_SCALE),
    RATIO: pa.decimal128(24, RATIO_SCALE),
    INT: pa.int64(),
    BOOL: pa.bool_(),
}

Schema = Sequence[tuple[str, str]]


def _quantized(value: Decimal, scale: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-scale))


def _arrow_value(value: Any, kind: str) -> Any:
    if value is None or value == "":
        return None if kind != TEXT else value
    if kind == TIME:
        return value.astimezone(UTC)
    if kind == MONEY:
        return _quantized(value, MONEY_SCALE)
    if kind == RATIO:
        return _quantized(value, RATIO_SCALE)
    return value


def _text(value: Any, kind: str) -> str:
    if value is None:
        return ""
    if kind == BOOL:
        return "true" if value else "false"
    if kind == TIME:
        return value.isoformat()
    if kind in (MONEY, RATIO) and isinstance(value, Decimal):
        return format(_quantized(value, MONEY_SCALE if kind == MONEY else RATIO_SCALE), "f")
    return str(value)


def to_csv(rows: Iterable[Mapping[str, Any]], schema: Schema) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([name for name, _ in schema])
    for row in rows:
        writer.writerow([_text(row.get(name), kind) for name, kind in schema])
    return buf.getvalue()


def to_arrow(rows: Sequence[Mapping[str, Any]], schema: Schema) -> pa.Table:
    arrays = {
        name: pa.array([_arrow_value(r.get(name), kind) for r in rows], type=_ARROW[kind])
        for name, kind in schema
    }
    return pa.table(arrays)


def write(folder: Path, stem: str, rows: Sequence[Mapping[str, Any]], schema: Schema) -> None:
    """`folder/stem.csv` and `folder/stem.parquet`, each written whole or not at all."""
    write_text(folder / f"{stem}.csv", to_csv(rows, schema))
    table = to_arrow(rows, schema)
    atomic_write(folder / f"{stem}.parquet", lambda tmp: pq.write_table(table, tmp))


def write_csv(folder: Path, stem: str, rows: Sequence[Mapping[str, Any]], schema: Schema) -> None:
    write_text(folder / f"{stem}.csv", to_csv(rows, schema))


def read_csv(path: Path, schema: Schema) -> list[dict[str, Any]]:
    """A table written by `write`, read back with its types."""
    kinds = dict(schema)
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {k: _parse(v, kinds.get(k, TEXT)) for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def _parse(raw: str, kind: str) -> Any:
    if kind == TEXT:
        return raw
    if raw == "":
        return None
    if kind == DAY:
        return date.fromisoformat(raw)
    if kind == TIME:
        return datetime.fromisoformat(raw)
    if kind in (MONEY, RATIO):
        return Decimal(raw)
    if kind == INT:
        return int(raw)
    return raw == "true"
