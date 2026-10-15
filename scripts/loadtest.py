"""Burst load test: N concurrent clients hammering the heavy endpoints. Usage: python scripts/loadtest.py http://host:port [concurrency] [seconds]"""
import asyncio, sys, time, statistics
from pathlib import Path
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 50
SECS = int(sys.argv[3]) if len(sys.argv) > 3 else 20
ROOT = Path(__file__).resolve().parent.parent
XML = (ROOT / "tests/fixtures/invoice/Standard_invoice_Extensive.xml").read_bytes()
CSV = (ROOT / "tests/fixtures/sample.csv").read_bytes() if (ROOT / "tests/fixtures/sample.csv").exists() else None
XLSX = next(iter((ROOT / "tests/private_data").glob("*.xlsx")), None)
XLSX_B = XLSX.read_bytes() if XLSX else None


async def worker(client, stats, stop):
    i = 0
    while time.time() < stop:
        i += 1
        t = time.perf_counter()
        try:
            if XLSX_B is not None and i % 5 == 0:
                r = await client.post("/api/readiness", files={"file": (XLSX.name, XLSX_B)})
                kind = "xlsx"
            elif CSV is not None and i % 2 == 0:
                r = await client.post("/api/readiness", files={"file": ("s.csv", CSV)})
                kind = "csv"
            else:
                r = await client.post("/api/validate-xml", content=XML, headers={"Content-Type": "application/xml"})
                kind = "xml"
            stats.append((kind, r.status_code, time.perf_counter() - t))
        except Exception as e:
            stats.append(("err", type(e).__name__, time.perf_counter() - t))


async def main():
    stats = []
    stop = time.time() + SECS
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as client:
        await asyncio.gather(*(worker(client, stats, stop) for _ in range(CONC)))
    by = {}
    for kind, code, dt in stats:
        by.setdefault((kind, code), []).append(dt)
    print(f"{len(stats)} requests in {SECS}s with {CONC} concurrent clients = {len(stats)/SECS:.1f} req/s")
    for (kind, code), ds in sorted(by.items(), key=lambda x: str(x[0])):
        ds.sort()
        p50 = ds[len(ds)//2]; p95 = ds[int(len(ds)*0.95)-1] if len(ds) > 1 else ds[0]
        print(f"  {kind:5s} {str(code):>4s}  n={len(ds):5d}  p50={p50*1000:7.0f}ms  p95={p95*1000:7.0f}ms  max={max(ds)*1000:7.0f}ms")

asyncio.run(main())
