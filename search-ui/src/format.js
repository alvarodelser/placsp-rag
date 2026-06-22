const eur = new Intl.NumberFormat('es-ES', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

export function money(v) {
  return v == null || v === '' ? null : eur.format(Number(v))
}
