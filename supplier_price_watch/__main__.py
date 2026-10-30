"""CLI: python -m supplier_price_watch samples/invoices [--demo] [--history prices.csv] [--threshold 3]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import asdict
from pathlib import Path

from .extract import ClaudeExtractor, DemoExtractor
from .report import summary, supplier_drafts
from .schema import InvalidInvoice
from .watch import PriceHistory, run


def main() -> None:
    p = argparse.ArgumentParser(description="Catch supplier price increases in a folder of invoices.")
    p.add_argument("folder", help="Folder with invoices (.pdf with Claude, .txt samples with --demo)")
    p.add_argument("--demo", action="store_true", help="Use the offline sample reader (no API key)")
    p.add_argument("--history", default="prices.csv", help="Price history CSV (created if missing)")
    p.add_argument("--threshold", type=float, default=3.0,
                   help="Report changes of at least this %% (default 3)")
    p.add_argument("--drafts", action="store_true", help="Also print a draft message to each supplier")
    p.add_argument("--business", default="[Your business]", help="Name used to sign the drafts")
    p.add_argument("--webhook", help="POST findings to Make / Zapier / n8n (e.g. to email or a sheet)")
    p.add_argument("--json", action="store_true", help="Print JSON instead of a readable alert")
    args = p.parse_args()

    folder = Path(args.folder)
    use_demo = args.demo or not os.environ.get("ANTHROPIC_API_KEY")
    engine = DemoExtractor() if use_demo else ClaudeExtractor()
    patterns = ["*.txt"] if use_demo else ["*.pdf", "*.txt"]
    files = sorted(f for pat in patterns for f in folder.glob(pat))
    if not files:
        sys.exit(f"No invoices found in {folder}")

    invoices, skipped = [], []
    for f in files:
        try:
            invoices.append(engine.extract(f))
        except InvalidInvoice as e:          # never guess: skip and say so
            skipped.append(f"{f.name}: {e}")

    history = PriceHistory(Path(args.history))
    findings = run(invoices, history, args.threshold)
    history.save()

    drafts = supplier_drafts(findings, args.business) if args.drafts or args.json or args.webhook else {}
    if args.json:
        print(json.dumps({"findings": [asdict(f) | {"change_pct": f.change_pct} for f in findings],
                          "drafts": drafts, "skipped": skipped}, indent=2, ensure_ascii=False))
    else:
        engine_name = "demo" if use_demo else "claude"
        print(f"[engine: {engine_name} · {len(invoices)} invoice(s) read · history: {args.history}]\n")
        print(summary(findings))
        for supplier, text in drafts.items():
            print(f"\n--- Draft to {supplier} (review before sending) ---\n{text}")
        for s in skipped:
            print(f"\nSkipped {s}")

    if args.webhook and findings:
        req = urllib.request.Request(
            args.webhook,
            data=json.dumps({"alert": summary(findings), "drafts": drafts,
                             "findings": [asdict(f) for f in findings]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"\nWebhook responded {r.status}")


if __name__ == "__main__":
    main()
