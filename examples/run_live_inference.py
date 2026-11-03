from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.run_microstructure_backtest import build_risk_panel, make_demo_minute_bars
from lingyu_quant.live_feed import LiveFeedConfig, LiveMarketFeed
from lingyu_quant.microstructure_alpha import MicrostructureAlphaEngine
from lingyu_quant.ml_engine import NonLinearAlphaPredictor
from lingyu_quant.partitioned_storage import PartitionedParquetStorage
from lingyu_quant.risk import BarraStyleNeutralizer


DEFAULT_TICKERS = ["000408.SZ", "601069.SH", "600392.SH", "301500.SZ", "000975.SZ", "002230.SZ"]
TICKER_NAMES = {
    "000408.SZ": "藏格矿业",
    "601069.SH": "西部黄金",
    "600392.SH": "盛和资源",
    "301500.SZ": "飞南资源",
    "000975.SZ": "银泰黄金",
    "002230.SZ": "科大讯飞",
}
FEATURE_COLUMNS = [
    "vwap_accumulation",
    "pulse_penalty",
    "downside_support",
    "volume_entropy",
    "pre_close_strength",
    "smart_money_score",
    "pure_smart_money_score",
]


def load_historical_minute_bars(tickers: list[str]) -> pd.DataFrame:
    """Load minute bars from the local Hive-style Parquet lake."""

    storage = PartitionedParquetStorage()
    minute_bars = storage.load_minute_bars(tickers=tickers)
    if not minute_bars.empty:
        print(f"[+] 已从本地分钟线数据湖加载历史样本: {len(minute_bars)} 行")
        return minute_bars

    print("[!] 未发现历史分钟线分区数据，使用 demo 样本完成模型热身。")
    return make_demo_minute_bars().query("ticker in @tickers").reset_index(drop=True)


def warm_up_model(historical_minute_bars: pd.DataFrame) -> tuple[NonLinearAlphaPredictor, pd.DataFrame, pd.Series]:
    """Run the expensive pre-market feature extraction and LightGBM training once."""

    print("[*] 盘前模型热身：提取历史微观结构因子...")
    alpha_daily = MicrostructureAlphaEngine(historical_minute_bars).extract_smart_money_factors()
    risk_panel = build_risk_panel(historical_minute_bars, alpha_daily)
    risk_panel["pure_smart_money_score"] = BarraStyleNeutralizer(
        risk_panel,
        alpha_col="alpha_raw",
    ).execute_neutralization()

    features = alpha_daily[
        ["vwap_accumulation", "pulse_penalty", "downside_support", "volume_entropy", "pre_close_strength", "smart_money_score"]
    ].join(risk_panel[["pure_smart_money_score"]], how="inner")
    close = risk_panel["close"].reindex(features.index)

    predictor = NonLinearAlphaPredictor(n_estimators=120, max_depth=4, learning_rate=0.05)
    X_train, y_train = predictor.align_features_and_labels(features[FEATURE_COLUMNS], close)
    if len(X_train) < 12:
        raise RuntimeError("历史分钟线样本过少，无法完成 LightGBM 热身训练。")

    print(f"[*] 正在训练实时推理模型，训练样本: {len(X_train)} 行...")
    predictor.model.fit(X_train.to_numpy(), y_train.to_numpy())
    predictor.feature_names_ = list(X_train.columns)

    print("[+] 模型热身完成。特征贡献度:")
    for name, value in predictor.get_feature_importance().items():
        print(f"    {name:<24} {int(value)}")

    latest_close = risk_panel["close"].groupby(level="ticker").tail(1)
    metadata = risk_panel[["industry_code"]].groupby(level="ticker").tail(1)
    return predictor, metadata, latest_close


