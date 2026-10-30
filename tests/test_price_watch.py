import json
from pathlib import Path

import pytest

from supplier_price_watch.extract import ClaudeExtractor, DemoExtractor
from supplier_price_watch.redact import redact
from supplier_price_watch.report import summary, supplier_drafts
from supplier_price_watch.schema import InvalidInvoice, Invoice, LineItem, parse_model_output
from supplier_price_watch.watch import PriceHistory, run

SAMPLES = Path(__file__).parent.parent / "samples" / "invoices"


def inv(date, number, lines, supplier="Acme Foods"):
    return Invoice(supplier, number, date, "USD", [LineItem(*li) for li in lines])


def test_redaction_removes_contact_details():
    text, counts = redact("orders@acme.example, +1 (555) 010-2233, 052-123-4567, tax ID 123456789")
    assert "acme.example" not in text and "010-2233" not in text and "4567" not in text and "123456789" not in text
    assert counts["EMAIL"] == 1 and counts["PHONE"] == 2 and counts["ID"] == 1


def test_redaction_keeps_prices_and_dates():
    text, _ = redact("2026-10-02 | Bread flour 25kg | bag | 6 | 96.60")
    assert "2026-10-02" in text and "96.60" in text


def test_parse_accepts_fenced_json():
    raw = 'Sure:\n```json\n{"supplier":"A","invoice_number":"1","invoice_date":"2026-10-01","currency":"usd","lines":[{"description":"Flour","sku":null,"unit":"bag","quantity":2,"unit_price":9.5}]}\n```'
    i = parse_model_output(raw)
    assert i.currency == "USD" and i.lines[0].unit_price == 9.5 and i.lines[0].key == "desc:flour"


@pytest.mark.parametrize("raw", [
    "no json",
    '{"supplier":"A","invoice_number":"1","invoice_date":"Oct 1","lines":[{"description":"x","quantity":1,"unit_price":1}]}',
    '{"supplier":"A","invoice_number":"1","invoice_date":"2026-10-01","lines":[]}',
    '{"supplier":"A","invoice_number":"1","invoice_date":"2026-10-01","lines":[{"description":"x","quantity":"two","unit_price":1}]}',
    '{"supplier":"","invoice_number":"1","invoice_date":"2026-10-01","lines":[{"description":"x","quantity":1,"unit_price":1}]}',
])
def test_parse_rejects_bad_output(raw):
    with pytest.raises(InvalidInvoice):
        parse_model_output(raw)


def test_flags_increase_above_threshold_only():
    h = PriceHistory()
    f = run([inv("2026-09-01", "1", [("Flour", "bag", 2, 100.0, "F1"), ("Salt", "kg", 1, 10.0, "S1")]),
             inv("2026-10-01", "2", [("Flour", "bag", 2, 105.0, "F1"), ("Salt", "kg", 1, 10.2, "S1")])], h, 3.0)
    assert [(x.kind, x.description) for x in f] == [("price_up", "Flour")]
    assert f[0].change_pct == pytest.approx(5.0) and f[0].extra_cost == pytest.approx(10.0)


def test_different_units_are_never_compared():
    f = run([inv("2026-09-01", "1", [("Sugar", "kg", 1, 2.0)]),
             inv("2026-10-01", "2", [("Sugar", "sack", 1, 40.0)])], PriceHistory())
    assert f == []


def test_same_item_from_another_supplier_is_separate():
    f = run([inv("2026-09-01", "1", [("Milk", "l", 1, 1.0)], "A"),
             inv("2026-10-01", "2", [("Milk", "l", 1, 1.5)], "B")], PriceHistory())
    assert f == []


def test_new_fee_from_known_supplier_is_flagged():
    f = run([inv("2026-09-01", "1", [("Flour", "bag", 1, 50.0)]),
             inv("2026-10-01", "2", [("Flour", "bag", 1, 50.0), ("Fuel surcharge", "unit", 1, 15.0)])], PriceHistory())
    assert [(x.kind, x.description) for x in f] == [("new_charge", "Fuel surcharge")]


def test_first_invoice_from_new_supplier_raises_nothing():
    assert run([inv("2026-10-01", "1", [("Delivery fee", "unit", 1, 20.0)])], PriceHistory()) == []


def test_history_csv_round_trip_skips_seen_invoices(tmp_path):
    path = tmp_path / "prices.csv"
    h = PriceHistory(path)
    run([inv("2026-09-01", "1", [("Flour", "bag", 1, 50.0)])], h)
    h.save()
    h2 = PriceHistory(path)
    f = run([inv("2026-09-01", "1", [("Flour", "bag", 1, 50.0)]),
             inv("2026-10-01", "2", [("Flour", "bag", 1, 60.0)])], h2)
    assert [x.kind for x in f] == ["price_up"] and len(h2.rows) == 2


def test_demo_end_to_end_on_samples():
    invoices = [DemoExtractor().extract(p) for p in sorted(SAMPLES.glob("*.txt"))]
    f = run(invoices, PriceHistory())
    kinds = sorted((x.kind, x.description) for x in f)
    assert ("price_up", "Sesame seeds 1kg") in kinds and ("new_charge", "Fuel surcharge") in kinds
    assert ("price_down", "Trash bags 60L (50)") in kinds
    assert all(x.description != "Dry yeast 500g" for x in f)      # +1.6%, under the threshold
    text = summary(f)
    assert "88.60 USD" in text
    drafts = supplier_drafts(f, "Corner Bakery")
    assert set(drafts) == {"Golden Field Bakery Supply", "CleanPro Distribution"}
    assert "Trash bags" not in drafts["CleanPro Distribution"]  # decreases aren't raised with suppliers


def test_claude_engine_redacts_text_and_retries(monkeypatch):
    sent, replies = [], iter(["not json", json.dumps({"supplier": "Golden Field Bakery Supply", "invoice_number": "GF-1163",
                                                     "invoice_date": "2026-10-02", "currency": "USD",
                                                     "lines": [{"description": "Bread flour 25kg", "sku": "F-25", "unit": "bag", "quantity": 6, "unit_price": 96.6}]})])
    eng = ClaudeExtractor(api_key="test")
    monkeypatch.setattr(eng, "_request", lambda content: sent.append(content) or next(replies))
    i = eng.extract(SAMPLES / "2026-10-02_golden-field.txt")
    assert i.lines[0].unit_price == 96.6 and len(sent) == 2
    body = sent[0][0]["text"]
    assert "goldenfield.example" not in body and "010-2233" not in body and "96.60" in body


def test_claude_engine_sends_pdf_as_document(tmp_path):
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    content, removed = ClaudeExtractor(api_key="test").build_content(pdf)
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert removed == {}


def test_demo_engine_refuses_pdf(tmp_path):
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(InvalidInvoice):
        DemoExtractor().extract(pdf)
