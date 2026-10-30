"""Compare each invoice line with the last price paid to the same supplier.

Rules a business owner can read:
- An item is the same item if the supplier, the product code (or, without one,
  the description) and the unit all match. Different units are never compared.
- A price change is reported when it moves by at least the threshold (default 3%).
- A fee or surcharge line that appears for the first time is reported as a new charge.
- Nothing is paid, disputed or sent. People decide what to do.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .schema import Invoice, LineItem

FEE_WORDS = ("fee", "surcharge", "charge", "handling", "delivery", "shipping", "freight", "fuel")
HISTORY_FIELDS = ["invoice_date", "supplier", "item_key", "description", "unit", "unit_price",
                  "quantity", "currency", "invoice_number"]


@dataclass
class Finding:
    kind: str                 # "price_up", "price_down" or "new_charge"
    supplier: str
    description: str
    unit: str
    currency: str
    invoice_number: str
    invoice_date: str
    new_price: float
    quantity: float
    old_price: float | None = None
    old_date: str | None = None

    @property
    def change_pct(self) -> float | None:
        if self.old_price in (None, 0):
            return None
        return (self.new_price - self.old_price) / self.old_price * 100

    @property
    def extra_cost(self) -> float:
        """What this change cost on this invoice alone."""
        if self.kind == "new_charge":
            return self.new_price * self.quantity
        return (self.new_price - (self.old_price or 0)) * self.quantity


def _supplier_key(name: str) -> str:
    return " ".join(name.lower().split())


def _is_fee(item: LineItem) -> bool:
    return any(w in item.description.lower() for w in FEE_WORDS)


class PriceHistory:
    """Last known price per (supplier, item, unit). Stored as a plain CSV you can open in any sheet."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.rows: list[dict] = []
        self.seen_invoices: set[tuple[str, str]] = set()
        if path and path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                self.rows = list(csv.DictReader(f))
            self.seen_invoices = {(_supplier_key(r["supplier"]), r["invoice_number"])
                                  for r in self.rows}

    def last(self, supplier: str, key: str, unit: str, before: str) -> dict | None:
        match = [r for r in self.rows
                 if _supplier_key(r["supplier"]) == _supplier_key(supplier)
                 and r["item_key"] == key and r["unit"].lower() == unit.lower()
                 and r["invoice_date"] < before]
        return max(match, key=lambda r: r["invoice_date"]) if match else None

    def known_supplier(self, supplier: str, before: str) -> bool:
        return any(_supplier_key(r["supplier"]) == _supplier_key(supplier) and r["invoice_date"] < before
                   for r in self.rows)

    def add(self, inv: Invoice) -> None:
        self.seen_invoices.add((_supplier_key(inv.supplier), inv.invoice_number))
        for li in inv.lines:
            self.rows.append({
                "invoice_date": inv.invoice_date, "supplier": inv.supplier, "item_key": li.key,
                "description": li.description, "unit": li.unit, "unit_price": f"{li.unit_price:.2f}",
                "quantity": f"{li.quantity:g}", "currency": inv.currency,
                "invoice_number": inv.invoice_number,
            })

    def save(self) -> None:
        if not self.path:
            return
        with self.path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            w.writeheader()
            w.writerows(sorted(self.rows, key=lambda r: (r["invoice_date"], r["supplier"])))


def check_invoice(inv: Invoice, history: PriceHistory, threshold_pct: float = 3.0) -> list[Finding]:
    """Findings for one invoice against the history recorded before its date."""
    findings: list[Finding] = []
    known = history.known_supplier(inv.supplier, inv.invoice_date)
    for li in inv.lines:
        prev = history.last(inv.supplier, li.key, li.unit, inv.invoice_date)
        base = dict(supplier=inv.supplier, description=li.description, unit=li.unit, currency=inv.currency,
                    invoice_number=inv.invoice_number, invoice_date=inv.invoice_date,
                    new_price=li.unit_price, quantity=li.quantity)
        if prev is None:
            if known and _is_fee(li):
                findings.append(Finding(kind="new_charge", **base))
            continue
        old = float(prev["unit_price"])
        if old == 0:
            continue
        pct = (li.unit_price - old) / old * 100
        if abs(pct) >= threshold_pct:
            findings.append(Finding(kind="price_up" if pct > 0 else "price_down",
                                    old_price=old, old_date=prev["invoice_date"], **base))
    return findings


def run(invoices: list[Invoice], history: PriceHistory, threshold_pct: float = 3.0) -> list[Finding]:
    """Process invoices oldest first, so each one is compared with what came before it."""
    findings: list[Finding] = []
    for inv in sorted(invoices, key=lambda i: i.invoice_date):
        if (_supplier_key(inv.supplier), inv.invoice_number) in history.seen_invoices:
            continue                       # already processed on an earlier run
        findings.extend(check_invoice(inv, history, threshold_pct))
        history.add(inv)
    return findings
