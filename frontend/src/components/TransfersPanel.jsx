import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'
import TransferForm from '@/components/TransferForm'
import AccountBalance from '@/components/AccountBalance'

export default function TransfersPanel({ ownerId, onExpired, intent, onIntent }) {
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [history, setHistory] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [balanceRevision, setBalanceRevision] = useState(0)
  const changed = useCallback(() => setBalanceRevision((value) => value + 1), [])
  const live = useRef(false)
  const fetching = useRef(true)
  const version = useRef(0)
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
            <h2 id="transfers-heading">Suas transferências</h2>
            <Button type="button" variant="outline" disabled={loading} onClick={reload}>
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
              </li>
            ))}
          </ul>
          {history.has_more && (
            <Button
              type="button"
              variant="outline"
              disabled={loading}
              onClick={() => more('history')}
            >
              Carregar mais transferências
            </Button>
          )}
          <p className="field-hint">
            Transferências não criam receita ou despesa. Edição, exclusão e efetivação de
            transferências planejadas serão disponibilizadas em etapas próprias.
          </p>
        </section>
      </div>
      <div>
        <TransferForm
          ownerId={ownerId}
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
            disabled={loading}
            onClick={() => more('accounts')}
          >
            Carregar mais contas para transferência
          </Button>
        )}
      </div>
    </div>
  )
}
