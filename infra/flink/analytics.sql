-- CallPay real-time analytics (Flink SQL).
-- Input: Kafka topic callpay.events (every API event, enveloped with topic + ts).
-- Output 1: analytics.minute  -> revenue, paid orders, calls, failovers per 1-minute window (-> ClickHouse metrics_1m)
-- Output 2: alerts.fraud      -> callers placing more than 5 calls in 10 minutes (abuse scoring)
SET 'pipeline.name' = 'callpay-analytics';

CREATE TABLE events (
  topic STRING,
  ts BIGINT,
  total STRING,
  call_id STRING,
  caller STRING,
  event_time AS TO_TIMESTAMP_LTZ(ts, 3),
  WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'callpay.events',
  'properties.bootstrap.servers' = 'kafka:9092',
  'properties.group.id' = 'flink-analytics',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true',
  'json.fail-on-missing-field' = 'false'
);

CREATE TABLE minute_metrics (
  window_start STRING,
  revenue DOUBLE,
  paid_orders BIGINT,
  calls BIGINT,
  failovers BIGINT
) WITH (
  'connector' = 'kafka',
  'topic' = 'analytics.minute',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);

CREATE TABLE fraud_alerts (
  caller STRING,
  window_end STRING,
  calls BIGINT
) WITH (
  'connector' = 'kafka',
  'topic' = 'alerts.fraud',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);

EXECUTE STATEMENT SET BEGIN
INSERT INTO minute_metrics
SELECT
  DATE_FORMAT(window_start, 'yyyy-MM-dd HH:mm:ss'),
  SUM(CASE WHEN topic = 'payment.completed' THEN CAST(total AS DOUBLE) ELSE 0 END),
  SUM(CASE WHEN topic = 'payment.completed' THEN 1 ELSE 0 END),
  SUM(CASE WHEN topic = 'call.started' THEN 1 ELSE 0 END),
  SUM(CASE WHEN topic = 'provider.failover' THEN 1 ELSE 0 END)
FROM TABLE(TUMBLE(TABLE events, DESCRIPTOR(event_time), INTERVAL '1' MINUTE))
GROUP BY window_start, window_end;

INSERT INTO fraud_alerts
SELECT caller, DATE_FORMAT(window_end, 'yyyy-MM-dd HH:mm:ss'), COUNT(*)
FROM TABLE(HOP(TABLE events, DESCRIPTOR(event_time), INTERVAL '1' MINUTE, INTERVAL '10' MINUTE))
WHERE topic = 'call.started' AND caller IS NOT NULL
GROUP BY caller, window_start, window_end
HAVING COUNT(*) > 5;
END;
