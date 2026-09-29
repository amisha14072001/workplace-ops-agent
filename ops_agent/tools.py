"""BigQuery tools for the Workplace Ops Agent. Each fix is tagged FIX-n (see README)."""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

from google.cloud import bigquery

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
TABLE = os.getenv("READINGS_TABLE", f"{PROJECT}.ops.readings")
TZ = ZoneInfo(os.getenv("BUILDING_TZ", "America/New_York"))   # FIX-3: explicit building timezone
LIMITS = {"pm25": 35.0, "co2": 1000.0, "no2": 53.0}          # FIX-2: whitelist, never raw SQL
MAX_DAYS = 31
MAX_ROWS = 50                                                 # FIX-4: bounded output to the LLM

_client = bigquery.Client(project=PROJECT)                    # FIX-5: one client, reused


def _window(days: int):
    days = max(1, min(int(days), MAX_DAYS))                   # FIX-1: always a bounded time window
    end = dt.datetime.now(TZ)
    return end - dt.timedelta(days=days), end


def _metric(metric: str) -> str:
    m = metric.lower().replace(".", "").replace("_", "")
    if m not in LIMITS:
        raise ValueError(f"metric must be one of {list(LIMITS)}")
    return m


def _run(sql: str, params: list) -> dict:
    cfg = bigquery.QueryJobConfig(
        query_parameters=params,
        maximum_bytes_billed=2 * 10**9,                       # FIX-6: cost guardrail per query
    )
    job = _client.query(sql, job_config=cfg)
    rows = [dict(r) for r in job.result(timeout=30)]
    return {
        "rows": json.loads(json.dumps(rows[:MAX_ROWS], default=str)),
        "truncated": len(rows) > MAX_ROWS,
        "bytes_scanned": job.total_bytes_processed,
    }


def _ts_params(start, end):
    return [bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", end)]


def floors_over_limit(metric: str, days: int = 7) -> dict:
    """Find floors where the hourly average of a metric (pm25, co2, no2) went above its limit.

    Args:
        metric: one of pm25, co2, no2.
        days: look-back window in days (1-31). "This week" = 7.
    """
    m = _metric(metric)
    start, end = _window(days)
    sql = f"""
      WITH hourly AS (
        SELECT floor, TIMESTAMP_TRUNC(ts, HOUR) h, AVG({m}) v
        FROM `{TABLE}` WHERE ts BETWEEN @start AND @end
        GROUP BY floor, h)
      SELECT floor, COUNTIF(v > @limit) hours_over_limit, ROUND(MAX(v), 1) worst_hourly_avg
      FROM hourly GROUP BY floor HAVING hours_over_limit > 0 ORDER BY hours_over_limit DESC"""
    out = _run(sql, _ts_params(start, end) + [bigquery.ScalarQueryParameter("limit", "FLOAT64", LIMITS[m])])
    out.update(metric=m, limit=LIMITS[m], window=f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} {TZ}")
    return out


def compare_floors(metric: str, floor_a: int, floor_b: int, days: int = 7) -> dict:
    """Compare daily averages of a metric between two floors.

    Args:
        metric: one of pm25, co2, no2.
        floor_a: first floor number.
        floor_b: second floor number.
        days: look-back window in days (1-31).
    """
    m = _metric(metric)
    start, end = _window(days)
    sql = f"""
      SELECT DATE(ts, @tz) day, floor, ROUND(AVG({m}), 1) avg_value
      FROM `{TABLE}` WHERE ts BETWEEN @start AND @end AND floor IN (@a, @b)
      GROUP BY day, floor ORDER BY day, floor"""
    params = _ts_params(start, end) + [
        bigquery.ScalarQueryParameter("a", "INT64", floor_a),
        bigquery.ScalarQueryParameter("b", "INT64", floor_b),
        bigquery.ScalarQueryParameter("tz", "STRING", str(TZ))]
    out = _run(sql, params)
    out.update(metric=m, limit=LIMITS[m])
    return out


def current_floor_status(floor: int) -> dict:
    """Latest 15-minute CO2, PM2.5 and occupancy for one floor (is it stuffy right now?).

    Args:
        floor: floor number.
    """
    end = dt.datetime.now(TZ)
    sql = f"""
      SELECT floor, ROUND(AVG(co2)) co2_ppm, ROUND(AVG(pm25), 1) pm25, SUM(occupancy) people_counted,
             COUNT(DISTINCT sensor_id) sensors_reporting
      FROM `{TABLE}` WHERE ts BETWEEN @start AND @end AND floor = @f GROUP BY floor"""
    out = _run(sql, _ts_params(end - dt.timedelta(minutes=15), end)
               + [bigquery.ScalarQueryParameter("f", "INT64", floor)])
    out.update(limits=LIMITS)
    return out


def find_faulty_sensors(days: int = 3) -> dict:
    """Detect broken sensors: flatlined CO2, missing PM2.5 data, or drifting PM2.5.

    Args:
        days: look-back window in days (2-31).
    """
    start, end = _window(max(2, days))
    sql = f"""
      WITH s AS (
        SELECT sensor_id, floor,
          STDDEV(co2) co2_std,
          SAFE_DIVIDE(COUNTIF(pm25 IS NULL), COUNT(*)) pm25_missing_rate,
          AVG(IF(ts > TIMESTAMP_SUB(@end, INTERVAL 1 DAY), pm25, NULL))
            - AVG(IF(ts < TIMESTAMP_ADD(@start, INTERVAL 1 DAY), pm25, NULL)) pm25_shift
        FROM `{TABLE}` WHERE ts BETWEEN @start AND @end GROUP BY sensor_id, floor)
      SELECT sensor_id, floor,
        CASE WHEN co2_std < 1 THEN 'flatlined CO2'
             WHEN pm25_missing_rate > 0.1 THEN 'missing PM2.5 data'
             ELSE 'drifting PM2.5' END issue,
        ROUND(co2_std, 2) co2_std, ROUND(pm25_missing_rate, 2) pm25_missing_rate, ROUND(pm25_shift, 1) pm25_shift
      FROM s WHERE co2_std < 1 OR pm25_missing_rate > 0.1 OR pm25_shift > 1.5
      ORDER BY sensor_id"""
    return _run(sql, _ts_params(start, end))
