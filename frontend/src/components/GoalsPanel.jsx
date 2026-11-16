import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import GoalFields from '@/components/GoalFields'
import AllocationPanel from '@/components/AllocationPanel'
import { goalStatuses } from '@/lib/goals'
import EditGoalPanel from '@/components/EditGoalPanel'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function GoalsPanel({
  ownerId,
  onExpired,
  intent,
  onIntent,
  allocationIntent,
  onAllocationIntent,
  onFinancialChange,
}) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [editing, setEditing] = useState(null)
  const [allocating, setAllocating] = useState(allocationIntent?.goalId ?? null)
  const [formKey, setFormKey] = useState(0)
  const [conflict, setConflict] = useState(intent?.conflict ?? false)
  const live = useRef(false),
    sending = useRef(false),
    fetching = useRef(true),
    heading = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    fetching.current = true
    api
      .goals(ownerId)
      .then((result) => {
        if (current) setPage(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível listar metas.'))
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
  }, [ownerId, onExpired, refresh])
  function reload() {
    if (fetching.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }
  async function more() {
    if (fetching.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.goals(ownerId, page.items.length)
      if (live.current)
        setPage((previous) => ({ ...result, items: [...previous.items, ...result.items] }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais metas.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  async function persist(pending) {
    if (sending.current || editing || allocating || allocationIntent) return
    sending.current = true
    setBusy(true)
    setError('')
    setNotice('')
    setConflict(false)
    onIntent(pending)
    try {
      await api.createGoal(ownerId, pending.data, pending.key)
      if (!live.current) return
      onIntent(null)
      setFormKey((value) => value + 1)
      setNotice('Meta cadastrada. Nenhum dinheiro foi reservado ou movimentado.')
      reload()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        onIntent({ ...pending, conflict: failure.status === 409 })
        setConflict(failure.status === 409)
        setError(
          failure.status === 409
            ? 'Esta tentativa tem dados diferentes dos já recebidos. Confira a lista antes de encerrar.'
            : 'Não foi possível confirmar o cadastro. A tentativa está preservada para conferência com a mesma chave.',
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }
  return (
    <div className="accounts-layout goals-panel">
      <section aria-labelledby="goals-heading" aria-busy={loading}>
        <div className="section-bar">
          <h2 id="goals-heading" ref={heading} tabIndex={-1}>
            Suas metas
          </h2>
          <Button
            type="button"
            variant="outline"
            disabled={loading || busy || Boolean(editing)}
            onClick={reload}
          >
            Atualizar metas
          </Button>
        </div>
        <p className="field-hint">
          Organize seus objetivos em reais. Cadastrar, editar ou mudar a situação de uma meta não
          reserva nem movimenta dinheiro.
        </p>
        {loading && <p role="status">Carregando metas…</p>}
        {error && (
          <p role="alert" className="notice notice-error">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="notice notice-success">
            {notice}
          </p>
        )}
        {!loading && !error && !page.items.length && <p>Nenhuma meta cadastrada.</p>}
        <ul className="account-cards" aria-label="Metas cadastradas">
          {page.items.map((item) => (
            <li key={item.id} className="surface account-card">
              <div className="account-card-heading">
                <h3>{item.name}</h3>
                <span className="account-type">{goalStatuses[item.status]}</span>
              </div>
              {item.description && <p>{item.description}</p>}
              <dl>
                <div>
                  <dt>Valor alvo</dt>
                  <dd>{formatMoney(item.target_amount)}</dd>
                </div>
                <div>
                  <dt>Prazo</dt>
                  <dd>{item.target_date ? formatDate(item.target_date) : 'Sem prazo definido'}</dd>
                </div>
              </dl>
              <Button
                type="button"
                variant="outline"
                disabled={
                  loading ||
                  busy ||
                  Boolean(intent) ||
                  Boolean(editing) ||
                  Boolean(allocating) ||
                  Boolean(allocationIntent)
                }
                onClick={() => {
                  setNotice('')
                  setEditing(item.id)
                }}
              >
                Editar meta
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={
                  loading ||
                  busy ||
                  Boolean(intent) ||
                  Boolean(editing) ||
                  Boolean(allocating) ||
                  Boolean(allocationIntent)
                }
                onClick={() => setAllocating(item.id)}
              >
                Reservas e progresso
              </Button>
            </li>
          ))}
        </ul>
        {page.has_more && (
          <Button
            type="button"
            variant="outline"
            disabled={loading || busy || Boolean(editing)}
            onClick={more}
          >
            Carregar mais metas
          </Button>
        )}
      </section>
      {allocationIntent && !allocating && (
        <Button type="button" onClick={() => setAllocating(allocationIntent.goalId)}>
          Retomar operação de reserva
        </Button>
      )}
      {allocating ? (
        <AllocationPanel
          key={allocating}
          ownerId={ownerId}
          goalId={allocating}
          intent={allocationIntent?.goalId === allocating ? allocationIntent : null}
          onIntent={onAllocationIntent}
          onExpired={onExpired}
          onChanged={onFinancialChange}
          onClose={() => {
            setAllocating(null)
            heading.current?.focus()
          }}
        />
      ) : editing ? (
        <EditGoalPanel
          key={editing}
          ownerId={ownerId}
          goalId={editing}
          onExpired={onExpired}
          onSaved={() => {
            setEditing(null)
            setNotice('Meta atualizada. Os saldos das contas não foram alterados.')
            reload()
            heading.current?.focus()
          }}
          onClose={() => {
            setEditing(null)
            heading.current?.focus()
          }}
        />
      ) : (
        <section className="surface account-form" aria-labelledby="new-goal-heading">
          <h2 id="new-goal-heading">Nova meta</h2>
          <GoalFields
            key={formKey}
            initial={intent?.data}
            disabled={busy || loading || Boolean(intent) || Boolean(allocationIntent)}
            onSave={(data) => persist({ ownerId, key: crypto.randomUUID(), data })}
          />
          {intent && (
            <div className="retry-account">
              <p>
                Em conferência: {intent.data.name} · {formatMoney(intent.data.target_amount)}.
                Recarregar a página perde esta tentativa; confira a lista antes de iniciar outra.
              </p>
              {!conflict && (
                <Button type="button" disabled={busy} onClick={() => persist(intent)}>
                  Conferir e repetir cadastro da meta
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  onIntent(null)
                  setConflict(false)
                  setError('')
                  setFormKey((value) => value + 1)
                }}
              >
                Conferi a lista: encerrar tentativa
              </Button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
