import { useEffect, useRef, useState } from 'react'
import { api, type Annotation, type PriceMode, type PriceSeries } from '../api/client'
import { MAX_SELECTED } from '../constants'
import { shortDate } from '../format'
import { LINE_COLORS } from './colors'
import { LineChart, type Line } from './LineChart'
import { RANGES, type Range, rangeStart } from './ranges'

const MODES: { mode: PriceMode; label: string }[] = [
  { mode: 'price', label: 'Price' },
  { mode: 'daily', label: 'Daily return' },
  { mode: 'cumulative', label: 'Cumulative' },
]
const NO_LINES: Line[] = []

/** How price mode plots values: dollars, dollars on a log axis, or year-over-year growth. */
type PriceAxis = 'usd' | 'log' | 'yoy'
const AXES: { axis: PriceAxis; label: string }[] = [
  { axis: 'usd', label: '$' },
  { axis: 'log', label: '$ log' },
  { axis: 'yoy', label: 'YoY %' },
]

/** One line saying exactly what the y-axis shows. */
function axisCaption(mode: PriceMode, axis: PriceAxis, start: string): string {
  if (mode === 'daily') return 'daily return, % change from the previous close.'
  if (mode === 'cumulative') return `cumulative return since ${start}, %.`
  if (axis === 'log') {
    return 'price in USD (split-adjusted) on a log scale: equal distances are equal % moves, so stocks at different price levels compare fairly.'
  }
  if (axis === 'yoy') {
    return "year-over-year growth: each day's close vs. the close one year earlier, %. Needs a year of history before the first point, so it starts later for recent ranges."
  }
  return 'price in USD (split-adjusted).'
}

function yearBefore(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() - 1)
  return d.toISOString().slice(0, 10)
}

/** Year-over-year growth for each point on or after `start`: close ÷ the last close at least a
 * year earlier − 1. `points` must be in date order and reach back a year before `start`. */
function yoyGrowth(points: PriceSeries['points'], start: string): PriceSeries['points'] {
  const out: PriceSeries['points'] = []
  let j = 0
  for (const p of points) {
    if (p.date < start) continue
    const cutoff = yearBefore(p.date)
    while (j + 1 < points.length && points[j + 1].date <= cutoff) j++
    if (points[j].date <= cutoff) out.push({ date: p.date, value: p.value / points[j].value - 1 })
  }
  return out
}

/** The first trading day on or after `date`, so an annotation dated on a weekend or holiday sits on
 * the next bar. Null when the date falls outside the plotted range. */
function snapToTradingDay(date: string, tradingDays: string[]): string | null {
  if (tradingDays.length === 0 || date < tradingDays[0]) return null
  return tradingDays.find((d) => d >= date) ?? null
}

interface Popup {
  id: string
  x: number
  y: number
  /** Open to the left of the click when it is on the right half of the chart. */
  flip: boolean
  width: number
}

/** Price history for the focused stock, or the selected stocks side by side when 2+ are selected.
 * Several stocks default to a log dollar axis, which keeps real prices while making different price
 * levels comparable; YoY growth is the percentage alternative. */
