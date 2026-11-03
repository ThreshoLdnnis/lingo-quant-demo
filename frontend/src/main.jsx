import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  BrainCircuit,
  Cpu,
  Layers3,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Zap,
} from 'lucide-react';
import ComputeDashboard from './ComputeDashboard.jsx';
import { PortfolioProvider, usePortfolio } from './context/PortfolioContext.jsx';
import MicrostructureSandbox from './MicrostructureSandbox.jsx';
import NewsDashboard from './NewsDashboard.jsx';
import RiskDashboard from './RiskDashboard.jsx';
import './styles.css';

function fmt(n, digits = 2) {
  return Number(n).toFixed(digits);
}

function formatPct(value, digits = 1) {
  return `${fmt(value, digits)}%`;
}

function featureLabel(feature) {
  const labels = {
    vwap_accumulation: 'VWAP吸筹',
    pulse_penalty: '脉冲惩罚',
    downside_support: '下跌承接',
    volume_entropy: '成交熵',
    pre_close_strength: '尾盘确认',
    smart_money_score: '聪明资金',
    pure_smart_money_score: '风控后Alpha',
  };
  return labels[feature] || feature || '实时推理';
}

function normalizePrediction(prediction) {
  const winRate = Number(
    prediction.win_rate_pct
    ?? prediction.win_rate
    ?? prediction.winRatePct
    ?? (prediction.score != null ? prediction.score * 100 : 0)
  );
  return {
    ticker: prediction.ticker || '--',
    name: prediction.name || prediction.ticker || '实时标的',
    alpha: Number(prediction.alpha_z ?? prediction.alpha_norm ?? prediction.smart_money_score ?? prediction.score ?? winRate / 100),
    winRate,
    topFeature: prediction.top_feature || prediction.topFeature || 'unknown',
    entropy: Number(prediction.volume_entropy ?? prediction.entropy ?? 0),
    vwap: Number(prediction.vwap_accumulation ?? prediction.vwap ?? 0),
    latest: Number(prediction.latest ?? prediction.price ?? 0),
    changePct: Number(prediction.change_pct ?? prediction.changePct ?? 0),
    amountYi: Number(prediction.amount_yi ?? (prediction.amount != null ? prediction.amount / 100000000 : 0)),
    quoteTime: prediction.quote_time || prediction.quoteTime || prediction.time || '',
  };
}

function buildStreamEvents(payload, predictions) {
  const rawEvents = payload.nlp_events || payload.events || payload.alpha_stream;
  const eventList = Array.isArray(rawEvents) ? rawEvents : (rawEvents ? [rawEvents] : []);
  if (eventList.length) {
    return eventList.map((event, index) => ({
      id: event.id || `${payload.timestamp || Date.now()}-${event.ticker || index}-${event.event_type || event.type || 'nlp'}`,
      timestamp: event.timestamp || payload.timestamp || '--:--:--',
      tag: event.tag || event.sector || event.event_type || 'NLP',
      reason: event.summary || event.reason || event.text || 'LLM 事件解析',
      score: Number(event.score ?? event.sentiment_score ?? event.sentiment ?? 0),
      ticker: event.ticker || event.code || '',
      name: event.name || event.entity || '',
    }));
  }

  const top = predictions[0];
  if (!top) return [];
  const eventTime = top.quoteTime || payload.timestamp || new Date().toLocaleTimeString('zh-CN', { hour12: false });
  return [{
    id: `${eventTime}-${top.ticker}-${fmt(top.alpha, 2)}-${fmt(top.changePct, 2)}`,
    timestamp: eventTime,
    tag: featureLabel(top.topFeature),
    reason: `实时涨跌幅 ${top.changePct >= 0 ? '+' : ''}${fmt(top.changePct)}%，Alpha Z ${fmt(top.alpha)}`,
    score: top.winRate,
    ticker: top.ticker,
    name: top.name,
  }];
}

