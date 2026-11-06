import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'
import TransferForm from '@/components/TransferForm'
import AccountBalance from '@/components/AccountBalance'
import PostTransferPanel from '@/components/PostTransferPanel'
import EditTransferPanel from '@/components/EditTransferPanel'

export default function TransfersPanel({ ownerId, onExpired, intent, onIntent }) {
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [history, setHistory] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [balanceRevision, setBalanceRevision] = useState(0)
  const [postingId, setPostingId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const actionOpen = Boolean(postingId || editingId)
  const heading = useRef(null)
  const changed = useCallback(() => setBalanceRevision((value) => value + 1), [])
  const resolved = useCallback(
    (item) => {
      setHistory((previous) => ({
        ...previous,
        items: previous.items.map((row) => (row.id === item.id ? item : row)),
      }))
      changed()
    },
    [changed],
  )
  const live = useRef(false)
  const fetching = useRef(true)
  const version = useRef(0)
  const edited = useCallback(() => {
    setHistory({ items: [], has_more: false })
    changed()
    fetching.current = true
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }, [changed])
  useEffect(() => {
    let current = true
    live.current = true
    Promise.all([api.accounts(ownerId), api.transfers(ownerId)])
      .then(([accountPage, transferPage]) => {
        if (current) {
          setAccounts(accountPage)
          setHistory(transferPage)
        }
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível carregar contas e transferências.'))
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
      version.current += 1
    }
  }, [ownerId, onExpired, refresh])

  function reload() {
    if (fetching.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }
  async function more(kind) {
    if (fetching.current) return
    fetching.current = true
    const request = ++version.current
    setLoading(true)
    setError('')
    try {
      const result = await (kind === 'accounts'
        ? api.accounts(ownerId, accounts.items.length)
        : api.transfers(ownerId, history.items.length))
      if (!live.current || request !== version.current) return
      const setter = kind === 'accounts' ? setAccounts : setHistory
      setter((previous) => ({ ...result, items: [...previous.items, ...result.items] }))
    } catch (failure) {
      if (!live.current || request !== version.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível carregar mais resultados.'))
    } finally {
      if (request === version.current) {
        fetching.current = false
        if (live.current) setLoading(false)
      }
    }
  }
  return (
    <div className="accounts-layout transactions-layout">
      <div className="transaction-overview">
        <AccountBalance
          ownerId={ownerId}
          accounts={accounts.items}
          loading={loading}
          onExpired={onExpired}
          revision={balanceRevision}
        />
        <section aria-labelledby="transfers-heading" aria-busy={loading}>
          <div className="section-bar">
            <h2 id="transfers-heading" tabIndex={-1} ref={heading}>
              Suas transferências
            </h2>
            <Button
              type="button"
              variant="outline"
              disabled={loading || actionOpen}
              onClick={reload}
            >
              Atualizar transferências
            </Button>
          </div>
          {loading && <p role="status">Carregando transferências…</p>}
          {error && (
            <p role="alert" className="notice notice-error">
              {error}
            </p>
          )}
          {!loading && !error && !history.items.length && (
            <p className="empty-accounts">Nenhuma transferência cadastrada.</p>
          )}
          {postingId && (
            <PostTransferPanel
              key={postingId}
              ownerId={ownerId}
              transferId={postingId}
              disabled={Boolean(intent)}
              onExpired={onExpired}
              onResolved={resolved}
              onAttempt={changed}
              onClose={() => {
                setPostingId(null)
                heading.current?.focus()
              }}
            />
          )}
          {editingId && (
            <EditTransferPanel
              key={editingId}
              ownerId={ownerId}
              transferId={editingId}
              accounts={accounts.items}
              loadingAccounts={loading}
              hasMoreAccounts={accounts.has_more}
              onMoreAccounts={() => more('accounts')}
              disabled={Boolean(intent)}
              onExpired={onExpired}
              onResolved={edited}
              onAttempt={changed}
              onClose={() => {
                setEditingId(null)
                heading.current?.focus()
              }}
            />
          )}
          <ul className="account-cards" aria-label="Transferências cadastradas">
            {history.items.map((item) => (
              <li key={item.id} className="surface account-card">
                <div className="account-card-heading">
                  <h3>{item.description || 'Transferência entre contas'}</h3>
                  <span className="account-type">
                    {item.status === 'posted' ? 'Efetivada' : 'Planejada'}
                  </span>
                </div>
                <p className="movement-references">
                  {item.from_account_name} → {item.to_account_name}
                </p>
                <dl>
                  <div>
                    <dt>Valor transferido</dt>
                    <dd>{formatMoney(item.amount)}</dd>
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
                    disabled={loading || Boolean(intent) || actionOpen}
                    onClick={() => setEditingId(item.id)}
                  >
                    Editar transferência
                  </Button>
                  {item.status === 'planned' && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={loading || Boolean(intent) || actionOpen}
                      onClick={() => setPostingId(item.id)}
                    >
                      Efetivar transferência
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {history.has_more && (
            <Button
              type="button"
              variant="outline"
              disabled={loading || actionOpen}
              onClick={() => more('history')}
            >
              Carregar mais transferências
            </Button>
          )}
          <p className="field-hint">
            Transferências não criam receita ou despesa. Planejadas exigem confirmação para entrar
            nos saldos. A edição mantém a situação e corrige contas, valor e data com revisão. A
            exclusão será disponibilizada em etapa própria.
          </p>
        </section>
      </div>
      <div>
        <TransferForm
          ownerId={ownerId}
          disabled={actionOpen}
          accounts={accounts.items}
          loading={loading || Boolean(error)}
          intent={intent}
          onIntent={onIntent}
          onExpired={onExpired}
          onAttempt={changed}
          onSaved={() => {
            changed()
            fetching.current = true
            setLoading(true)
            setError('')
            setRefresh((value) => value + 1)
          }}
        />
        {accounts.has_more && (
          <Button
            type="button"
            variant="outline"
            disabled={loading || Boolean(postingId)}
            onClick={() => more('accounts')}
          >
            Carregar mais contas para transferência
          </Button>
        )}
      </div>
    </div>
  )
}
