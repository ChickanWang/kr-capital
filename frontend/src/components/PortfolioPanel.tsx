import { useMemo, useState } from 'react'
import { type BasketDetail, type InstrumentRow, type PortfolioPoint, useFetch } from '../api/client'
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

interface Holding {
  ticker: string
  quantity: number
  last: number
  value: number
  weight: number
  dayReturn: number | null
  contribution: number | null
}

/** A portfolio basket (every member has a quantity): summary figures, a value / return chart, and
 * holdings with weights and today's contribution. Computed from the returns endpoint plus the
 * grid's latest closes. */
export function PortfolioPanel({
  basket,
  universe,
}: {
  basket: BasketDetail
  universe: InstrumentRow[]
}) {
  const [view, setView] = useState<View>('value')
  const [range, setRange] = useState<Range>('1Y')
  const returns = useFetch<PortfolioPoint[]>(`/baskets/${basket.id}/returns?start=${rangeStart(range)}`)
  const points = useMemo(() => returns.data ?? [], [returns.data])

  const stats = useMemo(() => summarise(points), [points])
  const holdings = useMemo(() => holdingsOf(basket, universe), [basket, universe])

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
        <div className="holdings-wrap">
        <table className="holdings">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Qty</th>
              <th>Last</th>
              <th>Value</th>
              <th>Weight</th>
              <th title="Today's move of the stock">1D</th>
              <th title="The stock's share of today's portfolio return">Contrib.</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr key={h.ticker}>
                <td>{h.ticker}</td>
                <td>{h.quantity.toLocaleString('en-US')}</td>
                <td>{price(h.last)}</td>
                <td>{price(h.value)}</td>
                <td>{pct(h.weight, 1).replace('+', '')}</td>
                <td className={signClass(h.dayReturn)}>{pct(h.dayReturn)}</td>
                <td className={signClass(h.contribution)}>{pct(h.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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

/** Each holding's market value and weight at the latest close, and its contribution to today's
 * portfolio return: quantity × (today's close − yesterday's close) ÷ yesterday's portfolio value.
 * Contributions add up to the portfolio's daily return. */
function holdingsOf(basket: BasketDetail, universe: InstrumentRow[]): Holding[] {
  const byId = new Map(universe.map((r) => [r.instrument_id, r]))
  const rows = basket.members.flatMap((m) => {
    const row = byId.get(m.instrument_id)
    if (!row || row.last_price === null || m.target_quantity === null) return []
    const quantity = Number(m.target_quantity)
    const last = row.last_price
    const prevClose = row.ret_1d === null ? null : last / (1 + row.ret_1d)
    return [{ ticker: row.ticker, quantity, last, prevClose, dayReturn: row.ret_1d }]
  })
  const total = rows.reduce((sum, r) => sum + r.quantity * r.last, 0)
  const prevTotal = rows.every((r) => r.prevClose !== null)
    ? rows.reduce((sum, r) => sum + r.quantity * r.prevClose!, 0)
    : null
  return rows
    .map((r) => ({
      ticker: r.ticker,
      quantity: r.quantity,
      last: r.last,
      value: r.quantity * r.last,
      weight: total ? (r.quantity * r.last) / total : 0,
      dayReturn: r.dayReturn,
      contribution:
        prevTotal && r.prevClose !== null ? (r.quantity * (r.last - r.prevClose)) / prevTotal : null,
    }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
}
