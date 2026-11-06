import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'
import PostTransactionPanel from '@/components/PostTransactionPanel'
import EditTransactionPanel from '@/components/EditTransactionPanel'
import DeleteTransactionPanel from '@/components/DeleteTransactionPanel'
import TransactionFilters from '@/components/TransactionFilters'

const emptyFilters = {
  account_id: '',
  category_id: '',
  type: '',
  status: '',
  date_from: '',
  date_to: '',
  q: '',
}

export default function TransactionHistory({
  ownerId,
  onExpired,
  disabled,
  onBalanceChanged,
  references,
  onActionChange,
  revision,
  onLoadReferences,
}) {
  const [draft, setDraft] = useState(emptyFilters)
  const [filters, setFilters] = useState(emptyFilters)
  const dirty = Object.keys(emptyFilters).some((key) => draft[key] !== filters[key])
  const [page, setPage] = useState({ items: [], has_more: false })
  const [pending, setLoading] = useState(true)
  const [loadedRevision, setLoadedRevision] = useState(revision)
  const loading = pending || loadedRevision !== revision
  const [error, setError] = useState('')
  const [postingId, setPostingId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const actionOpen = Boolean(postingId || editingId || deletingId)
  const heading = useRef(null)
  const resolved = useCallback(() => {
    setPage({ items: [], has_more: false })
    onBalanceChanged()
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }, [onBalanceChanged])
  const live = useRef(false)
  const requestVersion = useRef(0)
  const requestBusy = useRef(false)

  const removed = useCallback(
    (id) => {
      setPage((previous) => ({ ...previous, items: previous.items.filter((row) => row.id !== id) }))
      onBalanceChanged()
      setLoading(true)
      setError('')
      setRefresh((value) => value + 1)
    },
    [onBalanceChanged],
  )

  function closeAction() {
    setPostingId(null)
    setEditingId(null)
    setDeletingId(null)
    onActionChange(false)
    heading.current?.focus()
  }

  useEffect(() => {
    let current = true
    live.current = true
    const version = ++requestVersion.current
    requestBusy.current = true
    api
      .transactions(ownerId, 0, filters)
      .then((result) => {
        if (current && version === requestVersion.current) {
          setPage(result)
          setError('')
        }
      })
      .catch((failure) => {
        if (!current || version !== requestVersion.current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível carregar os lançamentos.'))
      })
      .finally(() => {
        if (current && version === requestVersion.current) {
          requestBusy.current = false
          setLoading(false)
          setLoadedRevision(revision)
        }
      })
    return () => {
      current = false
      live.current = false
      requestVersion.current += 1
      requestBusy.current = false
    }
  }, [ownerId, onExpired, refresh, filters, revision])

  function applyFilters(event) {
    event.preventDefault()
    if (requestBusy.current || actionOpen || disabled) return
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setError('A data inicial precisa ser igual ou anterior à data final.')
      return
    }
    const next = { ...draft, q: draft.q.trim() }
    setDraft(next)
    setLoading(true)
    setError('')
    setPage({ items: [], has_more: false })
    setFilters(next)
  }

  function clearFilters() {
    if (requestBusy.current || actionOpen || disabled) return
    setDraft(emptyFilters)
    setFilters({ ...emptyFilters })
    setLoading(true)
    setError('')
    setPage({ items: [], has_more: false })
  }

  async function reload(append = false) {
    if (requestBusy.current) return
    requestBusy.current = true
    const version = ++requestVersion.current
    setLoading(true)
    setError('')
    if (!append) setPage({ items: [], has_more: false })
    try {
      const result = await api.transactions(ownerId, append ? page.items.length : 0, filters)
      if (live.current && version === requestVersion.current)
        setPage((previous) => ({
          ...result,
          items: append ? [...previous.items, ...result.items] : result.items,
        }))
    } catch (failure) {
      if (!live.current || version !== requestVersion.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível carregar os lançamentos.'))
    } finally {
      if (live.current && version === requestVersion.current) {
        requestBusy.current = false
        setLoading(false)
      }
    }
  }

  return (
    <section aria-labelledby="history-heading" aria-busy={loading}>
      <div className="section-bar">
        <div>
          <h2 id="history-heading" tabIndex={-1} ref={heading}>
            Seus lançamentos
          </h2>
          <p className="muted">Receitas e despesas, da mais recente para a mais antiga.</p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loading || actionOpen || dirty}
          onClick={() => reload()}
        >
          Atualizar lançamentos
        </Button>
      </div>
      <TransactionFilters
        value={draft}
        onChange={(value) => {
          setDraft(value)
          setError('')
        }}
        onApply={applyFilters}
        onClear={clearFilters}
        references={references}
        onLoadReferences={onLoadReferences}
        disabled={loading || actionOpen || disabled}
        dirty={dirty}
      />
      {!dirty && !loading && !error && (
        <p className="field-hint">
          {Object.values(filters).some(Boolean)
            ? 'Resultados dos filtros aplicados.'
            : 'Todos os seus lançamentos.'}{' '}
          {page.items.length} registro(s) carregado(s)
          {page.has_more ? '; há mais resultados.' : '.'} O filtro do histórico não altera a
          consulta de saldo.
        </p>
      )}
      {loading && <p role="status">Carregando lançamentos…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {!loading && !error && !dirty && !page.items.length && (
        <div className="empty-accounts">
          <h3>
            {Object.values(filters).some(Boolean)
              ? 'Nenhum lançamento encontrado.'
              : 'Seu histórico começa aqui.'}
          </h3>
          <p>
            {Object.values(filters).some(Boolean)
              ? 'Revise os filtros ou limpe a consulta para ver o histórico completo.'
              : 'Registre o primeiro movimento para acompanhar sua conta.'}
          </p>
        </div>
      )}
      {postingId && (
        <PostTransactionPanel
          key={postingId}
          ownerId={ownerId}
          transactionId={postingId}
          disabled={disabled}
          onExpired={onExpired}
          onResolved={resolved}
          onAttempt={onBalanceChanged}
          onClose={closeAction}
        />
      )}
      {editingId && (
        <EditTransactionPanel
          key={editingId}
          ownerId={ownerId}
          transactionId={editingId}
          references={references}
          disabled={disabled}
          onExpired={onExpired}
          onResolved={resolved}
          onAttempt={onBalanceChanged}
          onClose={closeAction}
        />
      )}
      {deletingId && (
        <DeleteTransactionPanel
          key={deletingId}
          ownerId={ownerId}
          transactionId={deletingId}
          disabled={disabled}
          onExpired={onExpired}
          onRemoved={removed}
          onAttempt={onBalanceChanged}
          onClose={closeAction}
        />
      )}
      {!dirty && !loading && !error && (
        <ul className="account-cards" aria-label="Lançamentos cadastrados">
          {page.items.map((item) => (
            <li key={item.id} className="surface account-card">
              <div className="account-card-heading">
                <h3>{item.description}</h3>
                <span className="account-type">
                  {item.type === 'income' ? 'Receita' : 'Despesa'} ·{' '}
                  {item.status === 'posted' ? 'Efetivado' : 'Planejado'}
                </span>
              </div>
              <p className="movement-references">
                {item.account_name} · {item.category_name}
              </p>
              <dl>
                <div>
                  <dt>Valor</dt>
                  <dd className={item.type === 'expense' ? 'negative-money' : ''}>
                    {item.type === 'expense' ? '−' : '+'}
                    {formatMoney(item.amount)}
                  </dd>
                </div>
                <div className="opening-date">
                  <dt>Data</dt>
                  <dd>{formatDate(item.effective_date)}</dd>
                </div>
              </dl>
              <div className="account-actions">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={loading || disabled || actionOpen}
                  onClick={() => {
                    setEditingId(item.id)
                    onActionChange(true)
                  }}
                >
                  Editar
                </Button>
                {item.status === 'planned' && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={loading || disabled || actionOpen}
                    onClick={() => {
                      setPostingId(item.id)
                      onActionChange(true)
                    }}
                  >
                    Efetivar
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={loading || disabled || actionOpen}
                  onClick={() => {
                    setDeletingId(item.id)
                    onActionChange(true)
                  }}
                >
                  Excluir
                </Button>
              </div>
              {item.notes && (
                <details className="movement-notes">
                  <summary>Observações</summary>
                  <p>{item.notes}</p>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
      {!dirty && page.has_more && (
        <Button
          type="button"
          variant="outline"
          disabled={loading || actionOpen}
          onClick={() => reload(true)}
        >
          Carregar mais lançamentos
        </Button>
      )}
      <p className="field-hint">
        Planejados não alteram o saldo real até você confirmar sua efetivação. A edição mantém a
        situação atual. A exclusão exige confirmação e retira o movimento do saldo.
      </p>
    </section>
  )
}
