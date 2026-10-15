import {
  colorSchemeDark,
  type ColDef,
  type ICellRendererParams,
  type RowSelectionOptions,
  type SelectionColumnDef,
  type ValueFormatterParams,
  themeQuartz,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useEffect, useMemo, useRef } from 'react'
import type { InstrumentRow } from '../api/client'
import { MAX_SELECTED } from '../constants'
import { bigMoney, pct, price, signClass } from '../format'

const theme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#11161d',
  headerBackgroundColor: '#161c25',
  fontSize: 13,
  spacing: 6,
})

type Formatter = (p: ValueFormatterParams<GridRow, number | null>) => string
const asPct: Formatter = (p) => pct(p.value)
const returnColumn = (field: keyof InstrumentRow, headerName: string): ColDef<GridRow> => ({
  field,
  headerName,
  width: 100,
  type: 'rightAligned',
  valueFormatter: asPct,
  cellClass: (p) => signClass(p.value as number | null),
})

/** A grid row; `in_basket` is set while a basket is active. */
export type GridRow = InstrumentRow & { in_basket?: boolean }

interface GridContext {
  toggleMember: (row: GridRow) => void
  openCard: (ticker: string) => void
}

/** Runs `onClick` from a native listener that stops propagation, so clicking a button in a cell
 * doesn't also select the row or change the chart (AG Grid listens for row clicks natively). */
function useCellClick(onClick: (() => void) | null) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el || !onClick) return
    const handler = (e: MouseEvent) => {
      e.stopPropagation()
      onClick()
    }
    el.addEventListener('click', handler)
    return () => el.removeEventListener('click', handler)
  }, [onClick])
  return ref
}

/** ★ / ☆ toggle for basket membership. */
function StarCell({ data, context }: ICellRendererParams<GridRow, boolean, GridContext>) {
  const ref = useCellClick(data ? () => context.toggleMember(data) : null)
  if (!data) return null
  return (
    <button
      ref={ref}
      className={`star ${data.in_basket ? 'on' : ''}`}
      title={data.in_basket ? 'Remove from basket' : 'Add to basket'}
    >
      {data.in_basket ? '★' : '☆'}
    </button>
  )
}

/** ⓘ: open the company card (details, history, annotations). */
function InfoCell({ data, context }: ICellRendererParams<GridRow, unknown, GridContext>) {
  const ref = useCellClick(data ? () => context.openCard(data.ticker) : null)
  if (!data) return null
  return (
    <button ref={ref} className="cell-icon" title={`Details & annotations for ${data.ticker}`}>
      ⓘ
    </button>
  )
}

/** Annotation count; click to read or add annotations. */
function AnnotationsCell({ data, context }: ICellRendererParams<GridRow, number, GridContext>) {
  const ref = useCellClick(data ? () => context.openCard(data.ticker) : null)
  if (!data) return null
  return (
    <button ref={ref} className={`cell-icon ${data.annotation_count ? 'has-annotations' : ''}`} title="Annotations">
      {data.annotation_count ? `📝 ${data.annotation_count}` : '＋'}
    </button>
  )
}

const INFO_COLUMN: ColDef<GridRow> = {
  colId: 'info',
  headerName: '',
  headerTooltip: 'Company details, history and annotations',
  width: 48,
  pinned: 'left',
  sortable: false,
  filter: false,
  resizable: false,
  cellRenderer: InfoCell,
}

const ANNOTATIONS_COLUMN: ColDef<GridRow> = {
  field: 'annotation_count',
  headerName: 'Annotations',
  headerTooltip: 'Number of annotations; click to read or add',
  width: 120,
  filter: false,
  cellRenderer: AnnotationsCell,
}

const STAR_COLUMN: ColDef<GridRow> = {
  colId: 'in_basket',
  field: 'in_basket',
  headerName: '★',
  headerTooltip: 'In the active basket: click a star to add or remove',
  width: 60,
  pinned: 'left',
  filter: false,
  cellRenderer: StarCell,
}

