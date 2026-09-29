-- ~19M rows: 300 sensors x 45 days x 1-minute readings, generated inside BigQuery.
-- Injected faults: S007 flatlined CO2, S042 drifting PM2.5, S099 30% missing data.
-- Floor 3 has a real PM2.5 problem during work hours.
CREATE SCHEMA IF NOT EXISTS ops;

CREATE OR REPLACE TABLE ops.readings
PARTITION BY DATE(ts)
CLUSTER BY floor, sensor_id AS
WITH sensors AS (
  SELECT CONCAT('S', LPAD(CAST(n AS STRING), 3, '0')) AS sensor_id, 1 + MOD(n, 10) AS floor
  FROM UNNEST(GENERATE_ARRAY(1, 300)) AS n
),
times AS (
  SELECT ts FROM UNNEST(GENERATE_TIMESTAMP_ARRAY(
    TIMESTAMP_SUB(TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MINUTE), INTERVAL 45 DAY),
    TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MINUTE), INTERVAL 1 MINUTE)) AS ts
),
base AS (
  SELECT s.sensor_id, s.floor, t.ts,
    EXTRACT(HOUR FROM t.ts AT TIME ZONE 'America/New_York') BETWEEN 9 AND 17
      AND EXTRACT(DAYOFWEEK FROM t.ts AT TIME ZONE 'America/New_York') BETWEEN 2 AND 6 AS work_hours,
    TIMESTAMP_DIFF(t.ts, TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 45 DAY), HOUR) / 24.0 AS day_n
  FROM sensors s CROSS JOIN times t
),
vals AS (
  SELECT *, IF(work_hours, CAST(RAND() * 40 AS INT64), CAST(RAND() * 3 AS INT64)) AS occupancy
  FROM base
)
SELECT sensor_id, floor, ts, occupancy,
  IF(sensor_id = 'S007', 412.0, 420 + occupancy * 18 + RAND() * 40) AS co2,
  IF(sensor_id = 'S099' AND RAND() < 0.3, NULL,
     6 + RAND() * 8 + IF(floor = 3 AND work_hours, 25, 0)
       + IF(sensor_id = 'S042', day_n * 0.8, 0)) AS pm25,
  10 + RAND() * 15 AS no2
FROM vals;

-- The "before" table: same data, no partitioning or clustering (how most first versions ship).
CREATE OR REPLACE TABLE ops.readings_naive AS SELECT * FROM ops.readings;
