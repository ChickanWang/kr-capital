import { type ColDef, type GridApi, type ValueFormatterParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useMemo, useState } from 'react'
import type { BasketDetail, InstrumentRow } from '../api/client'
import { pct, price, signClass } from '../format'
import { gridTheme } from './gridTheme'

interface Holding {
  ticker: string
  name: string | null
  industry: string | null
  quantity: number
  last: number
  value: number
  weight: number
  dayReturn: number | null
  ret1m: number | null
  retYtd: number | null
  contribution: number | null
}

type Formatter = (p: ValueFormatterParams<Holding, number | null>) => string
const signedPct =
  (digits = 2): Formatter =>
  (p) =>
    pct(p.value, digits)
const returnColumn = (field: keyof Holding, headerName: string, headerTooltip?: string): ColDef<Holding> => ({
  field,
  headerName,
  headerTooltip,
  width: 90,
  type: 'rightAligned',
  filter: 'agNumberColumnFilter',
  valueFormatter: signedPct(),
  cellClass: (p) => signClass(p.value as number | null),
})

const COLUMNS: ColDef<Holding>[] = [
  { field: 'ticker', headerName: 'Ticker', width: 90, pinned: 'left' },
  { field: 'name', headerName: 'Name', minWidth: 150, flex: 1 },
  { field: 'industry', headerName: 'Industry', headerTooltip: 'SIC industry from Polygon', minWidth: 150, flex: 1 },
  {
    field: 'quantity',
    headerName: 'Qty',
    width: 80,
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => (p.value == null ? '–' : p.value.toLocaleString('en-US')),
  },
  {
    field: 'last',
    headerName: 'Last',
    width: 95,
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => price(p.value),
  },
  {
    field: 'value',
    headerName: 'Value',
    width: 110,
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    valueFormatter: (p) => price(p.value),
    sort: 'desc',
  },
  {
    field: 'weight',
    headerName: 'Weight',
    width: 85,
    type: 'rightAligned',
    filter: 'agNumberColumnFilter',
    // Filter on percentages as shown (type 10 for 10%), not on the stored fraction.
    filterValueGetter: (p) => (p.data ? p.data.weight * 100 : null),
    valueFormatter: (p) => pct(p.value, 1).replace('+', ''),
  },
  returnColumn('dayReturn', '1D', "Today's move of the stock"),
  returnColumn('ret1m', '1M'),
  returnColumn('retYtd', 'YTD'),
  returnColumn('contribution', 'Contrib.', "The stock's share of today's portfolio return"),
]

/** Totals over the holdings that pass the current filters. */
interface Shown {
  count: number
  weight: number
  contribution: number | null
}

/** A portfolio's holdings as a screener: sort and filter any column or search all of them, with a
 * running total of how much of the portfolio the filtered holdings are. Click a row to open the
 * company card. */
export function HoldingsGrid({
  basket,
  universe,
  onOpen,
}: {
  basket: BasketDetail
  universe: InstrumentRow[]
  onOpen: (ticker: string) => void
}) {
  const holdings = useMemo(() => holdingsOf(basket, universe), [basket, universe])
  const [search, setSearch] = useState('')
  const [shown, setShown] = useState<Shown | null>(null)
  const defaultColDef = useMemo<ColDef>(() => ({ sortable: true, resizable: true, filter: true }), [])

  const recount = useCallback((api: GridApi<Holding>) => {
    const rows: Holding[] = []
    api.forEachNodeAfterFilter((node) => node.data && rows.push(node.data))
    setShown({
      count: rows.length,
      weight: rows.reduce((sum, h) => sum + h.weight, 0),
      contribution: rows.every((h) => h.contribution !== null)
        ? rows.reduce((sum, h) => sum + h.contribution!, 0)
        : null,
    })
  }, [])

  const filtered = shown !== null && shown.count < holdings.length
  return (
    <section className="panel holdings-screener">
      <div className="holdings-toolbar">
        <input
          type="search"
          placeholder="Search holdings…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {shown && (
          <span className={filtered ? '' : 'muted'}>
            {shown.count} of {holdings.length} holdings · {pct(shown.weight, 1).replace('+', '')} of portfolio
            {shown.contribution !== null && (
              <>
                {' · '}
                <span className={signClass(shown.contribution)}>{pct(shown.contribution)}</span> today
              </>
            )}
          </span>
        )}
      </div>
      <div className="grid">
        <AgGridReact<Holding>
          theme={gridTheme}
          rowData={holdings}
          columnDefs={COLUMNS}
          defaultColDef={defaultColDef}
          quickFilterText={search}
          getRowId={(p) => p.data.ticker}
          onRowClicked={(e) => e.data && onOpen(e.data.ticker)}
          onFirstDataRendered={(e) => recount(e.api)}
          onRowDataUpdated={(e) => recount(e.api)}
          onFilterChanged={(e) => recount(e.api)}
          rowClass="clickable-row"
          overlayNoRowsTemplate="No holdings with a quantity yet"
        />
      </div>
    </section>
  )
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
    return [{ row, quantity, last, prevClose }]
  })
  const total = rows.reduce((sum, r) => sum + r.quantity * r.last, 0)
  const prevTotal = rows.every((r) => r.prevClose !== null)
    ? rows.reduce((sum, r) => sum + r.quantity * r.prevClose!, 0)
    : null
  return rows
    .map((r) => ({
      ticker: r.row.ticker,
      name: r.row.name,
      industry: r.row.sic_description,
      quantity: r.quantity,
      last: r.last,
      value: r.quantity * r.last,
      weight: total ? (r.quantity * r.last) / total : 0,
      dayReturn: r.row.ret_1d,
      ret1m: r.row.ret_1m,
      retYtd: r.row.ret_ytd,
      contribution:
        prevTotal && r.prevClose !== null ? (r.quantity * (r.last - r.prevClose)) / prevTotal : null,
    }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
}
