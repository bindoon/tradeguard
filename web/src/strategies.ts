import { StrategyInfo } from './types';

export type StrategyDefinition = Pick<
  StrategyInfo,
  'name' | 'title' | 'description' | 'icon' | 'color'
>;

export const STRATEGIES: StrategyDefinition[] = [
  {
    name: 'ma_golden_cross',
    title: '均线金叉多头排列',
    description: '两天前 5 日线上穿 10 日线，且当前均线维持多头排列。',
    icon: '📈',
    color: 'from-purple-600 to-indigo-700',
  },
  {
    name: 'two_bullish_one_bearish',
    title: '两阳夹一阴',
    description: '基于均线金叉结果的二次筛选，定位金叉后的延续形态。',
    icon: '📊',
    color: 'from-indigo-600 to-blue-700',
  },
  {
    name: 'macd_golden_cross',
    title: 'MACD 金叉趋势',
    description: '当日 MACD 金叉，且位于零轴上方并站上 MA20。',
    icon: '📉',
    color: 'from-emerald-600 to-teal-700',
  },
  {
    name: 'rsi_rebound',
    title: 'RSI 超卖反弹',
    description: 'RSI 从超卖区上穿 30，伴随放量阳线。',
    icon: '🔄',
    color: 'from-amber-600 to-orange-700',
  },
  {
    name: 'bollinger_breakout',
    title: '布林带放量突破',
    description: '收盘首次突破布林上轨，且当日量能高于 20 日均量。',
    icon: '🚀',
    color: 'from-sky-600 to-cyan-700',
  },
  {
    name: 'box_breakout',
    title: '箱体突破',
    description: '横盘整理 20 日后收盘首次放量突破箱体上沿，箱体振幅 < 15%，量能 > 1.5×MA20。',
    icon: '📦',
    color: 'from-violet-600 to-purple-700',
  },
];

export const STRATEGY_MAP = Object.fromEntries(
  STRATEGIES.map(strategy => [strategy.name, strategy]),
) as Record<string, StrategyDefinition>;

export const DAILY_STRATEGIES = STRATEGIES.filter(s => s.name !== 'two_bullish_one_bearish');
