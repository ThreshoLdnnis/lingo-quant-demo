"""Lingyu Quant System package with lazy public exports."""

from importlib import import_module

_EXPORTS = {
    "AlphaEngine": ("lingyu_quant.alpha", "AlphaEngine"),
    "AsyncFetchConfig": ("lingyu_quant.async_fetcher", "AsyncFetchConfig"),
    "AsyncMinuteBarFetcher": ("lingyu_quant.async_fetcher", "AsyncMinuteBarFetcher"),
    "BacktestConfig": ("lingyu_quant.backtester", "BacktestConfig"),
    "ExecutionPerformance": ("lingyu_quant.execution_engine", "ExecutionPerformance"),
    "FetchStats": ("lingyu_quant.async_fetcher", "FetchStats"),
    "LiveFeedConfig": ("lingyu_quant.live_feed", "LiveFeedConfig"),
    "LiveMarketFeed": ("lingyu_quant.live_feed", "LiveMarketFeed"),
    "LocalParquetStorage": ("lingyu_quant.storage", "LocalParquetStorage"),
    "MicrostructureAlphaEngine": ("lingyu_quant.microstructure_alpha", "MicrostructureAlphaEngine"),
    "MockDataFetcher": ("lingyu_quant.data_fetcher", "MockDataFetcher"),
    "NonLinearAlphaPredictor": ("lingyu_quant.ml_engine", "NonLinearAlphaPredictor"),
    "PartitionedParquetStorage": ("lingyu_quant.partitioned_storage", "PartitionedParquetStorage"),
    "VectorizedBacktester": ("lingyu_quant.backtester", "VectorizedBacktester"),
    "VWAPExecutionEngine": ("lingyu_quant.execution_engine", "VWAPExecutionEngine"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
