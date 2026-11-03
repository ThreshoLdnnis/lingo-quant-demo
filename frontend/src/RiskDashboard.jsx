import React, { useEffect, useMemo, useRef, useState } from 'react';
import './RiskDashboard.css';

const ECHARTS_CDN = 'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js';

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

const styleExposure = [
  { name: '市值 Size', value: 0.03 },
  { name: '动量 Momentum', value: 0.18 },
  { name: '波动率 Volatility', value: 0.34 },
  { name: '流动性 Liquidity', value: 0.41 },
  { name: '价值 Value', value: -0.08 },
];

const industryDeviation = [
  ['算力', 4.8],
  ['半导体', 3.2],
  ['黄金', 2.4],
  ['有色', 1.7],
  ['数据要素', 1.1],
  ['电力', -0.9],
  ['消费电子', -1.5],
  ['银行', -2.1],
  ['医药', -2.7],
  ['白酒', -3.4],
];

export default function RiskDashboard() {
  const radarRef = useRef(null);
  const barRef = useRef(null);
  const radarInstanceRef = useRef(null);
  const barInstanceRef = useRef(null);
  const [ready, setReady] = useState(false);

  const riskMetrics = useMemo(() => [
    ['投资组合风险预算', '15.0%', '年化波动控制'],
    ['主动暴露度', '82.4%', 'Alpha 组合差异度'],
    ['Beta 敞口', '0.05', '高度市场中性'],
  ], []);

  useEffect(() => {
    let disposed = false;
    loadECharts().then((echarts) => {
      if (disposed) return;
      if (radarRef.current) radarInstanceRef.current = echarts.init(radarRef.current);
      if (barRef.current) barInstanceRef.current = echarts.init(barRef.current);
      setReady(true);
    });

    const onResize = () => {
      radarInstanceRef.current?.resize();
      barInstanceRef.current?.resize();
    };
    window.addEventListener('resize', onResize);
    return () => {
      disposed = true;
      window.removeEventListener('resize', onResize);
      radarInstanceRef.current?.dispose();
      barInstanceRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    radarInstanceRef.current?.setOption({
      backgroundColor: 'transparent',
      tooltip: {},
      radar: {
        radius: '64%',
        indicator: styleExposure.map((item) => ({ name: item.name, min: -0.6, max: 0.6 })),
        axisName: { color: '#24344d', fontSize: 11 },
        splitLine: { lineStyle: { color: '#d6e1ef' } },
        splitArea: { areaStyle: { color: ['#f8fbff', '#eef4fa'] } },
        axisLine: { lineStyle: { color: '#cbd7e6' } },
      },
      series: [{
        type: 'radar',
        data: [{
          value: styleExposure.map((item) => item.value),
          name: 'Style Exposure',
          areaStyle: { color: 'rgba(95,76,199,0.18)' },
          lineStyle: { color: '#5f4cc7', width: 2 },
          itemStyle: { color: '#07885f' },
        }],
      }],
    });

    barInstanceRef.current?.setOption({
      backgroundColor: 'transparent',
      grid: { left: 86, right: 28, top: 18, bottom: 26 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${v}%` },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#68788f', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#dce5ef' } },
      },
      yAxis: {
        type: 'category',
        data: industryDeviation.map(([name]) => name),
        axisLabel: { color: '#172033' },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: industryDeviation.map(([, value]) => ({
          value,
          itemStyle: { color: value >= 0 ? '#c7374d' : '#07885f' },
        })),
        barWidth: 14,
        label: { show: true, position: 'right', formatter: ({ value }) => `${value > 0 ? '+' : ''}${value}%`, color: '#172033' },
      }],
    });
  }, [ready]);

  return (
    <section className="risk-dashboard view-shell">
      <div className="risk-head">
        <div>
          <span className="eyebrow">BARRA RISK CONTROL</span>
          <h2>Barra 风险监控大屏</h2>
        </div>
        <div className="risk-metric-grid">
          {riskMetrics.map(([label, value, sub]) => (
            <div className="risk-metric" key={label}>
              <small>{label}</small>
              <strong>{value}</strong>
              <span>{sub}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="risk-grid">
        <section className="risk-card">
          <div className="risk-card-head">
            <strong>Style Exposure</strong>
            <span>市值中性，流动性/波动率轻微主动暴露</span>
          </div>
          <div ref={radarRef} className="risk-chart" />
        </section>

        <section className="risk-card">
          <div className="risk-card-head">
            <strong>Industry Deviation</strong>
            <span>组合权重 - 中证500基准权重</span>
          </div>
          <div ref={barRef} className="risk-chart" />
        </section>
      </div>
    </section>
  );
}
