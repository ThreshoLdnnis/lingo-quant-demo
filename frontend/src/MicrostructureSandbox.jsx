import React, { useEffect, useMemo, useRef, useState } from 'react';
import './MicrostructureSandbox.css';

const ECHARTS_CDN = 'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js';

function loadECharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${ECHARTS_CDN}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve(window.echarts));
      existing.addEventListener('error', reject);
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

function generateSimulationData(scenario, volatility) {
  const minutes = 240;
  const prices = [];
  const volumes = [];
  const basePrice = 10.0;
  let currentPrice = basePrice;
  const volFactor = volatility / 100 / Math.sqrt(minutes);

  Array.from({ length: minutes }).forEach((_, i) => {
    let noise = (Math.random() - 0.5) * volFactor * basePrice;
    let currentVol = 1000 + Math.random() * 500;

    if (scenario === 'institutional') {
      noise -= volFactor * basePrice * 0.1;
      currentVol = 5000 + Math.random() * 1000;
    } else if (scenario === 'retail') {
      if (i < 15) {
        noise += volFactor * basePrice * 3.0;
        currentVol = 20000 + Math.random() * 5000;
      } else {
        noise -= volFactor * basePrice * 0.3;
        currentVol = 800 + Math.random() * 300;
      }
    } else if (scenario === 'support') {
      noise -= volFactor * basePrice * 0.8;
      currentVol = noise < -volFactor * basePrice * 0.4 ? 15000 + Math.random() * 2000 : 1500 + Math.random() * 500;
    }

    currentPrice += noise;
    prices.push(Number(currentPrice.toFixed(3)));
    volumes.push(Math.round(currentVol));
  });

  return { prices, volumes, xAxis: Array.from({ length: minutes }, (_, i) => `Min ${i + 1}`) };
}

function calculateFactors(prices, volumes) {
  const totalVolume = volumes.reduce((a, b) => a + b, 0);
  const totalAmount = prices.reduce((sum, price, i) => sum + price * volumes[i], 0);
  const vwap = totalAmount / totalVolume;
  const twap = prices.reduce((a, b) => a + b, 0) / prices.length;
  const vwapDev = ((twap - vwap) / vwap) * 100;
  const avgVol = totalVolume / volumes.length;
  const pulseRatio = Math.max(...volumes) / avgVol;
  const entropy = volumes.reduce((sum, volume) => {
    const p = volume / totalVolume;
    return p > 0 ? sum - p * Math.log(p) : sum;
  }, 0);

  return { entropy, pulseRatio, vwapDev };
}

export default function MicrostructureSandbox() {
  const chartRef = useRef(null);
  const instanceRef = useRef(null);
  const [scenario, setScenario] = useState('institutional');
  const [volatility, setVolatility] = useState(2.5);
  const [echartsReady, setEchartsReady] = useState(false);

  const data = useMemo(() => generateSimulationData(scenario, volatility), [scenario, volatility]);
  const factors = useMemo(() => calculateFactors(data.prices, data.volumes), [data]);

  useEffect(() => {
    let disposed = false;
    loadECharts()
      .then((echarts) => {
        if (disposed || !chartRef.current) return;
        instanceRef.current = instanceRef.current || echarts.init(chartRef.current, 'dark');
        setEchartsReady(true);
      })
      .catch(() => setEchartsReady(false));

    return () => {
      disposed = true;
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!instanceRef.current) return;
    instanceRef.current.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { data: ['标的价格', '成交量'], textStyle: { color: '#4b5563' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: data.xAxis, show: false },
      yAxis: [
        { type: 'value', name: '价格', scale: true, splitLine: { lineStyle: { color: '#d1d5db' } } },
        { type: 'value', name: '成交量', splitLine: { show: false } },
      ],
      series: [
        { name: '成交量', type: 'bar', yAxisIndex: 1, data: data.volumes, itemStyle: { color: '#3b82f6', opacity: 0.55 } },
        { name: '标的价格', type: 'line', data: data.prices, smooth: true, itemStyle: { color: '#b45309' }, lineStyle: { width: 3 } },
      ],
    });
  }, [data, echartsReady]);

  useEffect(() => {
    const onResize = () => instanceRef.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div className="micro-sandbox max-w-6xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold border-b border-gray-300 pb-2">翎语量化 - 微观结构订单流推演沙盘 (EMS)</h1>

      <div className="card grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm font-medium text-gray-500 mb-2">市场微观结构场景 (Microstructure Scenario)</label>
          <select
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
            className="w-full bg-white text-gray-900 border border-gray-300 rounded p-2 focus:outline-none focus:border-blue-500"
          >
            <option value="institutional">机构 VWAP 算法均匀吸筹 (Smart Money)</option>
            <option value="retail">游资开盘脉冲拉升出货 (Retail Noise)</option>
            <option value="support">压盘下跌承接建仓 (Downside Support)</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-500 mb-2">
            日内整体波动率 (Intraday Volatility): <span className="text-gray-900 font-bold">{volatility.toFixed(1)}%</span>
          </label>
          <input
            type="range"
            min="1.0"
            max="8.0"
            step="0.5"
            value={volatility}
            onChange={(event) => setVolatility(Number(event.target.value))}
            className="w-full"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard label="香农熵 (成交均匀度)" value={factors.entropy.toFixed(3)} tone={factors.entropy > 5.2 ? 'text-green-400' : 'text-gray-300'} help="越大说明算法拆单越均匀" />
        <MetricCard label="脉冲倍数 (噪音强度)" value={`${factors.pulseRatio.toFixed(1)}x`} tone={factors.pulseRatio > 10 ? 'text-red-400' : 'text-gray-300'} help="单分钟最大量/平均量" />
        <MetricCard label="VWAP 偏离度" value={`${factors.vwapDev.toFixed(2)}%`} tone={factors.vwapDev > 0 ? 'text-green-400' : 'text-red-400'} help="TWAP - VWAP (正值暗示吸筹)" />
      </div>

      <div className="card">
        <div ref={chartRef} style={{ width: '100%', height: 400 }} />
      </div>
    </div>
  );
}

function MetricCard({ label, value, tone, help }) {
  return (
    <div className="card flex flex-col justify-center">
      <div className="text-sm text-gray-500">{label}</div>
      <div className={`metric-value ${tone}`}>{value}</div>
      <div className="text-xs mt-1 text-gray-400">{help}</div>
    </div>
  );
}
