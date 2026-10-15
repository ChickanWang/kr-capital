import { useMemo, useState } from 'react'
import { type BasketDetail, type PortfolioPoint, useFetch } from '../api/client'
import { pct, price, shortDate, signClass } from '../format'
import { LineChart, type Line } from './LineChart'
import { RANGES, type Range, rangeStart, returnLabel } from './ranges'

type View = 'value' | 'daily' | 'cumulative'
const VIEWS: { view: View; label: string }[] = [
  { view: 'value', label: 'Value' },
  { view: 'daily', label: 'Daily return' },
  { view: 'cumulative', label: 'Cumulative' },
]
const TRADING_DAYS = 252
const UP = '#3ecf8e'
const DOWN = '#f2555a'

/** A portfolio basket (every member has a quantity): summary figures and a value / return chart,
 * computed from the returns endpoint. Its holdings are in the Holdings tab. */
export function PortfolioPanel({ basket }: { basket: BasketDetail }) {
  const [view, setView] = useState<View>('value')
  const [range, setRange] = useState<Range>('1Y')
  const returns = useFetch<PortfolioPoint[]>(`/baskets/${basket.id}/returns?start=${rangeStart(range)}`)
  const points = useMemo(() => returns.data ?? [], [returns.data])

  const stats = useMemo(() => summarise(points), [points])

  const lines = useMemo<Line[]>(() => {
    if (view === 'value') return [{ name: 'Value', points: points.map((p) => ({ date: p.date, value: p.value })) }]
    if (view === 'cumulative') {
      return [{ name: 'Cumulative', points: points.map((p) => ({ date: p.date, value: p.cumulative_return })) }]
    }
    return [
      {
        name: 'Daily return',
        kind: 'bars',
        points: points
          .filter((p) => p.daily_return !== null)
          .map((p) => ({ date: p.date, value: p.daily_return!, color: p.daily_return! >= 0 ? UP : DOWN })),
      },
    ]
  }, [points, view])

  return (
    <section className="panel portfolio-panel">
      <header className="panel-header">
        <div className="stats">
          <Stat label="Value" value={stats ? price(stats.value) : '–'} />
          <Stat
            label="Today"
            value={stats?.dayChange == null ? '–' : `${signed(stats.dayChange)} (${pct(stats.dayReturn)})`}
            tone={stats?.dayChange}
          />
          <Stat label={returnLabel(range)} value={pct(stats?.totalReturn)} tone={stats?.totalReturn} />
          <Stat label="Volatility (ann.)" value={pct(stats?.volatility, 1).replace('+', '')} />
          <Stat label="Max drawdown" value={pct(stats?.maxDrawdown)} tone={stats?.maxDrawdown} />
          <Stat
            label="Best / worst day"
            value={stats ? `${pct(stats.best.value)} · ${pct(stats.worst.value)}` : '–'}
            title={stats ? `Best ${stats.best.date}, worst ${stats.worst.date}` : undefined}
          />
        </div>
        <div className="controls">
          <div className="button-group">
            {VIEWS.map((v) => (
              <button key={v.view} className={v.view === view ? 'active' : ''} onClick={() => setView(v.view)}>
                {v.label}
              </button>
            ))}
          </div>
          <div className="button-group">
            {RANGES.map((r) => (
              <button key={r} className={r === range ? 'active' : ''} onClick={() => setRange(r)}>
                {r}
              </button>
            ))}
          </div>
        </div>
      </header>
      {returns.error && <p className="error">{returns.error}</p>}
      <div className="portfolio-body">
        <div className="portfolio-chart">
          <LineChart lines={lines} format={view === 'value' ? 'price' : 'percent'} />
        </div>
      </div>
    </section>
  )
}

function Stat({ label, value, tone, title }: { label: string; value: string; tone?: number | null; title?: string }) {
  return (
    <div className="stat" title={title}>
      <span className="muted">{label}</span>
      <strong className={signClass(tone)}>{value}</strong>
    </div>
  )
}

function signed(dollars: number): string {
  return `${dollars >= 0 ? '+' : '−'}${price(Math.abs(dollars))}`
}

/** Summary figures over the loaded range. Volatility is the standard deviation of daily returns,
 * annualised with √252; max drawdown is the largest fall from a running peak in value. */
function summarise(points: PortfolioPoint[]) {
  if (points.length === 0) return null
  const last = points[points.length - 1]
  const prev = points.length > 1 ? points[points.length - 2] : null
  const daily = points.flatMap((p) => (p.daily_return === null ? [] : [{ date: p.date, value: p.daily_return }]))
  const mean = daily.reduce((sum, d) => sum + d.value, 0) / (daily.length || 1)
  const variance = daily.reduce((sum, d) => sum + (d.value - mean) ** 2, 0) / Math.max(daily.length - 1, 1)
  let peak = -Infinity
  let maxDrawdown = 0
  for (const p of points) {
    peak = Math.max(peak, p.value)
    maxDrawdown = Math.min(maxDrawdown, p.value / peak - 1)
  }
  const byValue = [...daily].sort((a, b) => a.value - b.value)
  const none = { date: '', value: 0 }
  return {
    value: last.value,
    dayChange: prev ? last.value - prev.value : null,
    dayReturn: last.daily_return,
    totalReturn: last.cumulative_return,
    volatility: daily.length > 1 ? Math.sqrt(variance) * Math.sqrt(TRADING_DAYS) : null,
    maxDrawdown,
    best: byValue.length ? { ...byValue[byValue.length - 1], date: shortDate(byValue[byValue.length - 1].date) } : none,
    worst: byValue.length ? { ...byValue[0], date: shortDate(byValue[0].date) } : none,
  }
}
