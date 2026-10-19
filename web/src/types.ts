export interface KlineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount?: number | null;
  turnover_rate?: number | null;
  change?: number | null;
  change_pct?: number | null;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  bb_upper?: number | null;
  bb_middle?: number | null;
  bb_lower?: number | null;
}

export interface StockProfile {
  code: string;
  name: string | null;
  category: string | null;
  market: string | null;
  needUpdate: boolean | null;
  lastDataDate: string | null;
  dataDays: number | null;
  industry: string | null;
  industryCode: string | null;
  industryUpdatedAt: string | null;
  updatedAt: string | null;
  latestQuote: {
    date: string | null;
    open: number | null;
    high: number | null;
    low: number | null;
    close: number | null;
    volume: number | null;
  };
  latestScan: {
    scanDate: string | null;
    industry: string | null;
    latestPrice: number | null;
    resonanceCount: number | null;
    sectorStrength: number | null;
    strategiesHit: string[];
  };
}

export interface StrategyInfo {
  name: string;
  title: string;
  description: string;
  icon: string;
  color: string;
  latestDate: string | null;
  stockCount: number;
  industryCount: number;
}

export interface StockResult {
  id: number;
  stockCode: string;
  stockName: string | null;
  industry: string | null;
  targetDate: string;
  latestPrice: number | null;
  metadata: string | null;
  createdAt: string;
}

export interface StrategyResults {
  strategyName: string;
  date: string;
  totalStocks: number;
  industryCount: number;
  stocks: StockResult[];
}

export interface BacktestSummary {
  strategyName: string;
  title: string;
  runDate: string;
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  avgReturnPct: number;
  bestReturnPct: number;
  worstReturnPct: number;
  avgHoldingDays: number;
}

export interface BacktestTrade {
  id: number;
  stockCode: string;
  stockName: string | null;
  industry: string | null;
  entryDate: string;
  entryPrice: number;
  exitDate: string | null;
  exitPrice: number | null;
  exitReason: string | null;
  holdingDays: number | null;
  returnPct: number | null;
}

// ── Daily Scan ────────────────────────────────────────────────────────────────

export interface ScanTopSector {
  sector: string;
  rs: number | null;
  count: number;
}

export interface ScanSummary {
  id: string;
  market: string;
  source: string;
  status: string;
  filterCounts?: Record<string,number>;
  warnings?: Record<string,number>;
  error?: string;
  scanDate: string;
  executionDate?: string;
  tradableCount: number;
  candidateCount: number;
  sectorCount: number;
  topSectors: ScanTopSector[];
  marketRegime: string; // "bull" | "neutral" | "bear"
  executionTime: number | null;
  totalStockCount?: number;
  filteredOutCount?: number;
  scannedStockCount?: number;
  hitStockCount?: number;
  hitIndustryCount?: number;
  resonanceIndustryCount?: number;
  scanStrategies?: string[];
  strategyHitCounts?: Record<string, number>;
  filterConfig?: {
    filterSt?: boolean;
    filterNewStock?: boolean;
    filterLiquidity?: boolean;
    filterMarketCap?: boolean;
    filterSuspended?: boolean;
    filterLimit?: boolean;
    minAvgVolume5d?: number;
    minListedDays?: number;
    minMarketCap?: number;
    limitPct?: number;
  };
}

export interface ScanResult {
  id: number;
  scanDate?: string;
  stockCode: string;
  stockName: string | null;
  industry: string | null;
  resonanceCount: number;
  strategiesHit: string[];
  sectorStrength: number | null;
}

export interface ScanSector {
  industry: string;
  rsScore: number | null;
  candidateCount: number;
  stocks: ScanResult[];
}

// ── Stock Pool Filter ───────────────────────────────────────────────────────

export interface FilteredPoolStock {
  code: string;
  name: string;
  industry: string;
}

export interface FilteredPoolResult {
  total: number;
  stocks: FilteredPoolStock[];
}

// ── Portfolio / Positions ─────────────────────────────────────────────────────

export interface Trade {
  id: number;
  positionId: number;
  stockCode: string;
  tradeType: 'BUY' | 'SELL';
  tradeDate: string;
  price: number;
  shares: number;
  amount: number;
  reason: string | null;
  createdAt: string;
}

export interface Position {
  id: number;
  stockCode: string;
  stockName: string | null;
  status: 'OPEN' | 'CLOSED';
  openDate: string;
  closeDate: string | null;
  triggerStrategies: string[]; // parsed JSON
  avgCost: number | null;
  totalShares: number;
  totalInvested: number;
  totalReturned: number;
  maxPrice: number | null;
  pnl: number | null;
  pnlPct: number | null;
  closeReason: string | null;
  pyramidCount: number;
  signalExitDays: number;
  trades?: Trade[];
}

export interface PortfolioSummary {
  openCount: number;
  totalInvested: number;
  estimatedValue: number;
  totalPnl: number;
  totalPnlPct: number;
  availableCash: number;
}

export interface MonitorAlert {
  positionId: number;
  stockCode: string;
  priority: number;
  reason: string;
  action: 'SELL_ALL' | 'SELL_PARTIAL';
  sellShares: number;
  currentPrice: number;
  detail: string;
}

// ── Single-stock backtest ────────────────────────────────────────────────────────────────────────

export interface SingleBacktestTrade {
  entryDate: string;
  entryPrice: number;
  exitDate: string | null;
  exitPrice: number | null;
  size: number | null;          // shares traded
  entryAmount: number | null;   // entry_price * size
  exitAmount: number | null;    // exit_price * size
  pnl: number | null;
  returnPct: number | null;
  exitReason: string | null;
  holdingDays: number | null;
}

export interface SingleBacktestResult {
  stockCode: string;
  stockName: string;
  strategyName: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  totalPnl: number;
  totalReturn: number;  // % return on initial capital
  trades: SingleBacktestTrade[];
}

// Per-stock record from the all-stocks backtest page
export interface AllBacktestTrade {
  id: number;
  strategyName: string;
  strategyTitle: string;
  stockCode: string;
  stockName: string | null;
  industry: string | null;
  entryDate: string;
  entryPrice: number;
  exitDate: string | null;
  exitPrice: number | null;
  exitReason: string | null;
  holdingDays: number | null;
  returnPct: number | null;
}

// Per-stock historical backtest record (from DB)
export interface StockBacktestRecord {
  id: number;
  runDate: string;
  strategyName: string;
  strategyTitle: string;
  entryDate: string;
  entryPrice: number;
  exitDate: string | null;
  exitPrice: number | null;
  exitReason: string | null;
  holdingDays: number | null;
  returnPct: number | null;
}
