import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'
import PostTransactionPanel from '@/components/PostTransactionPanel'
import EditTransactionPanel from '@/components/EditTransactionPanel'
import DeleteTransactionPanel from '@/components/DeleteTransactionPanel'

export default function TransactionHistory({
  ownerId,
  onExpired,
  disabled,
  onBalanceChanged,
  references,
  onActionChange,
}) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [postingId, setPostingId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const actionOpen = Boolean(postingId || editingId || deletingId)
  const heading = useRef(null)
  const resolved = useCallback(
    (item) => {
      setPage((previous) => ({
        ...previous,
        items: previous.items.map((row) => (row.id === item.id ? item : row)),
      }))
      onBalanceChanged()
    },
    [onBalanceChanged],
  )
  const live = useRef(false)
  const requestVersion = useRef(0)
  const edited = useCallback(
    (item) => {
      resolved(item)
      // Reset pagination after edits because changing the date can move a row across pages.
      setLoading(true)
      setError('')
      setRefresh((value) => value + 1)
    },
    [resolved],
  )

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
    api
      .transactions(ownerId)
      .then((result) => {
        if (current) setPage(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível carregar os lançamentos.'))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
      live.current = false
      requestVersion.current += 1
    }
  }, [ownerId, onExpired, refresh])

  async function reload(append = false) {
    const version = ++requestVersion.current
    setLoading(true)
    setError('')
    try {
      const result = await api.transactions(ownerId, append ? page.items.length : 0)
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
      if (live.current && version === requestVersion.current) setLoading(false)
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
          disabled={loading || actionOpen}
          onClick={() => reload()}
        >
          Atualizar lançamentos
        </Button>
      </div>
      {loading && <p role="status">Carregando lançamentos…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {!loading && !error && !page.items.length && (
        <div className="empty-accounts">
          <h3>Seu histórico começa aqui.</h3>
          <p>Registre o primeiro movimento para acompanhar sua conta.</p>
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
          onResolved={edited}
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
      {page.has_more && (
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
