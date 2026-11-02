import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import TransactionForm from '@/components/TransactionForm'
import TransactionHistory from '@/components/TransactionHistory'
import AccountBalance from '@/components/AccountBalance'

export default function TransactionsPanel({ ownerId, onExpired, intent, onIntent }) {
  const [references, setReferences] = useState({
    accounts: [],
    categories: [],
    accountMore: false,
    categoryMore: false,
    loading: true,
    error: '',
  })
  const [revision, setRevision] = useState(0)
  const [balanceRevision, setBalanceRevision] = useState(0)
  const [actionOpen, setActionOpen] = useState(false)
  const balanceChanged = useCallback(() => setBalanceRevision((value) => value + 1), [])
  const live = useRef(false)
  const fetching = useRef(false)

  useEffect(() => {
    let current = true
    live.current = true
    fetching.current = true
    Promise.all([api.accounts(ownerId), api.categories(ownerId)])
      .then(([accounts, categories]) => {
        if (current)
          setReferences({
            accounts: accounts.items,
            categories: categories.items,
            accountMore: accounts.has_more,
            categoryMore: categories.has_more,
            loading: false,
            error: '',
          })
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else
          setReferences((previous) => ({
            ...previous,
            loading: false,
            error: errorMessage(failure, 'Não foi possível carregar contas e categorias.'),
          }))
      })
      .finally(() => {
        if (current) fetching.current = false
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, onExpired])

  async function load(kind) {
    if (fetching.current) return
    fetching.current = true
    setReferences((previous) => ({ ...previous, loading: true, error: '' }))
    try {
      if (!kind) {
        const [accounts, categories] = await Promise.all([
          api.accounts(ownerId),
          api.categories(ownerId),
        ])
        if (live.current)
          setReferences({
            accounts: accounts.items,
            categories: categories.items,
            accountMore: accounts.has_more,
            categoryMore: categories.has_more,
            loading: false,
            error: '',
          })
      } else {
        const result = await (kind === 'accounts'
          ? api.accounts(ownerId, references.accounts.length)
          : api.categories(ownerId, references.categories.length))
        if (live.current)
          setReferences((previous) => ({
            ...previous,
            [kind]: [...previous[kind], ...result.items],
            [kind === 'accounts' ? 'accountMore' : 'categoryMore']: result.has_more,
            loading: false,
          }))
      }
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else
        setReferences((previous) => ({
          ...previous,
          loading: false,
          error: errorMessage(failure, 'Não foi possível carregar contas e categorias.'),
        }))
    } finally {
      fetching.current = false
    }
  }

  return (
    <div className="accounts-layout transactions-layout">
      <div className="transaction-overview">
        <AccountBalance
          revision={balanceRevision}
          ownerId={ownerId}
          accounts={references.accounts}
          loading={references.loading}
          onExpired={onExpired}
        />
        <TransactionHistory
          key={`history-${revision}`}
          ownerId={ownerId}
          onExpired={onExpired}
          disabled={Boolean(intent)}
          onBalanceChanged={balanceChanged}
          references={references}
          onActionChange={setActionOpen}
        />
      </div>
      <div>
        <TransactionForm
          ownerId={ownerId}
          disabled={actionOpen}
          references={references}
          intent={intent}
          onIntent={onIntent}
          onExpired={onExpired}
          onSaved={() => {
            setRevision((value) => value + 1)
            balanceChanged()
          }}
        />
        <div className="reference-actions">
          <Button
            type="button"
            variant="outline"
            disabled={references.loading || Boolean(intent)}
            onClick={() => load()}
          >
            Atualizar contas e categorias
          </Button>
          {references.accountMore && (
            <Button
              type="button"
              variant="outline"
              disabled={references.loading || Boolean(intent)}
              onClick={() => load('accounts')}
            >
              Carregar mais contas para lançamento
            </Button>
          )}
          {references.categoryMore && (
            <Button
              type="button"
              variant="outline"
              disabled={references.loading || Boolean(intent)}
              onClick={() => load('categories')}
            >
              Carregar mais categorias para lançamento
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
