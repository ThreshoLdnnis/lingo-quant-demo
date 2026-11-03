import asyncio
from datetime import datetime

import pandas as pd

from lingyu_quant.live_feed import LiveMarketFeed


def quote_line(code, price, volume_lots, amount_10k):
    fields = [""] * 50
    fields[3] = str(price)
    fields[30] = "20260621103103"
    fields[36] = str(volume_lots)
    fields[37] = str(amount_10k)
    return f'v_{code}="' + "~".join(fields) + '";'


def test_tencent_quote_parser_normalizes_snapshot_fields():
    feed = LiveMarketFeed(["000408.SZ", "601069.SH"])
    raw = quote_line("sz000408", 12.34, 123, 456.7) + quote_line("sh601069", 23.45, 200, 1200)

    snapshots = feed._parse_tencent_quote(raw)

    assert snapshots == [
        {
            "ticker": "000408.SZ",
            "price": 12.34,
            "volume_total": 12_300,
            "amount_total": 4_567_000.0,
            "quote_time": "20260621103103",
        },
        {
            "ticker": "601069.SH",
            "price": 23.45,
            "volume_total": 20_000,
            "amount_total": 12_000_000.0,
            "quote_time": "20260621103103",
        },
    ]


def test_minute_boundary_emits_closed_bar_with_incremental_volume():
    asyncio.run(_run_minute_boundary_case())


async def _run_minute_boundary_case():
    moments = iter(
        [
            datetime(2026, 6, 21, 10, 30, 3),
            datetime(2026, 6, 21, 10, 30, 33),
            datetime(2026, 6, 21, 10, 31, 1),
        ]
    )
    feed = LiveMarketFeed(["000408.SZ"], now_provider=lambda: next(moments))
    emitted = []
    feed.on("minute_bar_closed", emitted.append)

    await feed._aggregate_and_check_boundary(
        [{"ticker": "000408.SZ", "price": 10.0, "volume_total": 1000, "amount_total": 10_000.0}]
    )
    await feed._aggregate_and_check_boundary(
        [{"ticker": "000408.SZ", "price": 10.5, "volume_total": 1300, "amount_total": 13_200.0}]
    )
    await feed._aggregate_and_check_boundary(
        [{"ticker": "000408.SZ", "price": 10.4, "volume_total": 1500, "amount_total": 15_300.0}]
    )

    assert len(emitted) == 1
    closed = emitted[0]
    assert isinstance(closed, pd.DataFrame)
    row = closed.iloc[0]
    assert closed.index.names == ["date", "ticker"]
    assert row["open"] == 10.0
    assert row["high"] == 10.5
    assert row["low"] == 10.0
    assert row["close"] == 10.5
    assert row["volume"] == 300
    assert row["amount"] == 3200.0
    assert row["snapshot_count"] == 2


def test_fetch_snapshot_emits_error_and_survives_network_failure():
    asyncio.run(_run_fetch_error_case())


async def _run_fetch_error_case():
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("HTTP 502")

    feed = LiveMarketFeed(["000408.SZ"])
    errors = []
    feed.on("feed_error", errors.append)

    snapshots = await feed._fetch_snapshot(BrokenSession())

    assert snapshots == []
    assert len(errors) == 1
    assert "HTTP 502" in str(errors[0])
