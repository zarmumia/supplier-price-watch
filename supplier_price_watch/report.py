"""Turn findings into a short alert a business owner can read in a minute,
plus a polite draft message to each supplier. Drafts are never sent automatically."""
from __future__ import annotations

from collections import defaultdict

from .watch import Finding


def _money(amount: float, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def finding_line(f: Finding) -> str:
    if f.kind == "new_charge":
        return (f"NEW CHARGE  {f.supplier}: \"{f.description}\" {_money(f.new_price, f.currency)} "
                f"(first time, invoice {f.invoice_number}, {f.invoice_date})")
    arrow = "UP  " if f.kind == "price_up" else "DOWN"
    return (f"PRICE {arrow}  {f.supplier}: {f.description} per {f.unit} "
            f"{_money(f.old_price or 0, f.currency)} -> {_money(f.new_price, f.currency)} "
            f"({f.change_pct:+.1f}%, since {f.old_date}, invoice {f.invoice_number})")


def summary(findings: list[Finding]) -> str:
    if not findings:
        return "No price changes above the threshold. Nothing to do."
    order = {"price_up": 0, "new_charge": 1, "price_down": 2}
    rows = sorted(findings, key=lambda f: (order[f.kind], -abs(f.extra_cost)))
    lines = [finding_line(f) for f in rows]

    extra: dict[str, float] = defaultdict(float)
    for f in findings:
        if f.kind in ("price_up", "new_charge"):
            extra[f.currency] += f.extra_cost
    ups = sum(f.kind == "price_up" for f in findings)
    fees = sum(f.kind == "new_charge" for f in findings)
    totals = ", ".join(_money(v, k) for k, v in extra.items()) or "0"
    lines.append("")
    lines.append(f"{ups} price increase(s), {fees} new charge(s). "
                 f"Extra paid on these invoices alone: {totals}.")
    return "\n".join(lines)


def supplier_drafts(findings: list[Finding], business_name: str = "[Your business]") -> dict[str, str]:
    """One draft per supplier with increases or new charges. A person reviews and sends it."""
    by_supplier: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.kind in ("price_up", "new_charge"):
            by_supplier[f.supplier].append(f)

    drafts = {}
    for supplier, items in by_supplier.items():
        bullets = []
        for f in items:
            if f.kind == "new_charge":
                bullets.append(f"- \"{f.description}\" ({_money(f.new_price, f.currency)}) appears for the "
                               f"first time on invoice {f.invoice_number}")
            else:
                bullets.append(f"- {f.description}: {_money(f.old_price or 0, f.currency)} -> "
                               f"{_money(f.new_price, f.currency)} per {f.unit} ({f.change_pct:+.1f}%)")
        drafts[supplier] = (
            f"Hi {supplier} team,\n\n"
            f"Going over our recent invoices, we noticed a few changes:\n"
            + "\n".join(bullets)
            + "\n\nCould you tell us what's behind them, and whether there's any flexibility "
              "given our regular orders?\n\nThanks,\n" + business_name
        )
    return drafts
