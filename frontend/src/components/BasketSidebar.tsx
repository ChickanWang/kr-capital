import { useState } from 'react'
import {
  api,
  type Basket,
  type BasketDetail,
  type Fetched,
  type InstrumentRow,
  useFetch,
} from '../api/client'

/** Baskets: named groups of stocks. Selecting one filters the grid to its members; stocks are added
 * with the search box. Giving every member a target quantity turns it into a portfolio with a
 * returns chart. */
export function BasketSidebar({
  universe,
  activeId,
  active,
  onActivate,
}: {
  universe: InstrumentRow[]
  activeId: string | null
  active: Fetched<BasketDetail>
  onActivate: (id: string | null) => void
}) {
  const baskets = useFetch<Basket[]>('/baskets')
  const [name, setName] = useState('')
  const [error, setError] = useState<string>()

  async function run(action: () => Promise<unknown>) {
    try {
      await action()
      setError(undefined)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const create = () =>
    run(async () => {
      const basket = await api.post<Basket>('/baskets', { name: name.trim() })
      setName('')
      baskets.reload()
      onActivate(basket.id)
    })

  const remove = (basket: Basket) =>
    run(async () => {
      if (!confirm(`Delete basket "${basket.name}"?`)) return
      await api.delete(`/baskets/${basket.id}`)
      if (basket.id === activeId) onActivate(null)
      baskets.reload()
    })

  return (
    <nav className="sidebar">
      <h3>Baskets</h3>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create()
        }}
      >
        <input value={name} placeholder="New basket name" onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={!name.trim()}>
          +
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      <ul className="basket-list">
        {baskets.data?.map((b) => (
          <li key={b.id} className={b.id === activeId ? 'active' : ''}>
            <button className="link" onClick={() => onActivate(b.id === activeId ? null : b.id)}>
              {b.name}
            </button>
            <button className="icon" onClick={() => remove(b)} aria-label={`Delete ${b.name}`}>
              ×
            </button>
          </li>
        ))}
        {baskets.data?.length === 0 && <li className="muted">No baskets yet</li>}
      </ul>

      {activeId && active.data && (
        <ActiveBasket
          key={active.data.id}
          basket={active.data}
          universe={universe}
          reload={active.reload}
          run={run}
        />
      )}
    </nav>
  )
}

function ActiveBasket({
  basket,
  universe,
  reload,
  run,
}: {
  basket: BasketDetail
  universe: InstrumentRow[]
  reload: () => void
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const members = basket.members
  const memberTickers = new Set(members.map((m) => m.ticker))
  const isPortfolio = members.length > 0 && members.every((m) => m.target_quantity !== null)

  const addStock = (ticker: string) =>
    run(async () => {
      await api.post(`/baskets/${basket.id}/members`, { ticker })
      reload()
    })

  const setQuantity = (ticker: string, value: string) =>
    run(async () => {
      const quantity = value.trim() === '' ? null : Number(value)
      if (quantity !== null && (!Number.isFinite(quantity) || quantity === 0)) {
        throw new Error('Quantity must be a non-zero number')
      }
      await api.post(`/baskets/${basket.id}/members`, {
        ticker,
        target_quantity: quantity,
      })
      reload()
    })

  const removeMember = (ticker: string) =>
    run(async () => {
      await api.delete(`/baskets/${basket.id}/members/${ticker}`)
      reload()
    })

  return (
    <section className="active-basket">
      <h3>{basket.name}</h3>
      <StockSearch candidates={universe.filter((r) => !memberTickers.has(r.ticker))} onPick={addStock} />
      <table className="members">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Qty</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.instrument_id}>
              <td>{m.ticker ?? '–'}</td>
              <td>
                <input
                  className="qty"
                  defaultValue={m.target_quantity ?? ''}
                  placeholder="–"
                  onBlur={(e) => {
                    const current = m.target_quantity === null ? '' : String(Number(m.target_quantity))
                    if (m.ticker && e.target.value.trim() !== current) setQuantity(m.ticker, e.target.value)
                  }}
                />
              </td>
              <td>
                {m.ticker && (
                  <button className="icon" onClick={() => removeMember(m.ticker!)} aria-label="Remove">
                    ×
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {members.length === 0 && <p className="muted">Click ☆ in the grid, or search above, to add stocks.</p>}
      {members.length > 0 && !isPortfolio && (
        <p className="muted">Give every member a quantity to see portfolio returns.</p>
      )}
      {isPortfolio && <p className="muted">Portfolio: see value, returns and holdings below the grid.</p>}
    </section>
  )
}

const MAX_MATCHES = 8

/** Type a ticker or company name; matching stocks not yet in the basket appear below. Click one,
 * or press Enter for the first match, to add it. */
function StockSearch({
  candidates,
  onPick,
}: {
  candidates: InstrumentRow[]
  onPick: (ticker: string) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const matches = q
    ? candidates
        .filter((r) => r.ticker.toLowerCase().startsWith(q) || (r.name ?? '').toLowerCase().includes(q))
        // Ticker matches first, then alphabetical.
        .sort(
          (a, b) =>
            Number(!a.ticker.toLowerCase().startsWith(q)) - Number(!b.ticker.toLowerCase().startsWith(q)) ||
            a.ticker.localeCompare(b.ticker),
        )
        .slice(0, MAX_MATCHES)
    : []

  const pick = (ticker: string) => {
    onPick(ticker)
    setQuery('')
  }

  return (
    <div className="stock-search">
      <input
        value={query}
        placeholder="Add stock: ticker or name"
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && matches[0] && pick(matches[0].ticker)}
      />
      {matches.length > 0 && (
        <ul className="matches">
          {matches.map((r) => (
            <li key={r.instrument_id}>
              <button className="link" onClick={() => pick(r.ticker)}>
                <strong>{r.ticker}</strong> <span className="muted">{r.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {q && matches.length === 0 && <p className="muted">No matching stocks outside this basket</p>}
    </div>
  )
}
