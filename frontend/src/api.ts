// REST client with API-token support (token stored in localStorage)

const TOKEN_KEY = 'srsran_api_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request(path: string, method: 'GET' | 'POST'): Promise<any> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token && method === 'POST') {
    headers['X-API-Token'] = token
  }
  const resp = await fetch(path, { method, headers })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* ignore */ }
    throw new ApiError(resp.status, detail)
  }
  return resp.json()
}

export function apiGet(path: string): Promise<any> {
  return request(path, 'GET')
}

export function apiPost(path: string): Promise<any> {
  return request(path, 'POST')
}
