"""Validate and summarize one bounded sales CSV."""

import csv
import re
from dataclasses import dataclass
from io import StringIO
from typing import Any

MAX_CSV_BYTES = 512 * 1024
CSV_JOB_TYPE = "csv_sales_summary"
MAX_ROWS = 10_000
MAX_REGIONS = 64
MAX_QUANTITY = 1_000_000
MAX_PRICE_CENTS = 100_000_000
COLUMNS = frozenset(("order_id", "region", "quantity", "unit_price"))
ORDER_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")
QUANTITY = re.compile(r"[0-9]{1,7}")
PRICE = re.compile(r"[0-9]{1,7}(?:\.[0-9]{1,2})?")


class InvalidCSV(ValueError):
    """A permanent validation failure whose message contains no input values."""


@dataclass
class Sales:
    orders: int = 0
    units: int = 0
    cents: int = 0

    def record(self, quantity: int, unit_price: int) -> None:
        self.orders += 1
        self.units += quantity
        self.cents += quantity * unit_price

    def summary(self) -> dict[str, int | str]:
        return {"orders": self.orders, "units_sold": self.units, "revenue": money(self.cents)}


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def price_cents(value: str, row: int) -> int:
    if not PRICE.fullmatch(value):
        raise InvalidCSV(f"Row {row} has an invalid unit_price.")
    whole, _, fraction = value.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if cents > MAX_PRICE_CENTS:
        raise InvalidCSV(f"Row {row} exceeds the unit_price limit.")
    return cents


def summarize_sales(source: str) -> dict[str, Any]:
    if len(source.encode("utf-8")) > MAX_CSV_BYTES:
        raise InvalidCSV("CSV exceeds the 512 KiB limit.")

    reader = csv.reader(StringIO(source, newline=""), strict=True)
    orders: set[str] = set()
    regions: dict[str, Sales] = {}
    totals = Sales()
    try:
        header = next(reader, [])
        if len(header) != len(COLUMNS) or set(header) != COLUMNS:
            raise InvalidCSV("Expected the columns order_id, region, quantity, and unit_price.")
        order_index, region_index, quantity_index, price_index = (
            header.index(field) for field in ("order_id", "region", "quantity", "unit_price")
        )
        for number, row in enumerate(reader, start=2):
            if number > MAX_ROWS + 1:
                raise InvalidCSV(f"CSV exceeds {MAX_ROWS:,} data rows.")
            if len(row) != len(COLUMNS):
                raise InvalidCSV(f"Row {number} must have exactly four fields.")
            order_id = row[order_index]
            if not ORDER_ID.fullmatch(order_id) or order_id in orders:
                raise InvalidCSV(f"Row {number} has an invalid or duplicate order_id.")
            orders.add(order_id)

            region = row[region_index].strip()
            if not region or len(region) > 64 or not region.isprintable():
                raise InvalidCSV(f"Row {number} has an invalid region.")
            if region not in regions:
                if len(regions) == MAX_REGIONS:
                    raise InvalidCSV(f"CSV exceeds {MAX_REGIONS} distinct regions.")
                regions[region] = Sales()

            value = row[quantity_index]
            if not QUANTITY.fullmatch(value) or not 1 <= (quantity := int(value)) <= MAX_QUANTITY:
                raise InvalidCSV(f"Row {number} has an invalid quantity.")
            price = price_cents(row[price_index], number)
            totals.record(quantity, price)
            regions[region].record(quantity, price)
    except csv.Error as exc:
        raise InvalidCSV(f"CSV could not be parsed near line {reader.line_num}.") from exc

    if not orders:
        raise InvalidCSV("CSV must contain at least one data row.")
    average_cents = (2 * totals.cents + totals.orders) // (2 * totals.orders)
    return {
        **totals.summary(),
        "average_order_value": money(average_cents),
        "regions": [{"region": region, **sales.summary()} for region, sales in sorted(regions.items())],
    }
