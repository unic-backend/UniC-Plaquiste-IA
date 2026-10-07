"""Mesure locale : temps de réponse (p50/p95) des routes principales sur une base de test remplie.

Usage : cd backend && python ../scripts/bench.py [nombre_de_requêtes=30]
Aucune IA n'est appelée. Les chiffres dépendent de la machine : comparer avant/après sur la même machine.
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
import uuid

os.environ["UNIC_DATA_DIR"] = tempfile.mkdtemp(prefix="unic-bench-")
os.environ["UNIC_NO_BACKGROUND"] = "1"
sys.path.insert(0, os.getcwd())

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Customer, Invoice, InvoiceItem, Quotation, QuotationItem  # noqa: E402

ROUTES = ["/api/ping", "/api/health/ready", "/api/customers", "/api/materials", "/api/quotes", "/api/invoices",
          "/api/projects", "/api/briefing", "/api/unpaid", "/api/export/invoices.csv", "/api/conversations"]


def seed(n: int = 300) -> None:
    db = SessionLocal()
    try:
        c = Customer(code="B-" + uuid.uuid4().hex[:6], name="Client Bench")
        db.add(c)
        db.flush()
        for i in range(n):
            q = Quotation(number=f"BQ-{i}-{uuid.uuid4().hex[:5]}", customer_id=c.id, subtotal=1000.0, total=1180.0, currency="FCFA")
            q.items = [QuotationItem(position=k, description=f"Ligne {k}", quantity=2, unit="u", unit_price=50.0, total=100.0) for k in range(1, 9)]
            inv = Invoice(number=f"BI-{i}-{uuid.uuid4().hex[:5]}", customer_id=c.id, status="approved", subtotal=1000.0, total=1180.0,
                          remaining=1180.0, currency="FCFA")
            inv.items = [InvoiceItem(position=k, description=f"Ligne {k}", quantity=2, unit="u", unit_price=50.0, total=100.0) for k in range(1, 9)]
            db.add_all([q, inv])
        db.commit()
    finally:
        db.close()


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    with TestClient(app) as client:
        seed()
        print(f"{'route':32} {'état':>5} {'p50 ms':>8} {'p95 ms':>8} {'octets':>9}")
        for path in ROUTES:
            times, size, status = [], 0, 0
            for _ in range(n):
                t = time.perf_counter()
                r = client.get(path)
                times.append((time.perf_counter() - t) * 1000)
                size, status = len(r.content), r.status_code
            times.sort()
            print(f"{path:32} {status:>5} {statistics.median(times):8.1f} {times[int(len(times) * 0.95) - 1]:8.1f} {size:9d}")


if __name__ == "__main__":
    main()
