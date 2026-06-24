// search-ui/src/components/CpvMiller.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CpvMiller from './CpvMiller.jsx'

describe('CpvMiller', () => {
  it('shows division column and a search box', () => {
    render(<CpvMiller value={[]} onChange={() => {}} />)
    expect(screen.getByPlaceholderText(/buscar/i)).toBeInTheDocument()
  })
  it('renders selected codes as chips with remove', () => {
    const onChange = vi.fn()
    render(<CpvMiller value={['45000000']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /quitar/i }))
    expect(onChange).toHaveBeenCalledWith([])
  })
})