const COLUMNS: ColDef<GridRow>[] = [
  { field: 'ticker', headerName: 'Ticker', width: 100, pinned: 'left' },
  { field: 'name', headerName: 'Name', flex: 1, minWidth: 180 },
  {
    field: 'last_price',
    headerName: 'Last',
    width: 110,
    type: 'rightAligned',
    valueFormatter: (p) => price(p.value),
  },
  returnColumn('ret_1d', '1D'),
  returnColumn('ret_1m', '1M'),
  returnColumn('ret_ytd', 'YTD'),
  {
    field: 'market_cap',
    headerName: 'Mkt cap',
    width: 110,
    type: 'rightAligned',
    valueFormatter: (p) => bigMoney(p.value),
    sort: 'desc',
  },
  { field: 'as_of', headerName: 'As of', width: 110 },
]

const SELECTION: RowSelectionOptions = {
  mode: 'multiRow',
  checkboxes: true,
  headerCheckbox: false, // "select all" would immediately exceed the cap
  enableClickSelection: true,
}

// The checkbox column selects stocks to chart together; label it so it isn't confused with the
// basket ★ column.
const COMPARE_COLUMN: SelectionColumnDef = {
  headerName: 'Compare',
  headerTooltip: `Tick up to ${MAX_SELECTED} stocks to chart them together`,
  width: 90,
}

/** The universe grid. Click a row to chart it, Ctrl/⌘-click or tick boxes to select up to
 * MAX_SELECTED to compare, double-click to open the company card. With `onToggleMember`, a star
 * column adds or removes stocks from the active basket. */
export function InstrumentGrid({
  rows,
  onFocus,
  onSelect,
  onOpen,
  onLimit,
  onToggleMember,
  emptyMessage,
}: {
  rows: GridRow[]
  emptyMessage: string
  onLimit: () => void
  onToggleMember?: (row: GridRow) => void
  onFocus: (ticker: string) => void
  onSelect: (tickers: string[]) => void
  onOpen: (ticker: string) => void
}) {
  const defaultColDef = useMemo<ColDef>(() => ({ sortable: true, resizable: true, filter: true }), [])
  const columns = useMemo(
    () => [...(onToggleMember ? [STAR_COLUMN] : []), INFO_COLUMN, ...COLUMNS, ANNOTATIONS_COLUMN],
    [onToggleMember],
  )
  // The grid keeps its context object; route through a ref so it always calls the latest handler.
  const toggleRef = useRef(onToggleMember)
  useEffect(() => {
    toggleRef.current = onToggleMember
  }, [onToggleMember])
  const openRef = useRef(onOpen)
  useEffect(() => {
    openRef.current = onOpen
  }, [onOpen])
  const context = useMemo<GridContext>(
    () => ({
      toggleMember: (row) => toggleRef.current?.(row),
      openCard: (ticker) => openRef.current(ticker),
    }),
    [],
  )
  return (
    <div className="grid">
      <AgGridReact<GridRow>
        theme={theme}
        rowData={rows}
        columnDefs={columns}
        context={context}
        defaultColDef={defaultColDef}
        rowSelection={SELECTION}
        selectionColumnDef={COMPARE_COLUMN}
        getRowId={(p) => p.data.instrument_id}
        onRowClicked={(e) => e.data && onFocus(e.data.ticker)}
        onRowDoubleClicked={(e) => e.data && onOpen(e.data.ticker)}
        onRowSelected={(e) => {
          // Over the cap: undo this selection (which fires onSelectionChanged again) and say why.
          if (e.node.isSelected() && e.api.getSelectedNodes().length > MAX_SELECTED) {
            e.node.setSelected(false)
            onLimit()
          }
        }}
        onSelectionChanged={(e) => onSelect(e.api.getSelectedRows().map((r) => r.ticker))}
        overlayNoRowsTemplate={emptyMessage}
      />
    </div>
  )
}
