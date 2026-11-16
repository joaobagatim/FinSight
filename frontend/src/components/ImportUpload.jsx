import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { csvFileSource, emptyMapping, mappingInput } from '@/lib/imports'
import { formatDate } from '@/lib/money'

export default function ImportUpload({ ownerId, intent, onIntent, onExpired, onSaved }) {
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [accountId, setAccountId] = useState('')
  const [file, setFile] = useState(null)
  const [delimiter, setDelimiter] = useState('')
  const [inspection, setInspection] = useState(null)
  const [mapping, setMapping] = useState(emptyMapping)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const live = useRef(false),
    working = useRef(false),
    ticket = useRef(0)
  useEffect(() => {
    let current = true
    live.current = true
    api
      .accounts(ownerId)
      .then((result) => {
        if (current) setAccounts(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else
          setError('Não foi possível carregar as contas. Reabra esta área para tentar novamente.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, onExpired])
  function invalidate() {
    ticket.current++
    setInspection(null)
    setMapping(emptyMapping())
    setError('')
  }
  async function moreAccounts() {
    if (working.current) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      const result = await api.accounts(ownerId, accounts.items.length)
      if (live.current)
        setAccounts((previous) => ({ ...result, items: [...previous.items, ...result.items] }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais contas.')
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
  }
  async function inspect(event) {
    event.preventDefault()
    if (working.current || intent || loading) return
    working.current = true
    const request = ++ticket.current
    setBusy(true)
    setError('')
    setInspection(null)
    setMapping(emptyMapping())
    try {
      if (!accountId) throw new Error('Selecione a conta de destino.')
      const content = await csvFileSource(file)
      if (!live.current || request !== ticket.current) return
      const source = {
        account_id: accountId,
        filename: file.name,
        content_base64: content,
        delimiter: delimiter || null,
      }
      const data = await api.inspectImport(ownerId, source)
      if (live.current && request === ticket.current) setInspection({ data, source })
    } catch (failure) {
      if (!live.current || request !== ticket.current) return
      if (failure.status === 401) onExpired()
      else
        setError(
          failure.status === undefined
            ? failure.message
            : failure.status === 422
              ? 'Confira UTF-8, separador, cabeçalhos e limites. Se houver ambiguidade, escolha o separador explicitamente e analise novamente.'
              : failure.status === 404
                ? 'Esta conta não está disponível para o seu acesso.'
                : failure.status === 503
                  ? 'A análise está ocupada ou indisponível. Tente novamente em instantes.'
                  : 'Não foi possível analisar o CSV. Nenhuma prévia foi confirmada por esta análise.',
        )
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
  }
  async function persist(pending) {
    if (working.current) return
    working.current = true
    setBusy(true)
    setError('')
    onIntent(pending)
    let identity = null
    try {
      const result = await api.createImport(ownerId, pending.data, pending.key)
      if (!live.current) return
      onIntent(null)
      identity = result.id
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        onIntent({ ...pending, rejected: [404, 409, 413, 422].includes(failure.status) })
        setError(
          failure.status === 409
            ? 'Esta chave já foi usada com outros dados. Confira o histórico antes de encerrar a tentativa.'
            : [404, 413, 422].includes(failure.status)
              ? 'O envio foi recusado. Confira a conta, o arquivo e o mapeamento antes de iniciar outra tentativa.'
              : 'Não foi possível confirmar o resultado. Confira o histórico ou repita a mesma tentativa; uma falha de resposta não cancela uma prévia já guardada.',
        )
      }
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
    if (identity && live.current) onSaved(identity)
  }
  function save(event) {
    event.preventDefault()
    if (!inspection || intent || working.current) return
    setError('')
    try {
      const data = {
        ...inspection.source,
        mapping: mappingInput(mapping, inspection.data.headers.length),
      }
      const account = accounts.items.find((item) => item.id === data.account_id)
      persist({
        ownerId,
        key: crypto.randomUUID(),
        data,
        accountName: account?.name ?? 'Conta selecionada',
      })
    } catch (failure) {
      setError(failure.message)
    }
  }
  function mappedColumn(field, label, optional = false) {
    return (
      <label className="field" htmlFor={'import-' + field}>
        {label}
        <select
          id={'import-' + field}
          value={mapping[field]}
          required={!optional}
          onChange={(event) =>
            setMapping((previous) => ({ ...previous, [field]: event.target.value }))
          }
        >
          <option value="">{optional ? 'Não usar' : 'Selecione uma coluna'}</option>
          {inspection.data.headers.map((header, index) => (
            <option key={index} value={String(index)}>
              {index + 1} — {header}
            </option>
          ))}
        </select>
      </label>
    )
  }
  return (
    <section
      className="surface account-form import-upload"
      aria-labelledby="import-upload-heading"
      aria-busy={busy || loading}
    >
      <h2 id="import-upload-heading">Nova prévia CSV</h2>
      <p className="field-hint">
        Criar uma prévia não altera seus saldos. Use uma conta de destino e confira o arquivo antes
        de guardar os registros para revisão.
      </p>
      {loading && <p role="status">Carregando contas…</p>}
      {busy && <p role="status">Processando solicitação…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {intent ? (
        <div className="retry-account">
          <p>
            Em conferência: {intent.data.filename}, na conta {intent.accountName}. A tentativa fica
            apenas em memória enquanto você navega. Após recarregar a página, confira o histórico
            antes de iniciar outra.
          </p>
          {!intent.rejected && (
            <Button type="button" disabled={busy || loading} onClick={() => persist(intent)}>
              Conferir e repetir envio da prévia
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={busy || loading}
            onClick={() => {
              onIntent(null)
              setFile(null)
              invalidate()
            }}
          >
            Conferi o histórico: encerrar tentativa de prévia
          </Button>
        </div>
      ) : (
        <>
          <form onSubmit={inspect} aria-label="Analisar CSV">
            <fieldset disabled={busy || loading}>
              <label className="field" htmlFor="import-account">
                Conta de destino
                <select
                  id="import-account"
                  value={accountId}
                  required
                  onChange={(event) => {
                    invalidate()
                    setAccountId(event.target.value)
                  }}
                >
                  <option value="">Selecione uma conta</option>
                  {accounts.items
                    .filter((item) => item.is_active)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
              {accounts.has_more && (
                <Button type="button" variant="outline" onClick={moreAccounts}>
                  Carregar mais contas para CSV
                </Button>
              )}
              <label className="field" htmlFor="import-file">
                Arquivo CSV
                <input
                  id="import-file"
                  type="file"
                  accept=".csv,text/csv"
                  required
                  onChange={(event) => {
                    invalidate()
                    setFile(event.target.files?.[0] ?? null)
                  }}
                  aria-describedby="import-file-hint"
                />
              </label>
              <p className="field-hint" id="import-file-hint">
                UTF-8, até 1 MiB e 5.000 registros. O original é processado em memória; a prévia
                guarda somente os registros interpretados.
              </p>
              <label className="field" htmlFor="import-delimiter">
                Separador do arquivo
                <select
                  id="import-delimiter"
                  value={delimiter}
                  onChange={(event) => {
                    invalidate()
                    setDelimiter(event.target.value)
                  }}
                >
                  <option value="">Identificar pelo cabeçalho</option>
                  <option value=";">Ponto e vírgula (;)</option>
                  <option value=",">Vírgula (,)</option>
                </select>
              </label>
              <Button type="submit">Analisar arquivo</Button>
            </fieldset>
          </form>
          {inspection && (
            <section aria-labelledby="import-mapping-heading">
              <h3 id="import-mapping-heading">Amostra e mapeamento</h3>
              <p>
                {inspection.source.filename}: {inspection.data.total_rows} registros. Abertura da
                conta em {formatDate(inspection.data.opening_date)}. Datas anteriores ou iguais à
                abertura serão marcadas como inválidas.
              </p>
              {inspection.data.matching_files > 0 && (
                <p role="status" className="notice notice-error">
                  Já existem {inspection.data.matching_files} prévia(s) com esse mesmo arquivo nesta
                  conta. Confira o histórico antes de guardar outra; compras idênticas não são
                  removidas automaticamente.
                </p>
              )}
              <div
                className="import-sample-scroll"
                role="region"
                aria-label="Amostra com rolagem horizontal"
                tabIndex={0}
              >
                <table>
                  <caption>Amostra do arquivo (até 5 registros)</caption>
                  <thead>
                    <tr>
                      {inspection.data.headers.map((header, index) => (
                        <th scope="col" key={index}>
                          {index + 1} — {header}
                        </th>
                      ))}
                      <th scope="col">Conferência</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspection.data.sample.map((cells, row) => (
                      <tr key={row}>
                        {inspection.data.headers.map((_, index) => (
                          <td key={index}>
                            {cells[index] === undefined
                              ? 'Ausente'
                              : cells[index].trim()
                                ? cells[index]
                                : 'Vazio'}
                          </td>
                        ))}
                        <td>
                          {cells.length === inspection.data.headers.length
                            ? 'Colunas completas'
                            : 'Quantidade de colunas diferente'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <form onSubmit={save} aria-label="Mapear colunas do CSV">
                <fieldset disabled={busy}>
                  {mappedColumn('date_column', 'Coluna de data')}
                  {mappedColumn('description_column', 'Coluna de descrição')}
                  <label className="field" htmlFor="import-values">
                    Organização dos valores
                    <select
                      id="import-values"
                      value={mapping.mode}
                      onChange={(event) =>
                        setMapping((previous) => ({ ...previous, mode: event.target.value }))
                      }
                    >
                      <option value="signed">Uma coluna com valores positivos e negativos</option>
                      <option value="split">Débito e crédito em colunas separadas</option>
                    </select>
                  </label>
                  {mapping.mode === 'signed' ? (
                    mappedColumn('amount_column', 'Coluna de valor')
                  ) : (
                    <>
                      {mappedColumn('debit_column', 'Coluna de débito')}
                      {mappedColumn('credit_column', 'Coluna de crédito')}
                    </>
                  )}
                  <label className="field" htmlFor="import-date-format">
                    Formato das datas
                    <select
                      id="import-date-format"
                      required
                      value={mapping.date_format}
                      onChange={(event) =>
                        setMapping((previous) => ({ ...previous, date_format: event.target.value }))
                      }
                    >
                      <option value="">Selecione o formato</option>
                      <option value="day-first">Dia/mês/ano — 02/01/2026</option>
                      <option value="iso">Ano-mês-dia — 2026-01-02</option>
                    </select>
                  </label>
                  <label className="field" htmlFor="import-money-format">
                    Formato dos valores
                    <select
                      id="import-money-format"
                      required
                      value={mapping.money_format}
                      onChange={(event) =>
                        setMapping((previous) => ({
                          ...previous,
                          money_format: event.target.value,
                        }))
                      }
                    >
                      <option value="">Selecione o formato</option>
                      <option value="decimal-comma">Vírgula decimal — 1.234,56</option>
                      <option value="decimal-dot">Ponto decimal — 1234.56</option>
                    </select>
                  </label>
                  {mappedColumn('external_id_column', 'Coluna de referência (opcional)', true)}
                  <p className="field-hint">
                    Valores com sinal indicam receita ou despesa; com débito/crédito, somente um
                    lado pode ser positivo. Confira transferências e estornos no arquivo: o sinal
                    sozinho não comprova a natureza do movimento.
                  </p>
                  <Button type="submit">Guardar prévia para revisão</Button>
                </fieldset>
              </form>
            </section>
          )}
        </>
      )}
    </section>
  )
}
