import { useMemo, useState } from 'react'
import { api, type InstrumentRow, type Metadata, type Annotation, type PriceSeries, useFetch } from '../api/client'
import { bigMoney, count, pct, price, shortDate, signClass } from '../format'
import { rangeStart } from './ranges'

const IDENTIFIERS: { key: keyof Metadata; label: string }[] = [
  { key: 'ticker', label: 'Ticker' },
  { key: 'figi', label: 'FIGI' },
  { key: 'sic_code', label: 'SIC code' },
  { key: 'sic_description', label: 'Industry' },
  { key: 'primary_exchange', label: 'Exchange' },
  { key: 'currency', label: 'Currency' },
  { key: 'shares_outstanding', label: 'Shares outstanding' },
  { key: 'listing_status', label: 'Status' },
]

/** Every versioned field, with the label used in the history list. */
const TRACKED: { key: keyof Metadata; label: string }[] = [
  ...IDENTIFIERS,
  { key: 'name', label: 'Name' },
  { key: 'description', label: 'Description' },
  { key: 'homepage_url', label: 'Website' },
  { key: 'total_employees', label: 'Employees' },
  { key: 'list_date', label: 'Listed' },
  { key: 'hq_city', label: 'HQ city' },
  { key: 'hq_state', label: 'HQ state' },
]

type HistoryItem = { when: string; text: string; from?: string; to?: string }

/** What changed between consecutive versions, newest first. A field going from empty to a value
 * (e.g. profile fields filled in for the first time) is grouped into one "Added" line, since it isn't
 * a change to the company; a reworded description is summarised rather than diffed. */
function history(versions: Metadata[]): HistoryItem[] {
  const items: HistoryItem[] = []
  versions.slice(1).forEach((next, i) => {
    const prev = versions[i]
    const when = shortDate(next.data_version)
    const added: string[] = []
    for (const { key, label } of TRACKED) {
      if (prev[key] === next[key]) continue
      if (prev[key] === null) added.push(label.toLowerCase())
      else if (key === 'description') items.push({ when, text: 'Description updated' })
      else items.push({ when, text: label, from: show(prev, key), to: show(next, key) })
    }
    if (added.length) items.push({ when, text: `Added: ${added.join(', ')}` })
  })
  return items.reverse()
}

function show(m: Metadata, key: keyof Metadata): string {
  const value = m[key]
  if (value === null || value === undefined) return '–'
  return key === 'shares_outstanding' || key === 'total_employees' ? count(value as number) : String(value)
}

const DESCRIPTION_PREVIEW = 280