export function PriceChart({
  focused,
  selected,
  annotationsVersion,
  onOpenCard,
}: {
  focused: string | null
  selected: string[]
  /** Bumped when annotations change, so the chart's dots are refetched. */
  annotationsVersion: number
  onOpenCard: (ticker: string) => void
}) {
  const [mode, setMode] = useState<PriceMode>('price')
  // 'auto' is plain dollars for one stock and a log dollar axis for several.
  const [axisChoice, setAxisChoice] = useState<'auto' | PriceAxis>('auto')
  const [range, setRange] = useState<Range>('1Y')
  const [lines, setLines] = useState<Line[]>([])
  // Annotations behind each dot, keyed by marker id ("TICKER|YYYY-MM-DD"); several can share a day.
  const [groups, setGroups] = useState<Record<string, Annotation[]>>({})
  const [popup, setPopup] = useState<Popup | null>(null)
  const fill = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string>()

  const compare = selected.length > 1
  const tickers = compare ? selected.slice(0, MAX_SELECTED) : focused ? [focused] : []
  const axis: PriceAxis = axisChoice === 'auto' ? (tickers.length > 1 ? 'log' : 'usd') : axisChoice
  const yoy = mode === 'price' && axis === 'yoy'
  const start = rangeStart(range)
  const key = tickers.join(',')

  useEffect(() => {
    if (!key) return
    let cancelled = false
    // YoY needs prices from a year before the range to compare against.
    const fetchFrom = yoy ? yearBefore(start) : start
    Promise.all(
      key.split(',').map((t) =>
        Promise.all([
          api.get<PriceSeries>(`/instruments/${t}/prices?mode=${mode}&start=${fetchFrom}`),
          api.get<Annotation[]>(`/instruments/${t}/annotations`),
        ]),
      ),
    )
      .then((results) => {
        if (cancelled) return
        const found: Record<string, Annotation[]> = {}
        setLines(
          results.map(([s, annotations]) => {
            const points = yoy ? yoyGrowth(s.points, start) : s.points
            const days = points.map((p) => p.date)
            const markerIds = new Set<string>()
            for (const a of annotations) {
              const day = a.annotation_date && snapToTradingDay(a.annotation_date, days)
              if (!day) continue // undated, or outside the plotted range
              const id = `${s.ticker}|${day}`
              markerIds.add(id)
              ;(found[id] ??= []).push(a)
            }
            return {
              name: s.ticker,
              points,
              markers: [...markerIds].map((id) => ({ id, date: id.split('|')[1] })),
            }
          }),
        )
        setGroups(found)
        setError(undefined)
      })
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [key, mode, start, yoy, annotationsVersion])

  // Escape closes the popup.
  useEffect(() => {
    if (!popup) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPopup(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [popup])

  const shown = popup ? groups[popup.id] : undefined
  const popupTicker = popup?.id.split('|')[0]

  return (
    <section className="panel chart-panel">
      <header className="panel-header">
        <div className="legend">
          {tickers.length === 0 && <span className="muted">Select a stock to see its chart</span>}
          {tickers.map((t, i) => (
            <span key={t} className="legend-item" style={{ color: LINE_COLORS[i] }}>
              {t}
            </span>
          ))}
          {tickers.length === 1 && (
            <button className="small" onClick={() => onOpenCard(tickers[0])}>
              ⓘ Details &amp; annotations
            </button>
          )}
        </div>
        <div className="controls">
          {mode === 'price' && (
            <div className="button-group" title="Price axis">
              {AXES.map((a) => (
                <button key={a.axis} className={a.axis === axis ? 'active' : ''} onClick={() => setAxisChoice(a.axis)}>
                  {a.label}
                </button>
              ))}
            </div>
          )}
          <div className="button-group">
            {MODES.map((m) => (
              <button key={m.mode} className={m.mode === mode ? 'active' : ''} onClick={() => setMode(m.mode)}>
                {m.label}
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
      {error && <p className="error">{error}</p>}
      <div className="chart-fill" ref={fill}>
        <LineChart
          lines={key ? lines : NO_LINES}
          format={mode === 'price' && !yoy ? 'price' : 'percent'}
          scale={mode === 'price' && axis === 'log' ? 'log' : 'normal'}
          onMarkerClick={(id, point) => {
            const width = fill.current?.clientWidth ?? 0
            setPopup(id && point ? { id, x: point.x, y: point.y, flip: point.x > width / 2, width } : null)
          }}
        />
        {popup && shown && popupTicker && (
          <div
            className="annotation-popup"
            style={
              popup.flip
                ? { right: popup.width - popup.x + 12, top: Math.max(popup.y - 12, 0) }
                : { left: popup.x + 12, top: Math.max(popup.y - 12, 0) }
            }
          >
            <header>
              <strong>
                {popupTicker} · 📍 {popup.id.split('|')[1]}
              </strong>
              <button className="icon" onClick={() => setPopup(null)} aria-label="Close">
                ×
              </button>
            </header>
            <ul>
              {shown.map((a) => (
                <li key={a.id}>
                  <p>{a.body}</p>
                  <span className="muted">
                    {a.author} · {new Date(a.created_at).toLocaleDateString()}
                    {a.edited_at && ` · edited ${shortDate(a.edited_at)}`}
                  </span>
                </li>
              ))}
            </ul>
            <button
              className="small"
              onClick={() => {
                setPopup(null)
                onOpenCard(popupTicker)
              }}
            >
              Open details &amp; annotations
            </button>
          </div>
        )}
      </div>
      <p className="hint">
        <strong>Axis:</strong> {axisCaption(mode, axis, start)}
        {tickers.length < 2 &&
          ` · Tick up to ${MAX_SELECTED} rows in the Compare column (or ⌘/Ctrl-click) to chart them together.`}
      </p>
    </section>
  )
}
