import React, { useEffect, useMemo, useState } from 'react';
import './NewsDashboard.css';

function normalizeNewsEvent(payload) {
  return {
    id: payload.id || `${payload.timestamp || Date.now()}-${payload.ticker || 'news'}`,
    timestamp: payload.timestamp || new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    summary: payload.summary || payload.text || '收到一条未命名舆情事件',
    ticker: payload.ticker || payload.code || '--',
    name: payload.name || payload.entity || '未知实体',
    type: payload.event_type || payload.type_label || payload.type || '事件解析',
    score: Number(payload.sentiment_score ?? payload.score ?? payload.sentiment ?? 0),
    latency: Number(payload.llm_latency_ms ?? payload.latency_ms ?? 125),
  };
}

export default function NewsDashboard() {
  const [newsFeed, setNewsFeed] = useState([]);
  const [eventCount, setEventCount] = useState(0);
  const [latency, setLatency] = useState(125);
  const [connectionState, setConnectionState] = useState('connecting');

  useEffect(() => {
    const ws = new WebSocket('ws://127.0.0.1:8000/ws/news');

    ws.onopen = () => setConnectionState('active');
    ws.onerror = () => setConnectionState('error');
    ws.onclose = () => setConnectionState('closed');
    ws.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data);
        if (payload.type && payload.type !== 'llm_news_event') {
          setConnectionState(payload.message || payload.type);
          return;
        }
        const event = normalizeNewsEvent(payload);
        setLatency(event.latency);
        setEventCount((count) => count + 1);
        setNewsFeed((prev) => [event, ...prev].slice(0, 50));
      } catch (error) {
        setConnectionState('parse_error');
      }
    };

    return () => ws.close();
  }, []);

  const metrics = useMemo(() => {
    const avg = newsFeed.reduce((sum, item) => sum + item.score, 0) / Math.max(newsFeed.length, 1);
    const sentimentIndex = Math.round((avg + 1) * 50);
    return {
      latency,
      sentimentIndex,
      eventCount,
    };
  }, [eventCount, latency, newsFeed]);

  return (
    <section className="news-dashboard view-shell">
      <div className="news-head">
        <div>
          <span className="eyebrow">LLM EVENT INTELLIGENCE</span>
          <h2>NLP 智能舆情终端</h2>
        </div>
        <div className="news-metrics">
          <Metric label="LLM 推理延迟" value={`${metrics.latency}ms / 条`} status={connectionState} />
          <div className="news-metric">
            <small>全局情绪指数</small>
            <strong>{metrics.sentimentIndex}</strong>
            <div className="sentiment-mini"><i style={{ width: `${metrics.sentimentIndex}%` }} /></div>
          </div>
          <Metric label="今日事件触发" value={`${metrics.eventCount.toLocaleString()} 条`} />
        </div>
      </div>

      <div className="event-feed">
        {newsFeed.map((event, index) => (
          <article className={`event-card ${event.score >= 0 ? 'bullish' : 'bearish'} ${index === 0 ? 'new' : ''}`} key={event.id}>
            <div className="event-time">[{event.timestamp}]</div>
            <div className="event-main">
              <p>{event.summary}</p>
              <div className="event-tags">
                <span className="ner">{event.ticker} · {event.name}</span>
                <span>{event.type}</span>
                <b>{event.score > 0 ? '+' : ''}{event.score.toFixed(2)}</b>
              </div>
            </div>
          </article>
        ))}
        {newsFeed.length === 0 && (
          <div className="news-empty">正在连接实时舆情流，等待 LLM 事件进入...</div>
        )}
      </div>
    </section>
  );
}

function Metric({ label, value, status = 'streaming' }) {
  return (
    <div className="news-metric">
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{status}</span>
    </div>
  );
}
