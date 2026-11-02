import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function PostTransactionPanel({
  ownerId,
  transactionId,
  disabled,
  onExpired,
  onResolved,
  onAttempt,
  onClose,
}) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const heading = useRef(null)
  const live = useRef(false)
  const sending = useRef(false)

  useEffect(() => {
    let current = true
    live.current = true
    sending.current = true
    heading.current?.focus()
    api
      .transaction(ownerId, transactionId)
      .then((result) => {
        if (!current) return
        setSnapshot(result)
        if (result.data.status === 'posted') onResolved(result.data)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível consultar este lançamento.'))
      })
      .finally(() => {
        if (current) {
          sending.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, transactionId, onExpired, onResolved])

  async function reload() {
    if (sending.current) return
    sending.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.transaction(ownerId, transactionId)
      if (!live.current) return
      setSnapshot(result)
      setBlocked(false)
      if (result.data.status === 'posted') onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível consultar a situação.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }

  async function confirm() {
    if (sending.current || blocked || disabled || snapshot?.data.status !== 'planned') return
    sending.current = true
    setBusy(true)
    setError('')
    onAttempt()
    try {
      const result = await api.postTransaction(ownerId, transactionId, snapshot.etag)
      if (!live.current) return
      setSnapshot(result)
      onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Os dados deste lançamento mudaram. Recarregue a situação e confira novamente antes de confirmar.'
            : failure.status === 422
              ? 'Não foi possível efetivar. Confira se a conta e a categoria estão ativas e se a data é válida para a abertura.'
              : failure.status === 0 || failure.status >= 500
                ? 'Não foi possível confirmar o resultado. Recarregue a situação para conferir se o lançamento já foi efetivado.'
                : errorMessage(
                    failure,
                    'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar novamente.',
                  ),
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  const item = snapshot?.data
  return (
    <section
      className="surface account-form posting-panel"
      aria-labelledby="post-heading"
      aria-busy={busy || loading}
    >
      <p className="eyebrow">Confira antes de efetivar</p>
      <h3 id="post-heading" tabIndex={-1} ref={heading}>
        Efetivar lançamento
      </h3>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {item && (
        <>
          <p>
            <strong>{item.description}</strong>
          </p>
          <p>
            {item.account_name} · {item.category_name}
          </p>
          <p>
            {item.type === 'income' ? 'Receita' : 'Despesa'} de {formatMoney(item.amount)} em{' '}
            {formatDate(item.effective_date)}.
          </p>
          {item.status === 'posted' ? (
            <p role="status" className="notice notice-success">
              Este lançamento já está efetivado.
            </p>
          ) : (
            <>
              <p className="field-hint">
                A efetivação fará este movimento compor o saldo a partir da data informada. Valor,
                conta, categoria e data serão mantidos; nenhum novo lançamento será criado.
              </p>
              <Button
                type="button"
                className="wide-button"
                disabled={busy || loading || blocked || disabled}
                onClick={confirm}
              >
                {busy ? 'Efetivando…' : 'Confirmar efetivação'}
              </Button>
            </>
          )}
        </>
      )}
      {(!snapshot || blocked) && !loading && (
        <Button type="button" variant="outline" disabled={busy} onClick={reload}>
          Recarregar situação
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        Voltar ao histórico
      </Button>
    </section>
  )
}