/** Drawer with a stock's overview, key figures, identifiers, reference-data history, and annotations. */
export function CompanyCard({
  ticker,
  row,
  onClose,
  onAnnotationsChanged,
}: {
  ticker: string
  /** The stock's grid row, for latest price, returns and market cap. */
  row: InstrumentRow | undefined
  onClose: () => void
  onAnnotationsChanged: () => void
}) {
  const current = useFetch<Metadata>(`/instruments/${ticker}`)
  const versions = useFetch<Metadata[]>(`/instruments/${ticker}/versions`)
  const annotations = useFetch<Annotation[]>(`/instruments/${ticker}/annotations`)
  const year = useFetch<PriceSeries>(`/instruments/${ticker}/prices?mode=price&start=${rangeStart('1Y')}`)
  const [draft, setDraft] = useState('')
  const [annotationDate, setAnnotationDate] = useState('')
  const [saveError, setSaveError] = useState<string>()
  const [fullDescription, setFullDescription] = useState(false)
  // Editing one annotation at a time, and which annotation is awaiting delete confirmation.
  const [editing, setEditing] = useState<{ id: string; body: string; date: string } | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)

  const yearStats = useMemo(() => {
    const closes = year.data?.points.map((p) => p.value) ?? []
    if (closes.length < 2) return null
    return {
      low: Math.min(...closes),
      high: Math.max(...closes),
      oneYear: closes[closes.length - 1] / closes[0] - 1,
    }
  }, [year.data])

  async function addAnnotation() {
    if (!draft.trim()) return
    try {
      await api.post(`/instruments/${ticker}/annotations`, { body: draft.trim(), annotation_date: annotationDate || null })
      setDraft('')
      setAnnotationDate('')
      setSaveError(undefined)
      annotations.reload()
      onAnnotationsChanged()
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  async function saveEdit() {
    if (!editing || !editing.body.trim()) return
    try {
      await api.patch(`/instruments/${ticker}/annotations/${editing.id}`, {
        body: editing.body.trim(),
        annotation_date: editing.date || null,
      })
      setEditing(null)
      setSaveError(undefined)
      annotations.reload()
      onAnnotationsChanged()
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  async function deleteAnnotation(id: string) {
    try {
      await api.delete(`/instruments/${ticker}/annotations/${id}`)
      setConfirmingDelete(null)
      setSaveError(undefined)
      annotations.reload()
      onAnnotationsChanged()
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  const m = current.data
  const changes = versions.data ? history(versions.data) : []
  const description = m?.description ?? ''
  const longDescription = description.length > DESCRIPTION_PREVIEW
  const hq = [m?.hq_city, m?.hq_state].filter(Boolean).join(', ')

  return (
    <aside className="drawer">
      <header className="drawer-header">
        <div>
          <h2>{ticker}</h2>
          {m && <p className="muted">{m.name}</p>}
          {m?.homepage_url && (
            <a href={m.homepage_url} target="_blank" rel="noreferrer">
              {m.homepage_url.replace(/^https?:\/\/(www\.)?/, '')}
            </a>
          )}
        </div>
        <button className="icon" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      {current.error && <p className="error">{current.error}</p>}

      {m && (
        <section>
          <h3>Overview</h3>
          {description ? (
            <p className="description">
              {fullDescription || !longDescription ? description : `${description.slice(0, DESCRIPTION_PREVIEW)}…`}{' '}
              {longDescription && (
                <button className="link inline" onClick={() => setFullDescription((v) => !v)}>
                  {fullDescription ? 'less' : 'more'}
                </button>
              )}
            </p>
          ) : (
            <p className="muted">No description yet; it is filled in by the nightly reference job.</p>
          )}
          <dl className="details">
            <Detail label="Headquarters" value={hq || '–'} />
            <Detail label="Employees" value={count(m.total_employees)} />
            <Detail label="Listed" value={m.list_date ?? '–'} />
          </dl>
        </section>
      )}

      <section>
        <h3>Key figures</h3>
        <dl className="details">
          <Detail label="Last close" value={price(row?.last_price)} annotation={row?.as_of ?? undefined} />
          <Detail label="Market cap" value={bigMoney(row?.market_cap)} />
          <Detail label="1D" value={pct(row?.ret_1d)} tone={row?.ret_1d} />
          <Detail label="YTD" value={pct(row?.ret_ytd)} tone={row?.ret_ytd} />
          <Detail label="1Y" value={pct(yearStats?.oneYear)} tone={yearStats?.oneYear} />
          <Detail
            label="52-week range (closes)"
            value={yearStats ? `${price(yearStats.low)} – ${price(yearStats.high)}` : '–'}
          />
        </dl>
      </section>

      {m && (
        <section>
          <h3>Identifiers &amp; classification</h3>
          <dl className="details">
            {IDENTIFIERS.map(({ key, label }) => (
              <Detail key={key} label={label} value={show(m, key)} />
            ))}
            <Detail label="Data as of" value={shortDate(m.data_version)} />
          </dl>
        </section>
      )}

      <section>
        <h3>History</h3>
        {versions.data && changes.length === 0 && (
          <p className="muted">
            No changes since first recorded on {shortDate(versions.data[0]?.data_version ?? '')}.
          </p>
        )}
        <ul className="history">
          {changes.map((c, i) => (
            <li key={i}>
              <span className="muted">{c.when}</span> {c.text}
              {c.from !== undefined && (
                <>
                  : <s>{c.from}</s> → {c.to}
                </>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Annotations</h3>
        <div className="annotation-form">
          <textarea
            value={draft}
            placeholder="Add an annotation… (⌘/Ctrl+Enter to save)"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && addAnnotation()}
          />
          <div className="annotation-actions">
            <label className="muted" title="Optional: the day this annotation is about, e.g. an earnings date.">
              About date{' '}
              <input type="date" value={annotationDate} onChange={(e) => setAnnotationDate(e.target.value)} />
            </label>
            <button onClick={addAnnotation} disabled={!draft.trim()}>
              Add annotation
            </button>
          </div>
        </div>
        {saveError && <p className="error">{saveError}</p>}
        <ul className="annotations">
          {annotations.data?.map((n) =>
            editing?.id === n.id ? (
              <li key={n.id} className="annotation-editing">
                <textarea
                  autoFocus
                  value={editing.body}
                  onChange={(e) => setEditing({ ...editing, body: e.target.value })}
                  onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && saveEdit()}
                />
                <div className="annotation-actions">
                  <label className="muted">
                    About date{' '}
                    <input
                      type="date"
                      value={editing.date}
                      onChange={(e) => setEditing({ ...editing, date: e.target.value })}
                    />
                  </label>
                  <span className="annotation-buttons">
                    <button onClick={() => setEditing(null)}>Cancel</button>
                    <button className="active" onClick={saveEdit} disabled={!editing.body.trim()}>
                      Save
                    </button>
                  </span>
                </div>
              </li>
            ) : (
              <li key={n.id}>
                {n.annotation_date && <span className="annotation-date">📍 {n.annotation_date}</span>}
                <p>{n.body}</p>
                <div className="annotation-meta">
                  <span className="muted">
                    {n.author} · {new Date(n.created_at).toLocaleString()}
                    {n.edited_at && ` · edited ${shortDate(n.edited_at)}`}
                  </span>
                  {n.can_edit &&
                    (confirmingDelete === n.id ? (
                      <span className="annotation-buttons">
                        Delete?
                        <button className="small" onClick={() => deleteAnnotation(n.id)}>
                          Yes
                        </button>
                        <button className="small" onClick={() => setConfirmingDelete(null)}>
                          No
                        </button>
                      </span>
                    ) : (
                      <span className="annotation-buttons">
                        <button
                          className="icon small-icon"
                          title="Edit annotation"
                          aria-label="Edit annotation"
                          onClick={() => setEditing({ id: n.id, body: n.body, date: n.annotation_date ?? '' })}
                        >
                          ✎
                        </button>
                        <button
                          className="icon small-icon"
                          title="Delete annotation"
                          aria-label="Delete annotation"
                          onClick={() => setConfirmingDelete(n.id)}
                        >
                          🗑
                        </button>
                      </span>
                    ))}
                </div>
              </li>
            ),
          )}
        </ul>
      </section>
    </aside>
  )
}

function Detail({ label, value, tone, annotation }: { label: string; value: string; tone?: number | null; annotation?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={signClass(tone)} title={annotation}>
        {value}
      </dd>
    </div>
  )
}