def build_live_feature_frame(
    intraday_bars: pd.DataFrame,
    metadata: pd.DataFrame,
    latest_close: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract, neutralize, and align live intraday features for model inference."""

    alpha_live = MicrostructureAlphaEngine(intraday_bars).extract_smart_money_factors()
    feature_panel = alpha_live[
        ["vwap_accumulation", "pulse_penalty", "downside_support", "volume_entropy", "pre_close_strength", "smart_money_score"]
    ].copy()

    close_now = intraday_bars.sort_values("date").groupby("ticker")["close"].last()
    close_now.index.name = "ticker"
    live_date = feature_panel.index.get_level_values("date").max()
    tickers = feature_panel.index.get_level_values("ticker")

    risk_live = pd.DataFrame(index=feature_panel.index)
    risk_live["alpha_raw"] = alpha_live["smart_money_score"]
    risk_live["close"] = [close_now.get(ticker, np.nan) for ticker in tickers]
    ref_close = latest_close.droplevel("date") if isinstance(latest_close.index, pd.MultiIndex) else latest_close
    risk_live["log_market_cap"] = [
        np.log(max(float(ref_close.get(ticker, risk_live.loc[(live_date, ticker), "close"])), 0.01) * 1_000_000)
        for ticker in tickers
    ]

    meta_by_ticker = metadata.droplevel("date") if isinstance(metadata.index, pd.MultiIndex) else metadata
    risk_live["industry_code"] = [
        str(meta_by_ticker.loc[ticker, "industry_code"]) if ticker in meta_by_ticker.index else "unknown"
        for ticker in tickers
    ]
    risk_live = risk_live.dropna(subset=["alpha_raw", "close", "log_market_cap", "industry_code"])
    risk_live["pure_smart_money_score"] = BarraStyleNeutralizer(risk_live, alpha_col="alpha_raw").execute_neutralization()

    return feature_panel.join(risk_live[["pure_smart_money_score"]], how="inner")[FEATURE_COLUMNS], alpha_live


def predict_live_alpha(predictor: NonLinearAlphaPredictor, live_features: pd.DataFrame) -> pd.Series:
    """Run one model inference pass without retraining."""

    feature_names = predictor.feature_names_ or FEATURE_COLUMNS
    X_pred = live_features.reindex(columns=feature_names).replace([np.inf, -np.inf], np.nan).dropna()
    if X_pred.empty:
        return pd.Series(dtype=float, name="win_rate")

    raw_pred = pd.Series(predictor.model.predict(X_pred.to_numpy()), index=X_pred.index, name="raw_pred")
    win_rate = raw_pred.groupby(level="date").rank(pct=True) * 100.0
    win_rate.name = "win_rate"
    return win_rate


def print_live_rank(ts: pd.Timestamp, win_rate: pd.Series, alpha_live: pd.DataFrame) -> None:
    if win_rate.empty:
        print(f"[{ts.strftime('%H:%M:%S')}] 实时推理跳过 | 有效特征不足")
        return

    entropy = alpha_live["volume_entropy"].reindex(win_rate.index)
    ranked = win_rate.sort_values(ascending=False)
    print(f"\n[{ts.strftime('%H:%M:%S')}] 实时推理完成 | 覆盖标的 {len(ranked)} 只")
    for (date, ticker), score in ranked.items():
        name = TICKER_NAMES.get(ticker, ticker)
        ent = entropy.loc[(date, ticker)]
        marker = ">>" if score >= 80 else "  "
        print(f"{marker} {name} ({ticker}) 胜率 {score:5.1f}% | 当前香农熵: {ent:.2f}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Lingyu event-driven live AI inference loop.")
    parser.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS, help="A-share tickers, e.g. 000408.SZ")
    parser.add_argument("--poll-interval", type=float, default=3.0, help="Tencent quote polling interval in seconds.")
    args = parser.parse_args()

    historical_minute_bars = load_historical_minute_bars(args.tickers)
    predictor, metadata, latest_close = warm_up_model(historical_minute_bars)

    intraday_bars_buffer: list[pd.DataFrame] = []
    feed = LiveMarketFeed(args.tickers, LiveFeedConfig(poll_interval=args.poll_interval))

    async def on_minute_bar(minute_bars: pd.DataFrame) -> None:
        if minute_bars.empty:
            return

        new_bars = minute_bars.reset_index()
        intraday_bars_buffer.append(new_bars)
        intraday_bars = pd.concat(intraday_bars_buffer, ignore_index=True)

        live_features, alpha_live = build_live_feature_frame(intraday_bars, metadata, latest_close)
        win_rate = predict_live_alpha(predictor, live_features)
        print_live_rank(pd.Timestamp(new_bars["date"].max()), win_rate, alpha_live)

    async def on_feed_error(exc: Exception) -> None:
        print(f"[!] Feed error captured by inference loop: {exc}")

    feed.on("minute_bar_closed", on_minute_bar)
    feed.on("feed_error", on_feed_error)

    print("[*] 实时 AI 推理循环启动。按 Ctrl+C 停止。")
    try:
        await feed.start()
    except KeyboardInterrupt:
        await feed.stop()
        print("\n[*] 实时 AI 推理循环已停止。")


if __name__ == "__main__":
    asyncio.run(main())
