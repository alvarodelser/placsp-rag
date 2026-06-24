// search-ui/src/components/FilterWorkspace.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FilterWorkspace from './FilterWorkspace.jsx'
import { EMPTY } from '../filters.js'

const base = {
  filters: EMPTY, patch: () => {}, setList: () => {},
  facetsData: { nuts: {}, dates: { publication: [], plazo: [] } },
  total: 42, previewResults: [], loading: false,
}

describe('FilterWorkspace', () => {
  it('shows category list, live count, and closes', () => {
    const onClose = vi.fn()
    render(<FilterWorkspace {...base} onClose={onClose} />)
    expect(screen.getByRole('button', { name: /CPV/i })).toBeInTheDocument()
    expect(screen.getByText('42 resultados')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /cerrar/i }))
    expect(onClose).toHaveBeenCalled()
  })
  it('switches the center pane when a category is chosen', () => {
    render(<FilterWorkspace {...base} onClose={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /ubicación/i }))
    expect(screen.getByRole('button', { name: /comunidades/i })).toBeInTheDocument()
  })
})
