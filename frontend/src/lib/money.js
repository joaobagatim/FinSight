// Convert and display decimal strings without binary floating-point money operations.
export function parseMoney(value) {
  const text = value.trim()
  if (!/^-?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,2})?$/.test(text)) {
    throw new Error('Use vírgula nos centavos, por exemplo: 1.234,56.')
  }
  const negative = text.startsWith('-')
  const [whole, fraction = ''] = text.replace(/^-/, '').replaceAll('.', '').split(',')
  const integer = whole.replace(/^0+(?=[0-9])/, '')
  if (integer.length > 13) throw new Error('O saldo inicial ultrapassa o limite permitido.')
  const cents = fraction.padEnd(2, '0')
  const sign = negative && !/^0+$/.test(integer + cents) ? '-' : ''
  return `${sign}${integer}.${cents}`
}

export function formatMoney(value) {
  if (typeof value !== 'string' || !/^-?[0-9]+\.[0-9]{2}$/.test(value)) return '—'
  const [whole, fraction] = value.replace(/^-/, '').split('.')
  return `${value.startsWith('-') ? '−' : ''}R$ ${whole.replace(/\B(?=([0-9]{3})+(?![0-9]))/g, '.')},${fraction}`
}

export function formatDate(value) {
  return /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) ? value.split('-').reverse().join('/') : '—'
}

export function today() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
