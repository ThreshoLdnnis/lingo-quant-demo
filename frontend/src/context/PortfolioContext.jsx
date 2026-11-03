import React, { createContext, useContext, useMemo, useState } from 'react';

const PortfolioContext = createContext(null);

function normalizeTicker(input) {
  const raw = String(input || '').trim().toUpperCase();
  if (!raw) return '';
  if (/^\d{6}\.(SH|SZ|BJ)$/.test(raw)) return raw;
  if (/^\d{6}$/.test(raw)) {
    if (/^(60|68|90)/.test(raw)) return `${raw}.SH`;
    if (/^(43|83|87)/.test(raw)) return `${raw}.BJ`;
    return `${raw}.SZ`;
  }
  return raw;
}

export function PortfolioProvider({ children }) {
  const [watchlist, setWatchlist] = useState(['000408.SZ', '601069.SH']);

  const value = useMemo(() => ({
    watchlist,
    addTicker(input) {
      const ticker = normalizeTicker(input);
      if (!ticker) return;
      setWatchlist((prev) => (prev.includes(ticker) ? prev : [...prev, ticker]));
    },
    removeTicker(ticker) {
      setWatchlist((prev) => prev.filter((item) => item !== ticker));
    },
  }), [watchlist]);

  return <PortfolioContext.Provider value={value}>{children}</PortfolioContext.Provider>;
}

export function usePortfolio() {
  const context = useContext(PortfolioContext);
  if (!context) {
    throw new Error('usePortfolio must be used inside PortfolioProvider');
  }
  return context;
}
