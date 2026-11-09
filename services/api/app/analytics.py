"""Analytics + the "Ask your business" Analyst sub-agent.

Pipeline: API -> Kafka topic `callpay.events` -> (a) ClickHouse Kafka-engine table -> `events`
                                               -> (b) Flink SQL job -> `analytics.minute` -> ClickHouse `metrics_1m`
Query side: ClickHouse first; if it's down, the same metrics are computed from Postgres/SQLite rows.

The Analyst never writes SQL from an LLM. The LLM (or keyword rules if no LLM) only picks a metric
from a fixed catalog plus a time window; code runs the query. No injection surface, no hallucinated numbers.
"""

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select

from .db import Call, Order, Payout, ProviderEvent
from .providers.chain import AllProvidersFailed
from .providers.llm import ChatMessage

log = logging.getLogger("callpay.analytics")

METRICS = {
    "revenue": "Total revenue from paid orders",
    "orders": "Number of paid orders",
    "avg_order": "Average paid order value",
    "busiest_hour": "Hour of day with the most paid orders",
    "top_items": "Best-selling menu items",
    "missed_calls": "Calls that ended without payment (abandoned) and how many were recovered",
    "conversion": "Share of calls that turned into a paid order",
    "payouts": "Money paid out to crew",
    "failovers": "Provider failovers (which AI/payment providers failed over)",
}
WINDOWS = {"today": 1, "week": 7, "month": 30, "all": 3650}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS events (
        ts DateTime64(3, 'UTC'), topic LowCardinality(String), order_id String, call_id String,
        amount Decimal(12, 2), provider String, payload String
    ) ENGINE = MergeTree ORDER BY (topic, ts)""",
    """CREATE TABLE IF NOT EXISTS metrics_1m (
        window_start DateTime64(3, 'UTC'), revenue Decimal(12, 2), paid_orders UInt64,
        calls UInt64, failovers UInt64
    ) ENGINE = ReplacingMergeTree ORDER BY window_start""",
]




def kafka_schema(broker: str) -> list[str]:
    """Kafka engine tables: ClickHouse consumes the event stream itself (no code in the data path)."""
    return [
        f"""CREATE TABLE IF NOT EXISTS events_queue (raw String) ENGINE = Kafka SETTINGS
            kafka_broker_list = '{broker}', kafka_topic_list = 'callpay.events',
            kafka_group_name = 'clickhouse-events', kafka_format = 'JSONAsString'""",
        """CREATE MATERIALIZED VIEW IF NOT EXISTS events_mv TO events AS SELECT
            fromUnixTimestamp64Milli(JSONExtractInt(raw, 'ts'), 'UTC') AS ts,
            JSONExtractString(raw, 'topic') AS topic,
            JSONExtractString(raw, 'order_id') AS order_id,
            JSONExtractString(raw, 'call_id') AS call_id,
            toDecimal64OrZero(JSONExtractString(raw, 'total'), 2) AS amount,
            if(JSONExtractString(raw, 'from_provider') != '', JSONExtractString(raw, 'from_provider'), JSONExtractString(raw, 'provider')) AS provider,
            raw AS payload
        FROM events_queue""",
        f"""CREATE TABLE IF NOT EXISTS metrics_queue (raw String) ENGINE = Kafka SETTINGS
            kafka_broker_list = '{broker}', kafka_topic_list = 'analytics.minute',
            kafka_group_name = 'clickhouse-metrics', kafka_format = 'JSONAsString'""",
        """CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_mv TO metrics_1m AS SELECT
            parseDateTime64BestEffort(JSONExtractString(raw, 'window_start'), 3, 'UTC') AS window_start,
            toDecimal64OrZero(toString(JSONExtractFloat(raw, 'revenue')), 2) AS revenue,
            JSONExtractUInt(raw, 'paid_orders') AS paid_orders,
            JSONExtractUInt(raw, 'calls') AS calls,
            JSONExtractUInt(raw, 'failovers') AS failovers
        FROM metrics_queue""",
    ]


class ClickHouse:
    def __init__(self, url: str, user: str, password: str, http: httpx.AsyncClient):
        self.url, self.auth, self.http = url.rstrip("/"), (user, password), http
        self.ok = False

    async def query(self, sql: str, fmt: bool = True) -> list[dict]:
        r = await self.http.post(
            self.url, params={"database": "callpay"}, auth=self.auth,
            content=sql + (" FORMAT JSON" if fmt else ""), timeout=10,
        )
        r.raise_for_status()
        return r.json()["data"] if fmt else []

    async def start(self, kafka_broker: str = "") -> bool:
        """Create tables. Returns True if ClickHouse is consuming Kafka directly."""
        if not self.url:
            return False
        try:
            for stmt in SCHEMA:
                await self.query(stmt, fmt=False)
            self.ok = True
            if kafka_broker:
                for stmt in kafka_schema(kafka_broker):
                    await self.query(stmt, fmt=False)
                return True
        except Exception as e:  # noqa: BLE001
            log.warning("ClickHouse unavailable (%s); analytics will use the main database", e)
        return False


class Analytics:
    def __init__(self, ch: ClickHouse, db, llm_chain=None):
        self.ch, self.db, self.llm = ch, db, llm_chain
        self.kafka_feeds_clickhouse = False  # set when the Kafka engine table exists (see infra/clickhouse)

    @property
    def backend(self) -> str:
        return "clickhouse" if self.ch.ok else "database"

    async def record(self, topic: str, payload: dict, bus_backend: str = "memory") -> None:
        """Direct insert used only when Kafka is NOT feeding ClickHouse (event bus fell back to memory)."""
        if not self.ch.ok or (self.kafka_feeds_clickhouse and bus_backend == "kafka"):
            return
        row = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "topic": topic,
            "order_id": str(payload.get("order_id") or ""), "call_id": str(payload.get("call_id") or ""),
            "amount": str(payload.get("total") or "0"), "provider": str(payload.get("from_provider") or payload.get("provider") or ""),
            "payload": json.dumps(payload, default=str),
        }
        try:
            await self.ch.query("INSERT INTO events FORMAT JSONEachRow " + json.dumps(row), fmt=False)
        except Exception as e:  # noqa: BLE001
            log.warning("ClickHouse insert failed (%s)", e)

    # ---------------- metrics ----------------
    async def metric(self, name: str, window: str) -> dict:
        days = WINDOWS.get(window, 7)
        if self.ch.ok:
            try:
                return await self._ch_metric(name, days)
            except Exception as e:  # noqa: BLE001
                log.warning("ClickHouse query failed (%s); falling back to database", e)
        return await self._db_metric(name, days)

    async def _ch_metric(self, name: str, days: int) -> dict:
        w = f"ts >= now() - INTERVAL {int(days)} DAY"
        q = self.ch.query
        if name in ("revenue", "orders", "avg_order"):
            r = (await q(f"SELECT sum(amount) AS revenue, count() AS orders FROM events WHERE topic='payment.completed' AND {w}"))[0]
            rev, n = Decimal(str(r["revenue"] or 0)), int(r["orders"])
            return {"revenue": f"{rev:.2f}", "orders": n, "avg_order": f"{(rev / n if n else 0):.2f}", "source": "clickhouse"}
        if name == "busiest_hour":
            rows = await q(f"SELECT toHour(ts) AS hour, count() AS orders FROM events WHERE topic='payment.completed' AND {w} GROUP BY hour ORDER BY orders DESC LIMIT 24")
            return {"by_hour": [{"hour": int(r["hour"]), "orders": int(r["orders"])} for r in rows], "source": "clickhouse"}
        if name in ("missed_calls", "conversion"):
            rows = await q(f"SELECT topic, count() AS n FROM events WHERE topic IN ('call.started','call.abandoned','recovery.sent','payment.completed') AND {w} GROUP BY topic")
            c = {r["topic"]: int(r["n"]) for r in rows}
            return self._calls_out(c.get("call.started", 0), c.get("call.abandoned", 0), c.get("recovery.sent", 0), c.get("payment.completed", 0), "clickhouse")
        if name == "payouts":
            r = (await q(f"SELECT sum(amount) AS total, count() AS n FROM events WHERE topic='payout.sent' AND {w}"))[0]
            return {"paid_out": f"{Decimal(str(r['total'] or 0)):.2f}", "batches": int(r["n"]), "source": "clickhouse"}
        if name == "failovers":
            rows = await q(f"SELECT provider, count() AS n FROM events WHERE topic='provider.failover' AND {w} GROUP BY provider ORDER BY n DESC")
            return {"failovers": [{"provider": r["provider"], "count": int(r["n"])} for r in rows], "source": "clickhouse"}
        return await self._db_metric(name, days)  # top_items needs order line items -> main DB

    @staticmethod
    def _calls_out(calls: int, abandoned: int, recovered: int, paid: int, source: str) -> dict:
        return {"calls": calls, "abandoned": abandoned, "recovery_texts": recovered, "paid_orders": paid,
                "conversion_pct": round(100 * paid / calls, 1) if calls else 0.0, "source": source}

    async def _db_metric(self, name: str, days: int) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.db.session() as s:
            orders = [o for o in (await s.execute(select(Order).where(Order.created_at >= since))).scalars()
                      if o.status in ("paid", "preparing", "ready")]
            if name in ("revenue", "orders", "avg_order"):
                rev = sum((o.total for o in orders), Decimal("0"))
                return {"revenue": f"{rev:.2f}", "orders": len(orders), "avg_order": f"{(rev / len(orders) if orders else 0):.2f}", "source": "database"}
            if name == "busiest_hour":
                c = Counter((o.paid_at or o.created_at).hour for o in orders)
                return {"by_hour": [{"hour": h, "orders": n} for h, n in c.most_common()], "source": "database"}
            if name == "top_items":
                c: Counter = Counter()
                for o in orders:
                    for i in o.items:
                        if i["name"] == "Crew tip":
                            continue
                        c[i["name"]] += int(i["quantity"])
                return {"top_items": [{"item": k, "quantity": v} for k, v in c.most_common(10)], "source": "database"}
            if name in ("missed_calls", "conversion"):
                calls = list((await s.execute(select(Call).where(Call.started_at >= since))).scalars())
                return self._calls_out(len(calls), sum(c.status in ("abandoned", "recovered") for c in calls),
                                       sum(c.status == "recovered" for c in calls), sum(1 for c in calls if c.state.get("stage") == "done"), "database")
            if name == "payouts":
                ps = [p for p in (await s.execute(select(Payout).where(Payout.created_at >= since))).scalars() if p.status in ("sent", "completed")]
                return {"paid_out": f"{sum((p.total for p in ps), Decimal('0')):.2f}", "batches": len(ps), "source": "database"}
            if name == "failovers":
                evs = (await s.execute(select(ProviderEvent).where(ProviderEvent.created_at >= since))).scalars()
                c = Counter(e.from_provider for e in evs)
                return {"failovers": [{"provider": k, "count": v} for k, v in c.most_common()], "source": "database"}
        raise ValueError(f"unknown metric {name}")

    async def timeseries(self, minutes: int = 60) -> list[dict]:
        """Revenue per minute: Flink output table first, raw events second, main DB last."""
        if self.ch.ok:
            try:
                rows = await self.ch.query(
                    f"SELECT window_start AS t, max(revenue) AS revenue, max(paid_orders) AS orders FROM metrics_1m "
                    f"WHERE window_start >= now() - INTERVAL {int(minutes)} MINUTE GROUP BY t ORDER BY t")
                if not rows:
                    rows = await self.ch.query(
                        f"SELECT toStartOfMinute(ts) AS t, sum(amount) AS revenue, count() AS orders FROM events "
                        f"WHERE topic='payment.completed' AND ts >= now() - INTERVAL {int(minutes)} MINUTE GROUP BY t ORDER BY t")
                return [{"t": str(r["t"]), "revenue": str(r["revenue"]), "orders": int(r["orders"])} for r in rows]
            except Exception as e:  # noqa: BLE001
                log.warning("timeseries from ClickHouse failed (%s)", e)
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        async with self.db.session() as s:
            buckets: dict[str, list] = {}
            for o in (await s.execute(select(Order).where(Order.paid_at.is_not(None), Order.paid_at >= since))).scalars():
                k = o.paid_at.replace(second=0, microsecond=0).isoformat()
                b = buckets.setdefault(k, [Decimal("0"), 0])
                b[0] += o.total
                b[1] += 1
        return [{"t": k, "revenue": f"{v[0]:.2f}", "orders": v[1]} for k, v in sorted(buckets.items())]

    # ---------------- Analyst sub-agent ----------------
    def _route_rules(self, q: str) -> tuple[str, str]:
        ql = q.lower()
        window = "today" if "today" in ql else "month" if "month" in ql else "all" if ("ever" in ql or "all time" in ql) else "week"
        rules = [
            (r"busiest|peak|what time|which hour", "busiest_hour"), (r"best.?sell|popular|top item|most ordered", "top_items"),
            (r"missed|abandon|recover|hung up", "missed_calls"), (r"conversion|convert", "conversion"),
            (r"payout|paid (the )?crew|staff|tips", "payouts"), (r"failover|outage|provider|down", "failovers"),
            (r"average|avg|typical order", "avg_order"), (r"how many orders|number of orders|orders", "orders"),
        ]
        for rx, m in rules:
            if re.search(rx, ql):
                return m, window
        return "revenue", window

    async def ask(self, question: str) -> dict:
        metric, window = self._route_rules(question)
        used = None
        if self.llm is not None:
            catalog = "\n".join(f"- {k}: {v}" for k, v in METRICS.items())
            system = ("You route a small-business owner's question to ONE metric. Reply ONLY JSON "
                      '{"metric": name, "window": one of today|week|month|all}.\nMetrics:\n' + catalog)
            try:
                text, used = await asyncio.wait_for(
                    self.llm.call(lambda p: p.complete(system, [ChatMessage("user", question[:300])], 60)), timeout=12)
                m = re.search(r"\{.*?\}", text, re.S)
                d = json.loads(m.group(0)) if m else {}
                if d.get("metric") in METRICS:
                    metric = d["metric"]
                if d.get("window") in WINDOWS:
                    window = d["window"]
            except (AllProvidersFailed, asyncio.TimeoutError, json.JSONDecodeError, AttributeError):
                used = None
        data = await self.metric(metric, window)
        return {"question": question, "metric": metric, "window": window, "answer": self._phrase(metric, window, data),
                "data": data, "llm": used}

    @staticmethod
    def _phrase(metric: str, window: str, d: dict) -> str:
        span = {"today": "today", "week": "in the last 7 days", "month": "in the last 30 days", "all": "all time"}[window]
        if metric in ("revenue", "orders", "avg_order"):
            return f"You made ${d['revenue']} from {d['orders']} paid orders {span} (average ${d['avg_order']})."
        if metric == "busiest_hour":
            if not d["by_hour"]:
                return f"No paid orders {span} yet."
            h = d["by_hour"][0]
            return f"Your busiest hour {span} is {h['hour']:02d}:00 UTC with {h['orders']} paid orders."
        if metric == "top_items":
            top = d["top_items"][:3]
            return ("Best sellers " + span + ": " + ", ".join(f"{t['item']} ({t['quantity']})" for t in top) + ".") if top else f"No sales {span} yet."
        if metric in ("missed_calls", "conversion"):
            return (f"{d['calls']} calls {span}: {d['paid_orders']} paid ({d['conversion_pct']}% conversion), "
                    f"{d['abandoned']} abandoned, {d['recovery_texts']} recovered by text.")
        if metric == "payouts":
            return f"You paid your crew ${d['paid_out']} across {d['batches']} payouts {span}."
        if metric == "failovers":
            if not d["failovers"]:
                return f"No provider failovers {span}. Everything stayed on the primary providers."
            return "Failovers " + span + ": " + ", ".join(f"{f['provider']} x{f['count']}" for f in d["failovers"]) + ". Every call kept going on a backup."
        return json.dumps(d)
