// Typed access to the backend. Types come from `npm run gen:types` (backend/openapi.json), so an API
// change the frontend doesn't match fails the type check.
import { useCallback, useEffect, useState } from 'react'
import type { components } from './schema'

type Schemas = components['schemas']
export type InstrumentRow = Schemas['InstrumentRow']
export type Metadata = Schemas['Metadata']
export type PriceSeries = Schemas['PriceSeries']
export type Annotation = Schemas['AnnotationOut']
export type Basket = Schemas['BasketOut']
export type BasketDetail = Schemas['BasketDetail']
export type Member = Schemas['MemberOut']
export type PortfolioPoint = Schemas['PortfolioPoint']
export type PriceMode = PriceSeries['mode']

const BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().then((j) => j.detail, () => response.statusText)
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  delete: (path: string) => request<void>('DELETE', path),
}

export interface Fetched<T> {
  data: T | undefined
  error: string | undefined
  loading: boolean
  reload: () => void
}

/** GET `path` whenever it changes (pass null to skip). `reload()` fetches it again. */
export function useFetch<T>(path: string | null): Fetched<T> {
  const [version, setVersion] = useState(0)
  const request = path === null ? null : `${path}#${version}`
  // The last settled request; loading until it matches the current one.
  const [settled, setSettled] = useState<{ request: string; data?: T; error?: string }>()

  useEffect(() => {
    if (path === null || request === null) return
    let cancelled = false
    api
      .get<T>(path)
      .then((data) => !cancelled && setSettled((prev) => ({ request, data: data ?? prev?.data })))
      .catch((e: Error) => !cancelled && setSettled((prev) => ({ request, data: prev?.data, error: e.message })))
    return () => {
      cancelled = true
    }
  }, [path, request])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  if (request === null) return { data: undefined, error: undefined, loading: false, reload }
  // Keep showing the previous data while a reload is in flight, so lists don't flash empty.
  const samePath = settled?.request.startsWith(`${path}#`)
  return {
    data: samePath ? settled?.data : undefined,
    error: settled?.request === request ? settled.error : undefined,
    loading: settled?.request !== request,
    reload,
  }
}
