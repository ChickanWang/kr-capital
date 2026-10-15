import {
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  LineSeries,
  type MouseEventParams,
  PriceScaleMode,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { LINE_COLORS } from './colors'

export interface Line {
  name: string
  points: { date: string; value: number; color?: string }[]
  /** 'bars' draws a histogram (e.g. daily returns), with optional per-point colours. */
  kind?: 'line' | 'bars'
  /** Clickable dots drawn on the line; `date` must be a date the series has. */
  markers?: { id: string; date: string }[]
}

export type AxisScale = 'normal' | 'log'

/** A time-series chart, one series per entry in `lines`. `format` sets how values are labelled;
 * `scale: 'log'` keeps real values on a logarithmic axis (equal distances = equal % moves). */
export function LineChart({
  lines,
  format = 'price',
  scale = 'normal',
  height,
  onMarkerClick,
}: {
  lines: Line[]
  format?: 'price' | 'percent'
  scale?: AxisScale
  /** Fixed height in px; without it the chart fills its container's height. */
  height?: number
  /** Called with a marker's id and click position, or with null when the click wasn't on a marker. */
  onMarkerClick?: (id: string | null, point?: { x: number; y: number }) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  // Always call the latest handler without resubscribing to the chart's events.
  const markerClick = useRef(onMarkerClick)
  useEffect(() => {
    markerClick.current = onMarkerClick
  }, [onMarkerClick])

  useEffect(() => {
    if (!container.current) return
    // Created once; autoSize follows the container, whose height comes from the `height` prop.
    chart.current = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9aa4b2',
        attributionLogo: false,
      },
      grid: { vertLines: { color: '#1f2733' }, horzLines: { color: '#1f2733' } },
      rightPriceScale: { borderColor: '#2a3340' },
      timeScale: { borderColor: '#2a3340' },
    })
    const c = chart.current
    const overMarker = (hovered?: { objectKind: string }) => hovered?.objectKind === 'series-marker'
    const onClick = (param: MouseEventParams) => {
      const info = param.hoveredInfo
      if (overMarker(info) && typeof info?.objectId === 'string') {
        markerClick.current?.(info.objectId, param.point)
      } else {
        markerClick.current?.(null)
      }
    }
    // A pointer cursor over a marker shows that it can be clicked.
    const onMove = (param: MouseEventParams) => {
      if (container.current) container.current.style.cursor = overMarker(param.hoveredInfo) ? 'pointer' : ''
    }
    c.subscribeClick(onClick)
    c.subscribeCrosshairMove(onMove)
    return () => {
      c.unsubscribeClick(onClick)
      c.unsubscribeCrosshairMove(onMove)
      chart.current?.remove()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.priceScale('right').applyOptions({
      mode: scale === 'log' ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    })
  }, [scale])

  useEffect(() => {
    const c = chart.current
    if (!c) return
    const priceFormat =
      format === 'percent'
        ? { type: 'custom' as const, formatter: (v: number) => `${(v * 100).toFixed(2)}%`, minMove: 0.0001 }
        : { type: 'price' as const, precision: 2, minMove: 0.01 }
    const series = lines.map((line, i) => {
      const color = LINE_COLORS[i % LINE_COLORS.length]
      const title = lines.length > 1 ? line.name : ''
      const data = line.points.map((p) => ({ time: p.date as Time, value: p.value, color: p.color }))
      if (line.kind === 'bars') {
        const s = c.addSeries(HistogramSeries, { color, title, priceFormat })
        s.setData(data)
        return s
      }
      const s = c.addSeries(LineSeries, { color, lineWidth: 2, title, priceFormat })
      s.setData(data.map(({ time, value }) => ({ time, value })))
      if (line.markers?.length) {
        const markers = line.markers
          .map((m) => ({
            id: m.id,
            time: m.date as Time,
            position: 'inBar' as const,
            shape: 'circle' as const,
            color: '#f5c542',
            size: 1.5,
          }))
          .sort((a, b) => (a.time < b.time ? -1 : 1))
        createSeriesMarkers(s, markers)
      }
      return s
    })
    c.timeScale().fitContent()
    return () => {
      // On unmount the chart itself may already be removed (its effect cleans up first).
      if (chart.current === c) series.forEach((s) => c.removeSeries(s))
    }
  }, [lines, format])

  return <div ref={container} className="line-chart" style={{ height: height ?? '100%' }} />
}
