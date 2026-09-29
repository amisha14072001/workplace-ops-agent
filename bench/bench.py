"""Before/after benchmark. Prints bytes scanned, latency and throughput for your README.

Usage: python -m bench.bench            (run from repo root, env vars set)
"""
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from google.cloud import bigquery

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
NO_CACHE = bigquery.QueryJobConfig(use_query_cache=False)

NAIVE = f"""SELECT floor, AVG(pm25) v FROM `{PROJECT}.ops.readings_naive`
            WHERE DATE(ts) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) GROUP BY floor"""
OPTIMIZED = f"""SELECT floor, AVG(pm25) v FROM `{PROJECT}.ops.readings`
                WHERE ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) GROUP BY floor"""


def run(sql, client=None):
    c = client or bigquery.Client(project=PROJECT)   # client=None reproduces BUG-5
    t = time.perf_counter()
    job = c.query(sql, job_config=NO_CACHE)
    job.result()
    return time.perf_counter() - t, job.total_bytes_processed


def load(label, sql, n=50, workers=10, shared=True):
    client = bigquery.Client(project=PROJECT) if shared else None
    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda _: run(sql, client), range(n)))
    wall = time.perf_counter() - t0
    lat = sorted(r[0] for r in res)
    gb = sum(r[1] for r in res) / 1e9
    print(f"{label:<38} p50 {statistics.median(lat):5.2f}s  p95 {lat[int(0.95 * len(lat)) - 1]:5.2f}s  "
          f"{n / wall:5.1f} q/s  {gb:8.2f} GB total")
    return gb


if __name__ == "__main__":
    print("Single query (cache off):")
    for name, sql in [("naive (no partition/cluster)", NAIVE), ("optimized", OPTIMIZED)]:
        s, b = run(sql, bigquery.Client(project=PROJECT))
        print(f"  {name:<32} {s:5.2f}s  {b / 1e6:10.1f} MB scanned")
    print("\nLoad test: 50 queries, 10 concurrent:")
    a = load("naive table + new client per call", NAIVE, shared=False)
    b = load("optimized table + shared client", OPTIMIZED)
    print(f"\nBytes scanned reduced {a / b:.0f}x  "
          f"(at $6.25/TB on-demand: ${a / 1000 * 6.25:.3f} -> ${b / 1000 * 6.25:.4f} per 50 questions)")
