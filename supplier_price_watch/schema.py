"""The structured shape of one supplier invoice, and strict parsing of model output."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date


class InvalidInvoice(ValueError):
    """The model (or a file) returned something we can't trust."""


@dataclass
class LineItem:
    description: str
    unit: str
    quantity: float
    unit_price: float
    sku: str | None = None

    @property
    def key(self) -> str:
        """How the same item is recognised on the next invoice from the same supplier."""
        if self.sku:
            return "sku:" + self.sku.strip().lower()
        return "desc:" + re.sub(r"\s+", " ", self.description.strip().lower())


@dataclass
class Invoice:
    supplier: str
    invoice_number: str
    invoice_date: str          # ISO date, YYYY-MM-DD
    currency: str
    lines: list[LineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise InvalidInvoice("no JSON object in output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise InvalidInvoice(f"bad JSON: {e}") from e
    if not isinstance(data, dict):
        raise InvalidInvoice("JSON is not an object")
    return data


def _text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidInvoice(f"missing or empty field: {key}")
    return value.strip()


def _number(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInvoice(f"{what} must be a number")
    if value < 0:
        raise InvalidInvoice(f"{what} can't be negative")
    return float(value)


def parse_model_output(raw: str) -> Invoice:
    """Validate the model's JSON field by field. Anything off is rejected, not guessed."""
    data = _extract_json(raw)
    inv_date = _text(data, "invoice_date")
    try:
        date.fromisoformat(inv_date)
    except ValueError as e:
        raise InvalidInvoice(f"invoice_date is not an ISO date: {inv_date}") from e

    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise InvalidInvoice("invoice has no line items")

    lines = []
    for i, item in enumerate(raw_lines):
        if not isinstance(item, dict):
            raise InvalidInvoice(f"line {i} is not an object")
        sku = item.get("sku")
        lines.append(LineItem(
            description=_text(item, "description"),
            unit=(item.get("unit") or "unit").strip() if isinstance(item.get("unit"), str) else "unit",
            quantity=_number(item.get("quantity"), f"line {i} quantity"),
            unit_price=_number(item.get("unit_price"), f"line {i} unit_price"),
            sku=sku.strip() if isinstance(sku, str) and sku.strip() else None,
        ))

    return Invoice(
        supplier=_text(data, "supplier"),
        invoice_number=_text(data, "invoice_number"),
        invoice_date=inv_date,
        currency=(data.get("currency") or "").strip().upper() or "UNKNOWN",
        lines=lines,
    )
