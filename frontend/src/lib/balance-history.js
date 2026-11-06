// Civil dates use UTC only for calendar arithmetic, never to shift a stored date.
export function dayNumber(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(parsed.getTime()) || parsed.getUTCFullYear() < 1) return null
  if (parsed.toISOString().slice(0, 10) !== value) return null
  return parsed.getTime() / 86400000
}

export function shiftDay(value, offset) {
  const day = dayNumber(value)
  if (day === null) throw new Error('Invalid civil date')
  return new Date((day + offset) * 86400000).toISOString().slice(0, 10)
}

export function chartPositions(points) {
  if (!points.length) throw new Error('Missing daily balances')
  const values = points.map((point) => {
    if (!/^-?\d+\.\d{2}$/.test(point.balance)) throw new Error('Invalid decimal balance')
    return BigInt(point.balance.replace('.', ''))
  })
  const min = values.reduce((left, right) => (left < right ? left : right))
  const max = values.reduce((left, right) => (left > right ? left : right))
  const span = max - min
  return points.map((point, index) => ({
    ...point,
    isMinimum: values[index] === min,
    isMaximum: values[index] === max,
    // Convert only a bounded pixel-position ratio to Number, never a monetary amount.
    position: span === 0n ? 50 : Number(((values[index] - min) * 1000000n) / span) / 10000,
  }))
}
