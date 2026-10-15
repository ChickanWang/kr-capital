import { useCallback, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { api, type BasketDetail, type InstrumentRow, useFetch } from './api/client'
import { BasketSidebar } from './components/BasketSidebar'
import { CompanyCard } from './components/CompanyCard'
import { type GridRow, InstrumentGrid } from './components/InstrumentGrid'
import { PortfolioPanel } from './components/PortfolioPanel'
import { PriceChart } from './components/PriceChart'
import { MAX_SELECTED } from './constants'
import { useDragSize } from './useDragSize'

const sidebarMax = () => 480
// Room kept above the bottom panel: top bar, basket toolbar, at least ~5 grid rows, drag handle.
const SPACE_ABOVE_BOTTOM = 330
const BOTTOM_MIN = 220
const bottomMax = () => Math.max(BOTTOM_MIN, window.innerHeight - SPACE_ABOVE_BOTTOM)

function subscribeResize(onChange: () => void) {
  window.addEventListener('resize', onChange)
  return () => window.removeEventListener('resize', onChange)
}
const windowHeight = () => window.innerHeight
const sidebarFromPointer = (e: MouseEvent) => e.clientX
const bottomFromPointer = (e: MouseEvent) => window.innerHeight - e.clientY - 12

/** One screen: baskets on the left, the universe grid with a chart panel below (prices, or the
 * active portfolio), and a company card drawer on double-click. Sidebar and bottom panel are
 * resizable for the current page; a refresh restores the default layout. */
export default function App() {
  const instruments = useFetch<InstrumentRow[]>('/instruments')
  const [focused, setFocused] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [card, setCard] = useState<string | null>(null)
  // Bumped when an annotation changes, so the chart's dots refresh.
  const [annotationsVersion, setAnnotationsVersion] = useState(0)
  const [basketId, setBasketId] = useState<string | null>(null)
  const basket = useFetch<BasketDetail>(basketId ? `/baskets/${basketId}` : null)
  const [view, setView] = useState<'members' | 'all'>('members')
  const [notice, setNotice] = useState<string>()
  const noticeTimer = useRef<number>(undefined)
  const [sidebarWidth, startSidebarDrag] = useDragSize({
    initial: 240,
    min: 180,
    max: sidebarMax,
    fromPointer: sidebarFromPointer,
    cursor: 'col-resize',
  })
  const [bottomHeight, startBottomDrag] = useDragSize({
    initial: 340,
    min: BOTTOM_MIN,
    max: bottomMax,
    fromPointer: bottomFromPointer,
    cursor: 'row-resize',
  })
  // Re-clamp the remembered height when the window shrinks, so the panel never covers the grid.
  const viewportHeight = useSyncExternalStore(subscribeResize, windowHeight)
  const bottom = Math.min(bottomHeight, Math.max(BOTTOM_MIN, viewportHeight - SPACE_ABOVE_BOTTOM))
  // 'auto' shows the portfolio when the active basket is one, otherwise stock prices.
  const [bottomView, setBottomView] = useState<'auto' | 'stocks' | 'portfolio'>('auto')

  const showNotice = useCallback((message: string) => {
    setNotice(message)
    window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => setNotice(undefined), 4000)
  }, [])

  const activateBasket = (id: string | null) => {
    setBasketId(id)
    setView('members')
    setBottomView('auto')
  }

  const memberIds = useMemo(
    () => new Set(basket.data?.members.map((m) => m.instrument_id) ?? []),
    [basket.data],
  )
  // An empty basket always shows every stock, so there is something to star.
  const basketEmpty = basketId !== null && basket.data !== undefined && memberIds.size === 0
  const showAll = basketEmpty || view === 'all'
  const isPortfolio =
    !!basket.data && basket.data.members.length > 0 && basket.data.members.every((m) => m.target_quantity !== null)
  const showPortfolio = isPortfolio && bottomView !== 'stocks'

  // With a basket active, rows carry an in_basket flag; "Members only" shows just those.
  const rows = useMemo<GridRow[]>(() => {
    const all = instruments.data ?? []
    if (!basketId || !basket.data) return all
    const flagged = all.map((r) => ({ ...r, in_basket: memberIds.has(r.instrument_id) }))
    return showAll ? flagged : flagged.filter((r) => r.in_basket)
  }, [instruments.data, basketId, basket.data, memberIds, showAll])

  const toggleMember = useCallback(
    async (row: GridRow) => {
      if (!basketId) return
      // Starring from "All stocks" (including an empty basket's forced view) stays there, so the
      // list doesn't collapse to members after the first star.
      if (showAll) setView('all')
      try {
        if (row.in_basket) await api.delete(`/baskets/${basketId}/members/${row.ticker}`)
        else await api.post(`/baskets/${basketId}/members`, { ticker: row.ticker })
        basket.reload()
      } catch (e) {
        showNotice((e as Error).message)
      }
    },
    [basketId, basket, showNotice, showAll],
  )

  return (
    <div className="app" style={{ gridTemplateColumns: `${sidebarWidth}px minmax(0, 1fr)` }}>
      <header className="topbar">
        <h1>KR Capital · S&amp;P 100 Watchlist</h1>
        <span className="muted">
          {basketId && basket.data ? `Basket: ${basket.data.name} · ` : ''}
          {rows.length} instruments · daily closes, split-adjusted
        </span>
        {notice && <span className="notice">{notice}</span>}
      </header>
      <BasketSidebar
        universe={instruments.data ?? []}
        activeId={basketId}
        active={basket}
        onActivate={activateBasket}
      />
      <div
        className="resizer"
        style={{ left: sidebarWidth - 3 }}
        onMouseDown={startSidebarDrag}
        title="Drag to resize the sidebar"
      />
      <main className="main">
        {instruments.error && <p className="error">Could not load instruments: {instruments.error}</p>}
        <div className="grid-area">
          {basketId && basket.data && (
            <div className="grid-toolbar">
              <div className="button-group">
                <button
                  className={showAll ? '' : 'active'}
                  disabled={basketEmpty}
                  onClick={() => setView('members')}
                >
                  Members only ({memberIds.size})
                </button>
                <button className={showAll ? 'active' : ''} onClick={() => setView('all')}>
                  All stocks
                </button>
              </div>
              <span className="muted">Click ☆ to add a stock to “{basket.data.name}”, ★ to remove it.</span>
            </div>
          )}
          <InstrumentGrid
            rows={rows}
            onFocus={setFocused}
            onSelect={setSelected}
            onOpen={setCard}
            onLimit={() =>
              showNotice(`You can compare up to ${MAX_SELECTED} stocks. Deselect one to pick another.`)
            }
            onToggleMember={basketId ? toggleMember : undefined}
            emptyMessage="No instruments yet. Load data with the ETL (see README)."
          />
        </div>
        <div className="row-resizer" onMouseDown={startBottomDrag} title="Drag to resize the chart" />
        <div className="bottom" style={{ height: bottom }}>
          {isPortfolio && (
            <div className="button-group bottom-tabs">
              <button className={showPortfolio ? '' : 'active'} onClick={() => setBottomView('stocks')}>
                Stocks
              </button>
              <button className={showPortfolio ? 'active' : ''} onClick={() => setBottomView('portfolio')}>
                Portfolio
              </button>
            </div>
          )}
          {showPortfolio && basket.data ? (
            <PortfolioPanel
              // Remount when holdings change, so the returns are refetched.
              key={JSON.stringify(basket.data.members)}
              basket={basket.data}
              universe={instruments.data ?? []}
            />
          ) : (
            <PriceChart
              focused={focused}
              selected={selected}
              annotationsVersion={annotationsVersion}
              onOpenCard={setCard}
            />
          )}
        </div>
      </main>
      {card && (
        <CompanyCard
          key={card}
          ticker={card}
          row={instruments.data?.find((r) => r.ticker === card)}
          onClose={() => setCard(null)}
          onAnnotationsChanged={() => {
            setAnnotationsVersion((v) => v + 1)
            instruments.reload() // refresh the grid's annotation counts
          }}
        />
      )}
    </div>
  )
}
