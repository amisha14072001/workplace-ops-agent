# Workplace Ops Agent

A Google ADK agent that answers building air-quality and occupancy questions
("which floors had elevated PM2.5 this week?") from ~19M sensor readings in BigQuery,
deployed on Cloud Run. Data is synthetic, with injected sensor faults.

## Production bugs found and fixed (fill in from `python -m bench.bench`)

| # | Bug (v0) | Symptom | Fix | Measured result |
|---|----------|---------|-----|-----------------|
| 1 | Unpartitioned table, no time filter | Every question scans the whole table | Partition by day, cluster by floor/sensor, bounded window | ___ MB -> ___ MB per query |
| 2 | LLM-written SQL | Injection risk, wrong columns | 4 typed tools, parameterized SQL, metric whitelist | 0 free-form SQL paths |
| 3 | UTC vs building time | "This week" off by hours | Explicit building timezone | Correct day boundaries |
| 4 | Raw rows returned to the LLM | Context overflow, slow answers | Aggregate in SQL, cap at 50 rows | ___ rows -> ___ rows |
| 5 | New BigQuery client per request | Slow under load | One shared client | p95 ___s -> ___s |
| 6 | No cost ceiling | One bad query can scan TBs | maximum_bytes_billed per query | Hard 2 GB cap |
| 7 | Faulty sensors trusted | Flatlined sensor reports "good air" | Fault check before "all clear" | Caught ___/3 injected faults |

## Run
```bash
pip install -r requirements.txt
cp ops_agent/.env.example ops_agent/.env   # edit project id
adk web                                    # local chat UI
python -m bench.bench                      # before/after numbers
```
