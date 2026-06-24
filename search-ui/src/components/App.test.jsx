import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../App.jsx'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
    const body = String(url).includes('/api/facets')
      ? { total: 0, nuts: {}, dates: { publication: [], plazo: [] } }
      : { query: '', mode: 'browse', count: 0, total: 0, offset: 0, results: [], errors: null }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  })
  if (!globalThis.crypto?.randomUUID) {
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => 'x', getRandomValues: () => {} },
      configurable: true,
    })
  }
})

describe('App', () => {
  it('shows the Filtros button and opens the workspace', async () => {
    render(<App />)
    const open = await screen.findByRole('button', { name: /filtros/i })
    fireEvent.click(open)
    expect(await screen.findByRole('dialog', { name: /filtros/i })).toBeInTheDocument()
  })
})
