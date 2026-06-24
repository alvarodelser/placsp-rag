// search-ui/src/components/LiveResults.test.jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import LiveResults from './LiveResults.jsx'

describe('LiveResults', () => {
  it('shows the total and preview titles', () => {
    render(<LiveResults total={1284} loading={false}
      results={[{ syndication_id: '1', title: 'Limpieza' }]} />)
    expect(screen.getByText(/1\.?284/)).toBeInTheDocument()
    expect(screen.getByText('Limpieza')).toBeInTheDocument()
  })
})
