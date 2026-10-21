import type { paths } from '@/lib/api/schema'

/**
 * Thin typed wrapper around fetch. Paths and response types come from the backend's
 * OpenAPI schema (regenerate with `make gen-api`), so a backend change that breaks the
 * frontend fails type checking instead of failing at runtime.
 */

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

type GetPath = { [P in keyof paths]: paths[P] extends { get: object } ? P : never }[keyof paths]

type JsonResponse<Op> = Op extends {
  responses: { 200: { content: { 'application/json': infer T } } }
}
  ? T
  : never

export type GetResponse<P extends GetPath> = JsonResponse<paths[P]['get']>

export async function apiGet<P extends GetPath>(
  path: P,
  init?: RequestInit,
): Promise<GetResponse<P>> {
  const res = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, body)
  return body as GetResponse<P>
}
