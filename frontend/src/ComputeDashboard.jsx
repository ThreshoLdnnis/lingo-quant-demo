import React, { useEffect, useMemo, useRef, useState } from 'react';
import './ComputeDashboard.css';

const ECHARTS_CDN = 'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js';
const WS_URL = 'ws://127.0.0.1:8000/ws/inference';
const FEATURE_ORDER = [
  'vwap_accumulation',
  'volume_entropy',
  'downside_support',
  'pre_close_strength',
  'pulse_penalty',
  'pure_smart_money_score',
  'smart_money_score',
];

function loadECharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${ECHARTS_CDN}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve(window.echarts), { once: true });
      existing.addEventListener('error', reject, { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = ECHARTS_CDN;
    script.async = true;
    script.onload = () => resolve(window.echarts);
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

function formatLog(timestamp, prediction) {
  return `[${timestamp}] 推理完成 -> ${prediction.ticker} 胜率 ${Number(prediction.win_rate_pct ?? 0).toFixed(1)}% | 核心驱动: ${prediction.top_feature || 'unknown'}`;
}

function computeFeatureBars(predictions) {
  const bars = Object.fromEntries(FEATURE_ORDER.map((feature) => [feature, 0]));
  predictions.forEach((prediction) => {
    const topFeature = prediction.top_feature;
    if (topFeature && bars[topFeature] !== undefined) {
      bars[topFeature] += Math.max(8, Number(prediction.win_rate_pct || 0));
    }
    if (bars.vwap_accumulation !== undefined) {
      bars.vwap_accumulation += Math.abs(Number(prediction.vwap_accumulation || 0)) * 10000;
    }
    if (bars.volume_entropy !== undefined) {
      bars.volume_entropy += Number(prediction.volume_entropy || 0) * 6;
    }
  });
  return FEATURE_ORDER.map((feature) => ({ feature, value: Number(bars[feature].toFixed(2)) }));
}

export default function ComputeDashboard() {
  const wsRef = useRef(null);
  const chartRef = useRef(null);
  const chartInstanceRef = useRef(null);
  const [connectionState, setConnectionState] = useState('connecting');
  const [systemStatus, setSystemStatus] = useState({ feed: 'connecting', memory_bars: 0, tickers: 0 });
  const [predictions, setPredictions] = useState([]);
  const [featureBars, setFeatureBars] = useState(FEATURE_ORDER.map((feature) => ({ feature, value: 0 })));
  const [inferenceLogs, setInferenceLogs] = useState([]);
  const [lastTimestamp, setLastTimestamp] = useState('--:--:--');
  const [errorText, setErrorText] = useState('');

  const topPrediction = predictions[0];
  const isActive = systemStatus.feed === 'active' && connectionState === 'open';

  useEffect(() => {
    let disposed = false;
    loadECharts()
      .then((echarts) => {
        if (disposed || !chartRef.current) return;
        chartInstanceRef.current = chartInstanceRef.current || echarts.init(chartRef.current);
        chartInstanceRef.current.setOption(buildChartOption(featureBars, topPrediction?.top_feature));
      })
      .catch(() => setErrorText('ECharts 加载失败'));

    const onResize = () => chartInstanceRef.current?.resize();
    window.addEventListener('resize', onResize);
    return () => {
      disposed = true;
      window.removeEventListener('resize', onResize);
      chartInstanceRef.current?.dispose();
      chartInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartInstanceRef.current?.setOption(buildChartOption(featureBars, topPrediction?.top_feature), true);
  }, [featureBars, topPrediction?.top_feature]);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState('open');
      setSystemStatus((prev) => ({ ...prev, feed: 'warming_up' }));
      setInferenceLogs((prev) => [`[${new Date().toLocaleTimeString()}] WebSocket 已连接，等待模型热身`, ...prev].slice(0, 50));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.system_status) {
          setSystemStatus((prev) => ({ ...prev, ...msg.system_status }));
        }

        if (msg.type === 'system_status') {
          setInferenceLogs((prev) => [`[${new Date().toLocaleTimeString()}] ${msg.message || '系统状态更新'}`, ...prev].slice(0, 50));
        }

        if (msg.type === 'inference_update') {
          const nextPredictions = Array.isArray(msg.predictions) ? msg.predictions : [];
          setPredictions(nextPredictions);
          setLastTimestamp(msg.timestamp || '--:--:--');
          setFeatureBars(computeFeatureBars(nextPredictions));
          setInferenceLogs((prev) => {
            const nextLogs = nextPredictions.map((prediction) => formatLog(msg.timestamp, prediction));
            return [...nextLogs, ...prev].slice(0, 50);
          });
        }
      } catch (error) {
        setErrorText(`消息解析失败: ${error.message}`);
      }
    };

    ws.onerror = () => {
      setConnectionState('error');
      setErrorText('WebSocket 连接异常，请确认 FastAPI 服务已启动');
    };

    ws.onclose = () => {
      setConnectionState('closed');
      setSystemStatus((prev) => ({ ...prev, feed: prev.feed === 'active' ? 'closed' : prev.feed }));
      setInferenceLogs((prev) => [`[${new Date().toLocaleTimeString()}] WebSocket 已关闭`, ...prev].slice(0, 50));
    };

    return () => {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, 'ComputeDashboard unmounted');
      }
      wsRef.current = null;
    };
  }, []);

  return (
    <section className="compute-dashboard view-shell">
      <div className="compute-head">
        <div>
          <span className="eyebrow">LIVE AI INFERENCE</span>
          <h2>实时推理计算中心</h2>
        </div>
        <div className="compute-status-grid">
          <StatusPill label="连接" value={connectionState} active={connectionState === 'open'} />
          <StatusPill label="系统状态" value={systemStatus.feed || 'unknown'} active={isActive} />
          <StatusPill label="内存聚合池" value={`${systemStatus.memory_bars ?? 0} bars`} active={isActive} />
          <StatusPill label="最新切片" value={lastTimestamp} active={isActive} />
        </div>
      </div>

      {errorText && <div className="compute-error">{errorText}</div>}

      <div className="compute-grid">
        <section className="compute-card chart-card">
          <div className="compute-card-head">
            <div>
              <strong>特征归因</strong>
              <span>Feature Importance / Live Driver</span>
            </div>
            <span className={isActive ? 'heartbeat active' : 'heartbeat'} />
          </div>
          <div ref={chartRef} className="feature-chart" />
        </section>

        <section className="compute-card terminal-card">
          <div className="compute-card-head">
            <div>
              <strong>Live Inference Feed</strong>
              <span>最近 50 条推理日志</span>
            </div>
            <span>{predictions.length} symbols</span>
          </div>
          <div className="inference-log-list">
            {inferenceLogs.length ? (
              inferenceLogs.map((log, index) => <div key={`${log}-${index}`} className={index === 0 ? 'fresh log-line' : 'log-line'}>{log}</div>)
            ) : (
              <div className="log-empty">等待后端推理流...</div>
            )}
          </div>
        </section>
      </div>

      <section className="compute-card prediction-card">
        <div className="compute-card-head">
          <div>
            <strong>实时胜率排名</strong>
            <span>LightGBM Cross-Sectional Ranking</span>
          </div>
        </div>
        <div className="prediction-table">
          <div className="prediction-row header">
            <span>代码</span><span>名称</span><span>胜率</span><span>核心驱动</span><span>香农熵</span><span>VWAP偏离</span>
          </div>
          {predictions.map((prediction) => (
            <div className="prediction-row" key={prediction.ticker}>
              <span className="mono">{prediction.ticker}</span>
              <span>{prediction.name || prediction.ticker}</span>
              <strong>{Number(prediction.win_rate_pct ?? 0).toFixed(1)}%</strong>
              <span>{prediction.top_feature || 'unknown'}</span>
              <span>{Number(prediction.volume_entropy ?? 0).toFixed(2)}</span>
              <span>{Number(prediction.vwap_accumulation ?? 0).toFixed(5)}</span>
            </div>
          ))}
          {!predictions.length && <div className="prediction-empty">暂无推理结果</div>}
        </div>
      </section>
    </section>
  );
}

function StatusPill({ label, value, active }) {
  return (
    <div className="status-pill">
      <span className={active ? 'status-dot active' : 'status-dot'} />
      <small>{label}</small>
      <b>{value}</b>
    </div>
  );
}

function buildChartOption(featureBars, topFeature) {
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 138, right: 24, top: 24, bottom: 24 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#dce5ef' } },
      axisLabel: { color: '#68788f' },
    },
    yAxis: {
      type: 'category',
      data: featureBars.map((item) => item.feature),
      axisLabel: { color: '#172033', fontSize: 11 },
      axisTick: { show: false },
    },
    series: [
      {
        name: 'live contribution',
        type: 'bar',
        data: featureBars.map((item) => ({
          value: item.value,
          itemStyle: { color: item.feature === topFeature ? '#07885f' : '#5f4cc7' },
        })),
        barWidth: 14,
        label: { show: true, position: 'right', color: '#172033', formatter: ({ value }) => Number(value).toFixed(1) },
      },
    ],
  };
}
