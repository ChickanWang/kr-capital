/** Chart range buttons shared by the price and portfolio charts. "All" is everything stored. */
export const RANGES = ['1M', '3M', 'YTD', '1Y', 'All'] as const
export type Range = (typeof RANGES)[number]

/** A date before any stored data; the API returns whatever exists from there on. */
const BEGINNING = '2000-01-01'

/** First date (YYYY-MM-DD) of a range ending today. */
export function rangeStart(range: Range): string {
  if (range === 'All') return BEGINNING
  const d = new Date()
  if (range === 'YTD') return `${d.getFullYear()}-01-01`
  d.setMonth(d.getMonth() - { '1M': 1, '3M': 3, '1Y': 12 }[range])
  return d.toISOString().slice(0, 10)
}

/** What a return over this range is called, e.g. "1Y return" or "Total return". */
export function returnLabel(range: Range): string {
  return range === 'All' ? 'Total return' : `${range} return`
}
