export const importStatuses = {
  uploaded: 'Recebida',
  processing: 'Em análise',
  review: 'Em revisão',
  completed: 'Concluída',
  failed: 'Com falha',
  cancelled: 'Cancelada',
}

export const rowStatuses = {
  pending: 'Aguardando revisão',
  invalid: 'Inválido',
  duplicate_candidate: 'Possível duplicata',
  imported: 'Lançamento criado',
  ignored: 'Ignorado',
}

export const importErrors = {
  column_count: 'Quantidade de colunas diferente do cabeçalho.',
  invalid_date: 'Data inválida.',
  date_not_after_opening: 'Data anterior ou igual à abertura da conta.',
  invalid_description: 'Descrição ausente, longa ou com caracteres não permitidos.',
  invalid_amount: 'Valor inválido, zero ou fora do limite.',
  invalid_external_id: 'Referência do arquivo inválida.',
}

export function emptyMapping() {
  return {
    date_column: '',
    description_column: '',
    amount_column: '',
    debit_column: '',
    credit_column: '',
    external_id_column: '',
    date_format: '',
    money_format: '',
    mode: 'signed',
  }
}

export function mappingInput(value, width) {
  const columns = []
  const column = (name, optional = false) => {
    const raw = value[name]
    if (optional && raw === '') return null
    if (!/^(?:[0-9]|[12][0-9]|3[01])$/.test(raw) || Number(raw) >= width)
      throw new Error('Selecione todas as colunas necessárias.')
    const index = Number(raw)
    if (columns.includes(index)) throw new Error('Cada campo deve usar uma coluna diferente.')
    columns.push(index)
    return index
  }
  if (
    !['iso', 'day-first'].includes(value.date_format) ||
    !['decimal-dot', 'decimal-comma'].includes(value.money_format)
  )
    throw new Error('Escolha os formatos de data e de valor.')
  if (!['signed', 'split'].includes(value.mode))
    throw new Error('Escolha como os valores estão organizados.')
  return {
    date_column: column('date_column'),
    description_column: column('description_column'),
    amount_column: value.mode === 'signed' ? column('amount_column') : null,
    debit_column: value.mode === 'split' ? column('debit_column') : null,
    credit_column: value.mode === 'split' ? column('credit_column') : null,
    external_id_column: column('external_id_column', true),
    date_format: value.date_format,
    money_format: value.money_format,
  }
}

export async function csvFileSource(file) {
  if (!file || file.size === 0) throw new Error('Selecione um arquivo CSV que não esteja vazio.')
  if (file.size > 1024 * 1024) throw new Error('O CSV deve ter no máximo 1 MiB.')
  if (
    Array.from(file.name).length < 5 ||
    Array.from(file.name).length > 255 ||
    !/\.csv$/i.test(file.name) ||
    /[/\\:]|\p{C}/u.test(file.name)
  )
    throw new Error('Use um nome de arquivo CSV sem caminhos ou caracteres não permitidos.')
  let bytes
  try {
    bytes = new Uint8Array(await file.arrayBuffer())
  } catch {
    throw new Error('Não foi possível ler o arquivo. Selecione-o novamente.')
  }
  if (!bytes.length || bytes.length > 1024 * 1024)
    throw new Error('O CSV deve ter entre 1 byte e 1 MiB.')
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 32768)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768))
  return btoa(binary)
}
