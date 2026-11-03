from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import select
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import akshare as ak
import openai
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.run_live_inference import (  # noqa: E402
    DEFAULT_TICKERS,
    TICKER_NAMES,
    build_live_feature_frame,
    load_historical_minute_bars,
    predict_live_alpha,
    warm_up_model,
)
from lingyu_quant.live_feed import LiveFeedConfig, LiveMarketFeed  # noqa: E402


app = FastAPI(title="Lingyu Quant Streaming API", version="0.1.0")

NEWS_ANALYSIS_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
NEWS_CACHE_TTL_SECONDS = 20 * 60
NEWS_POLL_INTERVAL_SECONDS = 15
NEWS_LLM_SYSTEM_PROMPT = (
    "你是一个顶级的量化金融分析师。请分析以下A股实时快讯，提取提及的最核心股票实体，并评估其情绪。"
    "必须严格返回 JSON 格式，包含以下字段：'ticker' (如 600519.SH，若无明确股票填 '000000.XX')、"
    "'name' (股票简称，无则填 '大盘')、'summary' (一句话摘要)、'event_type' (如 政策利好、业绩超预期、"
    "资金异动等)、'sentiment_score' (从 -1.0 极度利空 到 1.0 极度利好 的浮点数)。"
)
SIM_SECTORS = [
    "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器", "食品饮料", "纺织服饰",
    "轻工制造", "医药生物", "公用事业", "交通运输", "房地产", "商贸零售", "社会服务", "非银金融",
    "银行", "传媒", "计算机", "通信", "建筑装饰", "建筑材料", "机械设备", "电力设备",
    "国防军工", "汽车", "美容护理", "煤炭", "石油石化", "环保", "综合",
]
SIM_STOCKS = [
    ("000998.SZ", "隆平高科", "农林牧渔"), ("002714.SZ", "牧原股份", "农林牧渔"),
    ("600309.SH", "万华化学", "基础化工"), ("002648.SZ", "卫星化学", "基础化工"),
    ("600019.SH", "宝钢股份", "钢铁"), ("000932.SZ", "华菱钢铁", "钢铁"),
    ("601899.SH", "紫金矿业", "有色金属"), ("600111.SH", "北方稀土", "有色金属"), ("600547.SH", "山东黄金", "有色金属"),
    ("688981.SH", "中芯国际", "电子"), ("002371.SZ", "北方华创", "电子"), ("002475.SZ", "立讯精密", "电子"),
    ("000333.SZ", "美的集团", "家用电器"), ("600690.SH", "海尔智家", "家用电器"),
    ("600519.SH", "贵州茅台", "食品饮料"), ("000858.SZ", "五粮液", "食品饮料"),
    ("600398.SH", "海澜之家", "纺织服饰"), ("603877.SH", "太平鸟", "纺织服饰"),
    ("002572.SZ", "索菲亚", "轻工制造"), ("603816.SH", "顾家家居", "轻工制造"),
    ("600276.SH", "恒瑞医药", "医药生物"), ("300760.SZ", "迈瑞医疗", "医药生物"),
    ("600900.SH", "长江电力", "公用事业"), ("600025.SH", "华能水电", "公用事业"),
    ("601919.SH", "中远海控", "交通运输"), ("601111.SH", "中国国航", "交通运输"),
    ("000002.SZ", "万科A", "房地产"), ("600048.SH", "保利发展", "房地产"),
    ("600729.SH", "重庆百货", "商贸零售"), ("002024.SZ", "ST易购", "商贸零售"),
    ("601888.SH", "中国中免", "社会服务"), ("600754.SH", "锦江酒店", "社会服务"),
    ("601318.SH", "中国平安", "非银金融"), ("600030.SH", "中信证券", "非银金融"),
    ("000001.SZ", "平安银行", "银行"), ("600036.SH", "招商银行", "银行"),
    ("300251.SZ", "光线传媒", "传媒"), ("002027.SZ", "分众传媒", "传媒"),
    ("002230.SZ", "科大讯飞", "计算机"), ("688111.SH", "金山办公", "计算机"), ("300059.SZ", "东方财富", "计算机"),
    ("000063.SZ", "中兴通讯", "通信"), ("600050.SH", "中国联通", "通信"), ("300308.SZ", "中际旭创", "通信"),
    ("601668.SH", "中国建筑", "建筑装饰"), ("601390.SH", "中国中铁", "建筑装饰"),
    ("600585.SH", "海螺水泥", "建筑材料"), ("000786.SZ", "北新建材", "建筑材料"),
    ("300124.SZ", "汇川技术", "机械设备"), ("601766.SH", "中国中车", "机械设备"),
    ("300750.SZ", "宁德时代", "电力设备"), ("601012.SH", "隆基绿能", "电力设备"), ("300014.SZ", "亿纬锂能", "电力设备"),
    ("600150.SH", "中国船舶", "国防军工"), ("600760.SH", "中航沈飞", "国防军工"),
    ("002594.SZ", "比亚迪", "汽车"), ("601633.SH", "长城汽车", "汽车"),
    ("300957.SZ", "贝泰妮", "美容护理"), ("603605.SH", "珀莱雅", "美容护理"),
    ("601088.SH", "中国神华", "煤炭"), ("600188.SH", "兖矿能源", "煤炭"),
    ("601857.SH", "中国石油", "石油石化"), ("600028.SH", "中国石化", "石油石化"),
    ("300070.SZ", "碧水源", "环保"), ("600323.SH", "瀚蓝环境", "环保"),
    ("600673.SH", "东阳光", "综合"), ("000009.SZ", "中国宝安", "综合"),
]
SIM_TRIGGERS = ["量价背离", "VWAP吸筹", "成交熵抬升", "尾盘确认", "订单簿失衡", "政策脉冲", "资金回流"]
FFD_MCP_CONFIG_PATH = Path.home() / ".ffd" / "mcp-config.json"
FFD_REALTIME_POLL_SECONDS = 20

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LiveInferenceSession:
    """One WebSocket-scoped live inference pipeline."""

    def __init__(self, websocket: WebSocket, tickers: list[str], poll_interval: float = 3.0) -> None:
        self.websocket = websocket
        self.tickers = tickers
        self.poll_interval = poll_interval
        self.feed = LiveMarketFeed(tickers, LiveFeedConfig(poll_interval=poll_interval))
        self.intraday_bars_buffer: list[pd.DataFrame] = []
        self.send_lock = asyncio.Lock()
        self.feed_task: asyncio.Task[None] | None = None
        self.is_closed = False
        self.predictor = None
        self.metadata = None
        self.latest_close = None
        self.top_feature = "unknown"

    async def run(self) -> None:
        await self.websocket.accept()
        await self._send_json(
            {
                "type": "system_status",
                "message": "model_warmup_started",
                "system_status": {"feed": "warming_up", "memory_bars": 0},
            }
        )

        await self._warm_up()
        await self._send_json(
            {
                "type": "system_status",
                "message": "model_warmup_completed",
                "top_feature": self.top_feature,
                "system_status": {"feed": "starting", "memory_bars": 0},
            }
        )

        self.feed.on("minute_bar_closed", self._on_minute_bar)
        self.feed.on("feed_error", self._on_feed_error)
        self.feed_task = asyncio.create_task(self.feed.start())

        try:
            while True:
                # Keep the socket lifecycle tied to the browser tab. The client
                # may send pings or small control messages; the feed task does
                # the actual market polling work.
                await self.websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        await self.feed.stop()
        if self.feed_task:
            self.feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.feed_task
        self.feed.off("minute_bar_closed", self._on_minute_bar)
        self.feed.off("feed_error", self._on_feed_error)
        self.intraday_bars_buffer.clear()

    async def _warm_up(self) -> None:
        historical = await asyncio.to_thread(load_historical_minute_bars, self.tickers)
        predictor, metadata, latest_close = await asyncio.to_thread(warm_up_model, historical)
        self.predictor = predictor
        self.metadata = metadata
        self.latest_close = latest_close
        importance = predictor.get_feature_importance()
        self.top_feature = str(importance.index[0]) if not importance.empty else "unknown"

    async def _on_minute_bar(self, minute_bars: pd.DataFrame) -> None:
        if self.is_closed or minute_bars.empty:
            return

        new_bars = minute_bars.reset_index()
        self.intraday_bars_buffer.append(new_bars)
        intraday_bars = pd.concat(self.intraday_bars_buffer, ignore_index=True)

        live_features, alpha_live = await asyncio.to_thread(
            build_live_feature_frame,
            intraday_bars,
            self.metadata,
            self.latest_close,
        )
        win_rate = await asyncio.to_thread(predict_live_alpha, self.predictor, live_features)
        payload = self._build_inference_payload(new_bars, win_rate, alpha_live)
        await self._send_json(payload)

    async def _on_feed_error(self, exc: Exception) -> None:
        if self.is_closed:
            return
        await self._send_json(
            {
                "type": "system_status",
                "message": "feed_error",
                "error": str(exc),
                "system_status": {"feed": "degraded", "memory_bars": len(self.intraday_bars_buffer)},
            }
        )

    def _build_inference_payload(
        self,
        new_bars: pd.DataFrame,
        win_rate: pd.Series,
        alpha_live: pd.DataFrame,
    ) -> dict[str, Any]:
        ts = pd.Timestamp(new_bars["date"].max())
        predictions = []
        entropy = alpha_live["volume_entropy"].reindex(win_rate.index) if not win_rate.empty else pd.Series(dtype=float)
        vwap = alpha_live["vwap_accumulation"].reindex(win_rate.index) if not win_rate.empty else pd.Series(dtype=float)

        for (date, ticker), score in win_rate.sort_values(ascending=False).items():
            predictions.append(
                {
                    "ticker": ticker,
                    "name": TICKER_NAMES.get(ticker, ticker),
                    "score": round(float(score) / 100.0, 4),
                    "win_rate_pct": round(float(score), 2),
                    "top_feature": self.top_feature,
                    "volume_entropy": round(float(entropy.loc[(date, ticker)]), 4),
                    "vwap_accumulation": round(float(vwap.loc[(date, ticker)]), 6),
                }
            )

        return {
            "type": "inference_update",
            "timestamp": ts.strftime("%H:%M:%S"),
            "predictions": predictions,
            "system_status": {
                "feed": "active",
                "memory_bars": len(self.intraday_bars_buffer),
                "tickers": len(self.tickers),
            },
        }

    async def _send_json(self, data: dict[str, Any]) -> None:
        if self.is_closed:
            return
        try:
            async with self.send_lock:
                await self.websocket.send_json(data)
        except WebSocketDisconnect:
            self.is_closed = True
        except RuntimeError:
            self.is_closed = True


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _mcp_write(proc: subprocess.Popen, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    proc.stdin.write(b"Content-Length: " + str(len(body)).encode("utf-8") + b"\r\n\r\n" + body)
    proc.stdin.flush()


def _mcp_read(proc: subprocess.Popen, timeout: float = 60) -> dict[str, Any]:
    deadline = time.time() + timeout
    header = b""
    while b"\r\n\r\n" not in header:
        if time.time() > deadline:
            raise TimeoutError("timeout waiting for MCP header")
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if not ready:
            continue
        chunk = proc.stdout.read(1)
        if not chunk:
            raise EOFError("MCP server stdout closed")
        header += chunk

    headers, rest = header.split(b"\r\n\r\n", 1)
    content_length = None
    for line in headers.decode("utf-8").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise RuntimeError("MCP response missing Content-Length")

    body = rest
    while len(body) < content_length:
        if time.time() > deadline:
            raise TimeoutError("timeout waiting for MCP body")
        body += proc.stdout.read(content_length - len(body))
    return json.loads(body[:content_length])


def _call_ffd_tool_sync(tool_name: str, arguments: dict[str, Any], timeout: float = 90) -> dict[str, Any]:
    config = json.loads(FFD_MCP_CONFIG_PATH.read_text(encoding="utf-8"))["mcpServers"]["ffd"]
    env = os.environ.copy()
    env.update(config.get("env", {}))
    proc = subprocess.Popen(
        [config["command"], *config.get("args", [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        bufsize=0,
    )
    try:
        _mcp_write(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lingyu-backend", "version": "0.1"},
                },
            },
        )
        _mcp_read(proc, timeout=timeout)
        _mcp_write(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _mcp_write(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        response = _mcp_read(proc, timeout=timeout)
        if "error" in response:
            raise RuntimeError(response["error"])
        content = response.get("result", {}).get("content", [])
        text = content[0].get("text", "{}") if content else "{}"
        return json.loads(text)
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
        if proc.poll() is None:
            proc.kill()


def _fetch_ffd_realtime_quotes() -> list[dict[str, Any]]:
    codes = ",".join(ticker for ticker, _, _ in SIM_STOCKS)
    payload = _call_ffd_tool_sync(
        "ffd_query",
        {
            "function": "realtime_quote",
            "codes": codes,
            "indicators": "latest;changeRatio;volume;amount",
            "format": "json",
            "output_mode": "both",
        },
        timeout=90,
    )
    data = payload.get("data", {})
    codes_data = data.get("code", [])
    meta = {ticker: {"name": name, "sector": sector} for ticker, name, sector in SIM_STOCKS}
    rows = []
    for index, ticker in enumerate(codes_data):
        info = meta.get(ticker, {"name": ticker, "sector": "综合"})
        rows.append(
            {
                "ticker": ticker,
                "name": info["name"],
                "sector": info["sector"],
                "time": data.get("time", [None] * len(codes_data))[index],
                "latest": float(data.get("latest", [0] * len(codes_data))[index] or 0),
                "changeRatio": float(data.get("changeRatio", [0] * len(codes_data))[index] or 0),
                "volume": float(data.get("volume", [0] * len(codes_data))[index] or 0),
                "amount": float(data.get("amount", [0] * len(codes_data))[index] or 0),
            }
        )
    return rows


def _fetch_ffd_sector_money_flow_optional() -> tuple[list[dict[str, Any]] | None, str]:
    try:
        payload = _call_ffd_tool_sync(
            "ffd_sector_money_flow",
            {
                "query": "今日行业板块主力资金净流入排名",
                "format": "json",
                "output_mode": "both",
                "limit": 31,
            },
            timeout=90,
        )
    except Exception as exc:
        return None, f"sector_money_flow_unavailable:{type(exc).__name__}"

    if payload.get("code") and int(payload.get("code")) != 200:
        return None, f"sector_money_flow_rejected:{payload.get('error_code') or payload.get('code')}"

    raw_rows = payload.get("data") or payload.get("rows") or payload.get("result") or []
    if isinstance(raw_rows, dict):
        if all(isinstance(value, list) for value in raw_rows.values()):
            keys = list(raw_rows)
            raw_rows = [dict(zip(keys, values)) for values in zip(*[raw_rows[key] for key in keys])]
        else:
            raw_rows = raw_rows.get("rows") or raw_rows.get("data") or []
    if not isinstance(raw_rows, list) or not raw_rows:
        return None, "sector_money_flow_empty"

    normalized = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        sector = row.get("industry") or row.get("sector") or row.get("板块") or row.get("行业") or row.get("name") or row.get("名称")
        if not sector:
            continue
        change_pct = row.get("change_pct") or row.get("pct_chg") or row.get("涨跌幅") or row.get("changeRatio") or 0
        net_inflow = (
            row.get("main_net_inflow")
            or row.get("net_inflow")
            or row.get("主力净流入")
            or row.get("净流入")
            or row.get("main_net_amount")
            or 0
        )
        try:
            net_yi = float(net_inflow) / 100_000_000 if abs(float(net_inflow)) > 10_000 else float(net_inflow)
        except Exception:
            net_yi = 0.0
        normalized.append(
            {
                "sector": str(sector),
                "change_pct": round(float(change_pct), 2),
                "net_inflow": round(net_yi, 2),
                "alpha": round(max(0, min(100, 50 + float(change_pct) * 8 + max(-20, min(20, net_yi / 2)))), 0),
            }
        )
    return (normalized or None), "ffd_sector_money_flow"


def _build_realtime_alpha_payload(
    rows: list[dict[str, Any]],
    sector_money_flow: list[dict[str, Any]] | None = None,
    market_source: str = "ffd_realtime_quote_sector_proxy",
) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("FFD realtime quote returned no rows")

    changes = [row["changeRatio"] for row in rows]
    amounts = [row["amount"] for row in rows]
    mean_change = statistics.fmean(changes)
    stdev_change = statistics.pstdev(changes) or 1.0
    ranked_amounts = sorted(amounts)
    max_amount = max(amounts) or 1.0

    factor_matrix = []
    for row in rows:
        liquidity_rank = ranked_amounts.index(row["amount"]) / max(len(ranked_amounts) - 1, 1)
        alpha_z = (row["changeRatio"] - mean_change) / stdev_change + (liquidity_rank - 0.5) * 0.35
        win_rate = max(3, min(97, 50 + alpha_z * 12))
        factor_matrix.append(
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "alpha_z": round(alpha_z, 2),
                "win_rate": round(win_rate, 1),
                "volume_entropy": round(3.2 + min(row["amount"] / max_amount, 1.0) * 2.2, 2),
                "vwap_accumulation": round(row["changeRatio"] / 100.0, 4),
                "top_feature": "realtime_quote",
                "latest": row["latest"],
                "change_pct": row["changeRatio"],
                "amount": row["amount"],
                "quote_time": row["time"],
            }
        )
    factor_matrix.sort(key=lambda item: item["alpha_z"], reverse=True)

    if sector_money_flow:
        by_name = {row["sector"]: row for row in sector_money_flow}
        market_panorama = [by_name[sector] for sector in SIM_SECTORS if sector in by_name]
        for row in sector_money_flow:
            if row["sector"] not in SIM_SECTORS:
                market_panorama.append(row)
        market_source = "ffd_sector_money_flow"
    else:
        by_sector: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_sector.setdefault(row["sector"], []).append(row)
        market_panorama = []
        for sector in SIM_SECTORS:
            members = by_sector.get(sector, [])
            if members:
                change_pct = statistics.fmean(item["changeRatio"] for item in members)
                turnover_yi = sum(item["amount"] for item in members) / 100_000_000
                alpha = max(0, min(100, 50 + change_pct * 8))
            else:
                change_pct = 0.0
                turnover_yi = 0.0
                alpha = 50
            market_panorama.append(
                {
                    "sector": sector,
                    "change_pct": round(change_pct, 2),
                    "net_inflow": round(turnover_yi, 2),
                    "alpha": round(alpha, 0),
                }
            )

    top = factor_matrix[0]
    timestamp = str(top.get("quote_time") or pd.Timestamp.now().strftime("%H:%M:%S"))
    stable_event_key = f"{timestamp}-{top['ticker']}-{top['change_pct']:.2f}-{top['alpha_z']:.2f}"
    alpha_stream = {
        "id": stable_event_key,
        "timestamp": timestamp[-8:] if len(timestamp) >= 8 else timestamp,
        "sector": next((row["sector"] for row in rows if row["ticker"] == top["ticker"]), "实时行情"),
        "event_type": "FFD实时行情",
        "summary": f"{top['name']} 实时涨跌幅 {top['change_pct']:+.2f}%，Alpha Z {top['alpha_z']:.2f}",
        "ticker": top["ticker"],
        "name": top["name"],
        "score": top["win_rate"],
    }

    return {
        "type": "ffd_realtime_pulse",
        "timestamp": timestamp,
        "market_panorama": market_panorama,
        "factor_matrix": factor_matrix,
        "alpha_stream": alpha_stream,
        "system_status": {"feed": "OPEN", "mode": "ffd_realtime_quote", "symbols": len(factor_matrix), "market_data_source": market_source},
    }


@app.websocket("/ws/inference")
async def inference_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {
                    "type": "inference_status",
                    "timestamp": pd.Timestamp.now().strftime("%H:%M:%S"),
                    "system_status": {"feed": "FETCHING", "mode": "ffd_realtime_quote", "symbols": len(SIM_STOCKS)},
                }
            )
            sector_money_flow, market_source = await asyncio.to_thread(_fetch_ffd_sector_money_flow_optional)
            rows = await asyncio.to_thread(_fetch_ffd_realtime_quotes)
            await websocket.send_json(_build_realtime_alpha_payload(rows, sector_money_flow, market_source))
            await asyncio.sleep(FFD_REALTIME_POLL_SECONDS)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "inference_error",
                    "timestamp": pd.Timestamp.now().strftime("%H:%M:%S"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "system_status": {"feed": "ERROR", "mode": "ffd_realtime_quote"},
                }
            )
    except RuntimeError:
        pass


def _normalize_news_text(news_text: str) -> str:
    return " ".join(str(news_text or "").strip().split())


def _news_cache_key(news_text: str) -> str:
    return _normalize_news_text(news_text)[:220]


def _prune_news_cache() -> None:
    now = time.monotonic()
    expired = [key for key, (ts, _) in NEWS_ANALYSIS_CACHE.items() if now - ts > NEWS_CACHE_TTL_SECONDS]
    for key in expired:
        NEWS_ANALYSIS_CACHE.pop(key, None)


async def analyze_news_with_llm(news_text: str) -> dict[str, Any] | None:
    """Analyze one A-share news item with an OpenAI-compatible LLM."""

    normalized_text = _normalize_news_text(news_text)
    if not normalized_text:
        return None

    _prune_news_cache()
    cache_key = _news_cache_key(normalized_text)
    cached = NEWS_ANALYSIS_CACHE.get(cache_key)
    if cached:
        return cached[1]

    started_at = time.perf_counter()
    client = openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "your_api_key"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "deepseek-chat"),
                response_format={"type": "json_object"},
                temperature=0.1,
                messages=[
                    {"role": "system", "content": NEWS_LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": normalized_text},
                ],
            ),
            timeout=20,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        sentiment = max(-1.0, min(1.0, float(parsed.get("sentiment_score", 0))))
        result = {
            "type": "llm_news_event",
            "ticker": str(parsed.get("ticker") or "000000.XX"),
            "name": str(parsed.get("name") or "大盘"),
            "summary": str(parsed.get("summary") or normalized_text[:120]),
            "event_type": str(parsed.get("event_type") or "实时快讯"),
            "sentiment_score": round(sentiment, 3),
            "llm_latency_ms": round((time.perf_counter() - started_at) * 1000),
            "raw_text": normalized_text,
        }
        NEWS_ANALYSIS_CACHE[cache_key] = (time.monotonic(), result)
        return result
    except Exception as exc:
        print(f"[-] LLM news analysis failed: {type(exc).__name__}: {exc}")
        NEWS_ANALYSIS_CACHE[cache_key] = (time.monotonic(), None)
        return None


