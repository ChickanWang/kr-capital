export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '–'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

/** $3.42T, $812.5B, $12.0M */
export function bigMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  const units: [number, string][] = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
  ]
  for (const [size, suffix] of units) {
    if (Math.abs(value) >= size) return `$${(value / size).toFixed(size === 1e12 ? 2 : 1)}${suffix}`
  }
  return price(value)
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : value.toLocaleString('en-US')
}

export function shortDate(iso: string): string {
  return iso.slice(0, 10)
}

export function signClass(value: number | null | undefined): string {
  if (!value) return ''
  return value > 0 ? 'up' : 'down'
}