function Header({ running, setRunning, searchQuery, setSearchQuery }) {
  const { addTicker } = usePortfolio();

  function handleSearchKeyDown(event) {
    if (event.key !== 'Enter') return;
    addTicker(searchQuery);
    setSearchQuery('');
  }

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark"><Radar size={18} /></div>
        <div>
          <div className="brand-name">LINGYU QUANT SYSTEM</div>
          <div className="brand-sub">A-SHARE ALPHA · RESEARCH · EXECUTION</div>
        </div>
      </div>
      <div className="command">
        <Search size={15} />
        <input
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          onKeyDown={handleSearchKeyDown}
          placeholder="输入股票代码并回车加入自选，例如：600519.SH"
        />
        <kbd>Enter</kbd>
      </div>
      <div className="system-state">
        <span>Parquet Lake</span>
        <span>Vector Core</span>
        <span className="live"><Activity size={14} /> 16.8ms</span>
        <button className="icon-btn" title={running ? '暂停流处理' : '启动流处理'} onClick={() => setRunning(!running)}>
          {running ? <Pause size={16} /> : <Play size={16} />}
        </button>
      </div>
    </header>
  );
}

function Panel({ id, title, icon, children }) {
  return (
    <section className={`panel ${id}`}>
      <div className="panel-head">
        <span>{icon}{title}</span>
        <div className="panel-tools">
          <button title="刷新"><RefreshCw size={13} /></button>
          <button title="设置"><Settings2 size={13} /></button>
        </div>
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function Widget({ id, title, icon, children, fullscreenId, setFullscreenId }) {
  const fullscreen = fullscreenId === id;
  return (
    <section className={`widget ${fullscreen ? 'fullscreen' : ''}`}>
      <div className="widget-head">
        <span>{icon}{title}</span>
        <button
          className="widget-action"
          title={fullscreen ? '退出全屏' : '全屏'}
          onClick={() => setFullscreenId(fullscreen ? null : id)}
        >
          {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
      </div>
      <div className="widget-body">{children}</div>
    </section>
  );
}

function Treemap({ rows }) {
  return (
    <div className="treemap">
      {rows.map((row) => (
        <button key={row.sector} className={`tile ${row.changePct >= 0 ? 'pos' : 'neg'}`}>
          <span>{row.sector}</span>
          <strong>{fmt(row.changePct)}%</strong>
          <small>成交额 {fmt(row.netInflow, 1)}亿 · α {fmt(row.alpha, 0)}</small>
        </button>
      ))}
      {rows.length === 0 && <div className="empty-watchlist">等待 FFD 实时行情</div>}
    </div>
  );
}

function FactorMatrix({ predictions, searchQuery }) {
  const { watchlist } = usePortfolio();
  const watchSet = useMemo(() => new Set(watchlist), [watchlist]);
  const query = searchQuery.trim().toLowerCase();
  const ranked = predictions
    .slice()
    .sort((a, b) => b.alpha - a.alpha)
    .filter((s) => !query || s.ticker.toLowerCase().includes(query) || s.name.toLowerCase().includes(query));

  return (
    <table className="matrix">
      <thead>
        <tr><th>代码</th><th>名称</th><th>最新</th><th>涨跌</th><th>Alpha Z</th><th>胜率</th><th>成交额</th><th>快照</th></tr>
      </thead>
      <tbody>
        {ranked.map((s) => (
          <tr key={s.ticker} className={`${query ? 'search-hit' : ''} ${watchSet.has(s.ticker) ? 'watchlisted' : ''}`}>
            <td className="mono">{s.ticker}</td>
            <td>{s.name}</td>
            <td className="num">{s.latest ? fmt(s.latest, 2) : '--'}</td>
            <td className={s.changePct >= 0 ? 'num pos-text' : 'num neg-text'}>{formatPct(s.changePct, 2)}</td>
            <td className={s.alpha >= 0 ? 'num pos-text' : 'num neg-text'}>{fmt(s.alpha)}</td>
            <td><div className="bar"><i style={{ width: `${Math.max(0, Math.min(100, s.winRate))}%` }} /></div></td>
            <td className="num">{fmt(s.amountYi, 1)}亿</td>
            <td className="mono quote-time">{String(s.quoteTime).slice(-8) || '--'}</td>
          </tr>
        ))}
        {ranked.length === 0 && <tr><td colSpan="8" className="empty">等待 FFD 实时快照，或检查后端 WebSocket 连接</td></tr>}
      </tbody>
    </table>
  );
}

function AlphaStream({ events }) {
  return (
    <div className="alpha-stream">
      {events.map((event) => (
        <div className="event" key={event.id}>
          <span className="ts">{event.timestamp}</span><span className="tag">{event.tag}</span><span>{event.reason}</span><span className="score">{formatPct(event.score)}</span><span className="match">{event.ticker} · {event.name}</span>
        </div>
      ))}
      {events.length === 0 && <div className="empty-watchlist">等待推理流生成 Alpha Stream</div>}
    </div>
  );
}

const navItems = [
  ['alpha', 'Alpha', <BrainCircuit size={16} />],
  ['risk', 'Risk', <ShieldCheck size={16} />],
  ['news', 'News', <Bell size={16} />],
  ['compute', 'Compute', <Cpu size={16} />],
  ['micro', 'Micro', <Radar size={16} />],
  ['settings', 'Settings', <SlidersHorizontal size={16} />],
];

function App() {
  const [running, setRunning] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeView, setActiveView] = useState('alpha');

  return (
    <div className="app">
      <Header running={running} setRunning={setRunning} searchQuery={searchQuery} setSearchQuery={setSearchQuery} />
      <aside className="left-rail">
        {navItems.map(([id, label, icon]) => (
          <button key={id} className={activeView === id ? 'active' : ''} title={label} onClick={() => setActiveView(id)}>
            {icon}<span>{label}</span>
          </button>
        ))}
      </aside>
      <main className="workspace">
        {activeView === 'alpha' && (
          <AlphaDashboard
            searchQuery={searchQuery}
          />
        )}
        {activeView === 'risk' && <RiskDashboard />}
        {activeView === 'news' && <NewsDashboard />}
        {activeView === 'micro' && <MicrostructureView />}
        {activeView === 'compute' && <ComputeDashboard />}
        {activeView !== 'alpha' && activeView !== 'risk' && activeView !== 'news' && activeView !== 'micro' && activeView !== 'compute' && <UnderConstruction view={activeView} />}
      </main>
    </div>
  );
}

function AlphaDashboard({ searchQuery }) {
  const [fullscreenId, setFullscreenId] = useState(null);
  const wsRef = useRef(null);
  const [wsStatus, setWsStatus] = useState('CONNECTING');
  const [marketPanorama, setMarketPanorama] = useState([]);
  const [livePredictions, setLivePredictions] = useState([]);
  const [streamEvents, setStreamEvents] = useState([]);
  const [layout, setLayout] = useState([
    { i: 'panorama', x: 0, y: 0, w: 8, h: 4 },
    { i: 'factor', x: 8, y: 0, w: 4, h: 7 },
    { i: 'stream', x: 0, y: 4, w: 8, h: 3 },
  ]);
  const [draggingId, setDraggingId] = useState(null);

  useEffect(() => {
    const ws = new WebSocket('ws://127.0.0.1:8000/ws/inference');
    wsRef.current = ws;

    ws.onopen = () => setWsStatus('OPEN');
    ws.onerror = () => setWsStatus('ERROR');
    ws.onclose = () => setWsStatus('CLOSED');
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const nextPanorama = Array.isArray(payload.market_panorama)
          ? payload.market_panorama.map((item) => ({
            sector: item.sector,
            changePct: Number(item.change_pct ?? item.changePct ?? 0),
            netInflow: Number(item.net_inflow ?? item.netInflow ?? 0),
            alpha: Number(item.alpha ?? 0),
          }))
          : [];
        const rawMatrix = payload.factor_matrix || payload.predictions;
        const nextPredictions = Array.isArray(rawMatrix)
          ? rawMatrix.map(normalizePrediction)
          : [];
        if (nextPanorama.length) {
          setMarketPanorama(nextPanorama);
        }
        if (nextPredictions.length) {
          setLivePredictions(nextPredictions);
          const nextEvents = buildStreamEvents(payload, nextPredictions);
          if (nextEvents.length) {
            setStreamEvents((current) => {
              const existingIds = new Set(current.map((item) => item.id));
              const freshEvents = nextEvents.filter((item) => !existingIds.has(item.id));
              if (!freshEvents.length) return current;
              return [...freshEvents, ...current].slice(0, 10);
            });
          }
        }
        if (payload.system_status?.feed) {
          setWsStatus(payload.system_status.feed);
        }
      } catch (error) {
        setWsStatus('ERROR');
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  const widgetProps = { fullscreenId, setFullscreenId };
  const widgetMap = {
    panorama: <Widget id="panorama" title="市场全景" icon={<Layers3 size={15} />} {...widgetProps}><Treemap rows={marketPanorama} /></Widget>,
    factor: <Widget id="factor" title="实时因子矩阵" icon={<BrainCircuit size={15} />} {...widgetProps}><FactorMatrix predictions={livePredictions} searchQuery={searchQuery} /></Widget>,
    stream: <Widget id="stream" title="Alpha Stream" icon={<Zap size={15} />} {...widgetProps}><AlphaStream events={streamEvents} /></Widget>,
  };

  function moveWidget(targetId) {
    if (!draggingId || draggingId === targetId) return;
    setLayout((current) => {
      const source = current.find((item) => item.i === draggingId);
      const target = current.find((item) => item.i === targetId);
      if (!source || !target) return current;
      return current.map((item) => {
        if (item.i === draggingId) return { ...item, x: target.x, y: target.y, w: target.w, h: target.h };
        if (item.i === targetId) return { ...item, x: source.x, y: source.y, w: source.w, h: source.h };
        return item;
      });
    });
    setDraggingId(null);
  }

  return (
    <>
      <div className="ticker-strip">
        <span className="strip-label">MARKET BREADTH {fmt(marketPanorama.filter((s) => s.changePct > 0).length / Math.max(marketPanorama.length, 1) * 100, 0)}%</span>
        <span className={`stream-state ${wsStatus === 'OPEN' ? 'active' : ''}`}>WS {wsStatus}</span>
        {livePredictions.slice(0, 8).map((s) => (
          <span key={s.ticker} className={s.alpha >= 0 ? 'chip up' : 'chip down'}>
            {s.ticker} {s.alpha >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />} {fmt(s.alpha)}
          </span>
        ))}
      </div>
      <div className="mosaic-grid">
        {layout.map(({ i, x, y, w, h }) => (
          <div
            key={i}
            className={`mosaic-cell ${i}`}
            style={{ gridColumn: `${x + 1} / span ${w}`, gridRow: `${y + 1} / span ${h}` }}
            draggable
            onDragStart={() => setDraggingId(i)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => moveWidget(i)}
          >
            {widgetMap[i]}
          </div>
        ))}
      </div>
    </>
  );
}

function MicrostructureView() {
  return (
    <section className="view-shell micro-view" aria-label="微观结构沙盘">
      <MicrostructureSandbox />
    </section>
  );
}

function UnderConstruction({ view }) {
  const label = navItems.find(([id]) => id === view)?.[1] || view;
  return (
    <section className="view-shell placeholder-view">
      <div>
        <span>{label}</span>
        <strong>建设中</strong>
        <small>Under Construction</small>
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(
  <PortfolioProvider>
    <App />
  </PortfolioProvider>
);