def _pick_first_existing(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        if column in row and pd.notna(row[column]):
            value = _normalize_news_text(str(row[column]))
            if value:
                return value
    return ""


def _fetch_latest_a_share_news(limit: int = 3) -> list[dict[str, str]]:
    """Fetch latest A-share news from AkShare with interface-name fallbacks."""

    fetchers = []
    if hasattr(ak, "stock_info_a_cls_news"):
        fetchers.append(("stock_info_a_cls_news", lambda: ak.stock_info_a_cls_news()))
    if hasattr(ak, "stock_info_global_cls"):
        fetchers.append(("stock_info_global_cls", lambda: ak.stock_info_global_cls(symbol="全部")))
    if hasattr(ak, "stock_info_global_em"):
        fetchers.append(("stock_info_global_em", lambda: ak.stock_info_global_em()))

    last_error: Exception | None = None
    for source, fetcher in fetchers:
        try:
            df = fetcher()
            if df is None or df.empty:
                continue
            records = []
            sample_df = df.tail(limit).iloc[::-1] if source == "stock_info_global_cls" else df.head(limit)
            for _, row in sample_df.iterrows():
                title = _pick_first_existing(row, ["标题", "title", "新闻标题", "内容", "摘要"])
                content = _pick_first_existing(row, ["内容", "摘要", "summary", "新闻内容", "详情"])
                timestamp = _pick_first_existing(row, ["发布时间", "时间", "date", "datetime", "发布日期"])
                text = _normalize_news_text(f"{title} {content}") if content and content != title else title
                if text:
                    records.append({"source": source, "timestamp": timestamp, "text": text})
            if records:
                return records
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    return []


@app.websocket("/ws/news")
async def news_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    processed_news: set[str] = set()
    try:
        await websocket.send_json(
            {
                "type": "news_status",
                "message": "real_news_stream_started",
                "timestamp": pd.Timestamp.now().strftime("%H:%M:%S"),
            }
        )
        while True:
            try:
                latest_news = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_latest_a_share_news, 3),
                    timeout=12,
                )
            except Exception as exc:
                await websocket.send_json(
                    {
                        "type": "news_status",
                        "message": "akshare_fetch_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "timestamp": pd.Timestamp.now().strftime("%H:%M:%S"),
                    }
                )
                await asyncio.sleep(NEWS_POLL_INTERVAL_SECONDS)
                continue

            for item in latest_news:
                key = _news_cache_key(item["text"])
                if not key or key in processed_news:
                    continue
                processed_news.add(key)

                analysis = await analyze_news_with_llm(item["text"])
                if not analysis:
                    continue

                analysis.update(
                    {
                        "id": f"{int(time.time() * 1000)}-{len(processed_news)}",
                        "timestamp": pd.Timestamp.now().strftime("%H:%M:%S"),
                        "news_source": item["source"],
                        "source_timestamp": item.get("timestamp") or "",
                    }
                )
                await websocket.send_json(analysis)

            await asyncio.sleep(NEWS_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except RuntimeError:
        pass
