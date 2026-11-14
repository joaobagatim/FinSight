import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import ImportRowEditor from '@/components/ImportRowEditor'
import { importErrors, importStatuses, rowStatuses, reviewErrors } from '@/lib/imports'
import { formatDate, formatMoney } from '@/lib/money'

export default function ImportPreview({ ownerId, jobId, onExpired, onClose, onUpdated }) {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [editing, setEditing] = useState(null)
  const [selecting, setSelecting] = useState(false)
  const [selectionBlocked, setSelectionBlocked] = useState(false)
  const [notice, setNotice] = useState('')
  const [summaryStale, setSummaryStale] = useState(false)
  const selectionWorking = useRef(false)
  const live = useRef(false),
    fetching = useRef(true),
    heading = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    fetching.current = true
    heading.current?.focus()
    api
      .importJob(ownerId, jobId)
      .then(async (summary) => {
        if (!current) return
        const [rows, account] = await Promise.all([
          api.importRows(ownerId, jobId),
          api.account(ownerId, summary.account_id),
        ])
        if (account.data.id !== summary.account_id) throw new Error('Inconsistent response')
        if (current) setResult({ summary, rows, account: account.data })
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else
          setError(
            failure.status === 404
              ? 'Esta prévia não está disponível para o seu acesso.'
              : 'Não foi possível consultar a prévia. Tente recarregar.',
          )
      })
      .finally(() => {
        if (current) {
          fetching.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, jobId, onExpired, refresh])
  function reload() {
    if (fetching.current || selectionWorking.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    setSelectionBlocked(false)
    setSummaryStale(false)
    setResult(null)
    setRefresh((value) => value + 1)
  }
  async function more() {
    if (fetching.current || selectionWorking.current || !result) return
    fetching.current = true
    setLoading(true)
    setError('')
    try {
      const rows = await api.importRows(ownerId, jobId, result.rows.items.length)
      if (live.current)
        setResult((previous) => ({
          ...previous,
          rows: { ...rows, items: [...previous.rows.items, ...rows.items] },
        }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais registros.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  async function applyRow(row, message) {
    if (!live.current) return
    setResult((previous) => ({
      ...previous,
      rows: {
        ...previous.rows,
        items: previous.rows.items.map((item) => (item.id === row.id ? row : item)),
      },
    }))
    setNotice(message)
    setSummaryStale(true)
    try {
      const summary = await api.importJob(ownerId, jobId)
      if (live.current) {
        setResult((previous) => ({ ...previous, summary }))
        setSummaryStale(false)
        onUpdated?.(summary)
      }
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setSelectionBlocked(true)
        setError(
          'O registro foi salvo, mas não foi possível atualizar os contadores. Recarregue a prévia para continuar.',
        )
      }
    }
  }
  async function edited(row) {
    setEditing(null)
    selectionWorking.current = true
    setSelecting(true)
    try {
      await applyRow(row, 'Registro atualizado e desmarcado. Confira antes de selecionar.')
    } finally {
      selectionWorking.current = false
      if (live.current) setSelecting(false)
    }
  }
  async function choose(row, selected) {
    if (fetching.current || selectionWorking.current || selectionBlocked) return
    selectionWorking.current = true
    setSelecting(true)
    setError('')
    setNotice('')
    try {
      let response
      try {
        response = await api.selectImportRow(ownerId, jobId, row.id, selected, row.etag)
      } catch (failure) {
        if (!live.current) return
        if (failure.status === 401) onExpired()
        else {
          setSelectionBlocked(true)
          setError(
            failure.status === 412
              ? 'A revisão mudou em outra operação. Recarregue a prévia antes de alterar a seleção.'
              : 'Não foi possível conferir o resultado da seleção. Recarregue a prévia para consultar o estado atual.',
          )
        }
        return
      }
      await applyRow(
        response.data,
        selected
          ? 'Registro selecionado para revisão. Nenhum lançamento foi criado.'
          : 'Registro retirado da seleção. Nenhum saldo foi alterado.',
      )
    } finally {
      selectionWorking.current = false
      if (live.current) setSelecting(false)
    }
  }
  if (editing)
    return (
      <ImportRowEditor
        key={editing}
        ownerId={ownerId}
        jobId={jobId}
        rowId={editing}
        onExpired={onExpired}
        onSaved={edited}
        onClose={() => setEditing(null)}
      />
    )
  return (
    <section
      className="surface import-preview"
      aria-labelledby="import-preview-heading"
      aria-busy={loading}
    >
      <h2 id="import-preview-heading" tabIndex={-1} ref={heading}>
        Consulta da prévia
      </h2>
      <p className="field-hint">
        Guardar uma prévia não cria lançamentos. Confira valores, datas, transferências e estornos
        no arquivo original; registros em revisão ainda não representam movimentos confirmados.
      </p>
      {notice && (
        <p role="status" className="notice notice-success">
          {notice}
        </p>
      )}
      <p className="field-hint">
        A seleção começa desmarcada. Corrija os dados e escolha uma categoria compatível para
        selecionar. Selecionar não cria lançamentos; a revisão será revalidada antes de uma
        confirmação financeira.
      </p>
      {loading && <p role="status">Consultando prévia…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && (
        <>
          <h3>{result.summary.filename}</h3>
          <p>
            Conta: {result.account.name}. Abertura em {formatDate(result.account.opening_date)}.
            {!result.account.is_active &&
              ' Conta arquivada; a prévia permanece disponível para consulta.'}
          </p>
          {summaryStale && <p role="status">Contadores aguardando atualização da prévia.</p>}
          {!summaryStale && (
            <dl className="import-summary">
              <div>
                <dt>Situação</dt>
                <dd>{importStatuses[result.summary.status] ?? 'Consultar situação'}</dd>
              </div>
              <div>
                <dt>Total de registros</dt>
                <dd>{result.summary.total_rows}</dd>
              </div>
              <div>
                <dt>Registros inválidos</dt>
                <dd>{result.summary.invalid_rows}</dd>
              </div>
              <div>
                <dt>Lançamentos criados</dt>
                <dd>{result.summary.imported_rows}</dd>
              </div>
              <div>
                <dt>Registros selecionados</dt>
                <dd>
                  {Number.isSafeInteger(result.summary.selected_rows)
                    ? result.summary.selected_rows
                    : 'Não disponível'}
                </dd>
              </div>
            </dl>
          )}
          {result.summary.matching_files > 0 && (
            <p role="status" className="notice notice-error">
              Há {result.summary.matching_files} outra(s) prévia(s) deste mesmo arquivo nesta conta.
              Confira o histórico para evitar reenviar a mesma intenção. Compras idênticas não são
              eliminadas automaticamente.
            </p>
          )}
          <ol className="import-rows" aria-label="Registros da prévia">
            {result.rows.items.map((row) => (
              <li key={row.id} className="import-row">
                <h4>Registro {row.row_number}</h4>
                <p>{row.description ?? 'Descrição não identificada'}</p>
                <dl>
                  <div>
                    <dt>Data</dt>
                    <dd>
                      {row.transaction_date ? formatDate(row.transaction_date) : 'Não identificada'}
                    </dd>
                  </div>
                  <div>
                    <dt>Tipo indicado</dt>
                    <dd>
                      {row.type === 'income'
                        ? 'Receita'
                        : row.type === 'expense'
                          ? 'Despesa'
                          : 'Não identificado'}
                    </dd>
                  </div>
                  <div>
                    <dt>Valor indicado</dt>
                    <dd>{row.amount === null ? 'Não identificado' : formatMoney(row.amount)}</dd>
                  </div>
                  <div>
                    <dt>Conferência</dt>
                    <dd>{rowStatuses[row.status] ?? 'Revise o registro'}</dd>
                  </div>
                </dl>
                <p>Categoria: {row.category_name ?? 'Sem categoria'}</p>
                {row.review_errors?.length > 0 && (
                  <ul aria-label={'Pendências de revisão do registro ' + row.row_number}>
                    {row.review_errors.map((code) => (
                      <li key={code}>
                        {reviewErrors[code] ?? 'Confira a revisão deste registro.'}
                      </li>
                    ))}
                  </ul>
                )}
                <label className="import-selection">
                  <input
                    type="checkbox"
                    aria-label={'Selecionar registro ' + row.row_number}
                    checked={Boolean(row.selected)}
                    disabled={
                      loading ||
                      selecting ||
                      selectionBlocked ||
                      !row.selection_editable ||
                      (!row.selected && !row.selection_eligible)
                    }
                    onChange={(event) => choose(row, event.target.checked)}
                  />
                  Selecionar registro {row.row_number}
                </label>
                <Button
                  type="button"
                  variant="outline"
                  disabled={loading || selecting || selectionBlocked || !row.editable}
                  onClick={() => {
                    setError('')
                    setNotice('')
                    setEditing(row.id)
                  }}
                >
                  Revisar registro {row.row_number}
                </Button>
                {row.external_id && <p>Referência no arquivo: {row.external_id}</p>}
                {row.error_codes.length > 0 && (
                  <ul aria-label={'Problemas do registro ' + row.row_number}>
                    {row.error_codes.map((code, index) => (
                      <li key={index}>{importErrors[code] ?? 'Revise os dados deste registro.'}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          {!loading && !error && result.rows.items.length === 0 && (
            <p>Nenhum registro disponível nesta prévia.</p>
          )}
          {result.rows.has_more && (
            <Button type="button" variant="outline" disabled={loading || selecting} onClick={more}>
              Carregar mais registros da prévia
            </Button>
          )}
        </>
      )}
      <div className="account-actions">
        <Button type="button" variant="outline" disabled={loading || selecting} onClick={reload}>
          Recarregar prévia
        </Button>
        <Button type="button" variant="outline" onClick={onClose}>
          Voltar ao envio de CSV
        </Button>
      </div>
    </section>
  )
}
