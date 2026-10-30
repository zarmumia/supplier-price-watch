"""Read a supplier invoice into an Invoice.

Two engines:
- `ClaudeExtractor` calls the Anthropic Messages API (set ANTHROPIC_API_KEY).
  Text invoices are redacted before sending. PDFs are sent as documents, so
  only use it on PDFs you are comfortable sending to the API.
- `DemoExtractor` reads the simple pipe-table format used in `samples/`, so the
  project runs and is testable without an API key. It is NOT meant for real invoices.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .redact import redact
from .schema import InvalidInvoice, Invoice, LineItem, parse_model_output

PROMPT = """You read supplier invoices for a small business that wants to catch price increases.
Return ONLY a JSON object with:
- "supplier": the supplier's business name
- "invoice_number": as printed
- "invoice_date": YYYY-MM-DD
- "currency": ISO code such as USD, EUR, GBP, ILS
- "lines": one object per billed line, each with
    "description" (as printed), "sku" (product code if printed, else null),
    "unit" (bag, kg, box, case, hour...; "unit" if none), "quantity" (number),
    "unit_price" (number, price per one unit before tax)
Include fees and surcharges (delivery, fuel, handling) as lines too.
Skip subtotal, tax and total rows. Do not invent lines or numbers that are not on the invoice."""

RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


class ClaudeExtractor:
    def __init__(self, api_key: str | None = None, model: str | None = None, max_retries: int = 2,
                 network_retries: int = 3, backoff: float = 1.0, sleep=time.sleep):
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.max_retries = max_retries          # re-asks when the model returns invalid JSON
        self.network_retries = network_retries  # retries for timeouts, rate limits and 5xx
        self.backoff = backoff
        self._sleep = sleep

    def build_content(self, path: Path) -> tuple[list[dict], dict[str, int]]:
        """The message content for one invoice, and what was redacted from it."""
        if path.suffix.lower() == ".pdf":
            pdf = base64.standard_b64encode(path.read_bytes()).decode()
            return [
                {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
                {"type": "text", "text": PROMPT},
            ], {}
        safe, removed = redact(path.read_text(encoding="utf-8"))
        return [{"type": "text", "text": f"{PROMPT}\n\nInvoice:\n{safe}"}], removed

    def _call(self, content: list[dict]) -> str:
        for attempt in range(self.network_retries + 1):
            try:
                return self._request(content)
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE_STATUS or attempt == self.network_retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.network_retries:
                    raise
            self._sleep(self.backoff * 2 ** attempt)
        raise RuntimeError("unreachable")

    def _request(self, content: list[dict]) -> str:
        body = {"model": self.model, "max_tokens": 2000, "messages": [{"role": "user", "content": content}]}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
        return "".join(block.get("text", "") for block in data["content"])

    def extract(self, path: Path) -> Invoice:
        content, _ = self.build_content(path)
        last_error: InvalidInvoice | None = None
        for _ in range(self.max_retries + 1):
            try:
                return parse_model_output(self._call(content))
            except InvalidInvoice as e:   # invalid output: ask again
                last_error = e
        assert last_error is not None
        raise last_error


class DemoExtractor:
    """Parses the sample format: KEY: value header lines, then a pipe table of items."""

    def extract(self, path: Path) -> Invoice:
        if path.suffix.lower() != ".txt":
            raise InvalidInvoice(f"the demo engine only reads .txt samples, not {path.name}")
        header: dict[str, str] = {}
        lines: list[LineItem] = []
        in_items = False
        for raw in path.read_text(encoding="utf-8").splitlines():
            row = raw.strip()
            if not row:
                continue
            if row.upper().startswith("ITEMS"):
                in_items = True
                continue
            if in_items and "|" in row:
                cells = [c.strip() for c in row.split("|")]
                if len(cells) != 5 or cells[0].lower() == "sku":
                    continue
                sku, desc, unit, qty, price = cells
                try:
                    lines.append(LineItem(desc, unit or "unit", float(qty), float(price), sku or None))
                except ValueError as e:
                    raise InvalidInvoice(f"{path.name}: bad number in '{row}'") from e
            elif ":" in row and not in_items:
                k, v = row.split(":", 1)
                header[k.strip().lower()] = v.strip()
            elif in_items and row.upper().startswith(("SUBTOTAL", "TAX", "TOTAL")):
                break
        payload = {
            "supplier": header.get("supplier", ""),
            "invoice_number": header.get("invoice", ""),
            "invoice_date": header.get("date", ""),
            "currency": header.get("currency", ""),
            "lines": [{"description": li.description, "sku": li.sku, "unit": li.unit,
                       "quantity": li.quantity, "unit_price": li.unit_price} for li in lines],
        }
        return parse_model_output(json.dumps(payload))   # same validation as the model path
