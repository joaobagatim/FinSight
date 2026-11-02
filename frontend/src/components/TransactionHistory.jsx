import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function TransactionHistory({ ownerId, onExpired }) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const live = useRef(false)
  const requestVersion = useRef(0)

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
  }, [ownerId, onExpired])

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
          <h2 id="history-heading">Seus lançamentos</h2>
          <p className="muted">Receitas e despesas, da mais recente para a mais antiga.</p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loading}
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
        <Button type="button" variant="outline" disabled={loading} onClick={() => reload(true)}>
          Carregar mais lançamentos
        </Button>
      )}
      <p className="field-hint">
        Planejados não alteram o saldo real. Alteração, exclusão e efetivação de planejados estarão
        disponíveis em outra etapa.
      </p>
    </section>
  )
}
