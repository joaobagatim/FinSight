import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function DeleteTransactionPanel({
  ownerId,
  transactionId,
  disabled,
  onExpired,
  onRemoved,
  onAttempt,
  onClose,
}) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [removed, setRemoved] = useState(false)
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
        if (current) setSnapshot(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else if (failure.status === 410) {
          setRemoved(true)
          onRemoved(transactionId)
        } else setError(errorMessage(failure, 'Não foi possível consultar este lançamento.'))
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
  }, [ownerId, transactionId, onExpired, onRemoved])

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
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else if (failure.status === 410) {
        setRemoved(true)
        onRemoved(transactionId)
      } else setError(errorMessage(failure, 'Não foi possível consultar a situação.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }

  async function confirm() {
    if (sending.current || blocked || disabled || removed || !snapshot) return
    sending.current = true
    setBusy(true)
    setError('')
    onAttempt()
    try {
      await api.deleteTransaction(ownerId, transactionId, snapshot.etag)
      if (!live.current) return
      setRemoved(true)
      onRemoved(transactionId)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Os dados mudaram. Recarregue a situação e confira novamente antes de excluir.'
            : failure.status === 422
              ? 'Este lançamento não pode ser excluído por este fluxo.'
              : 'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar excluir novamente.',
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
      className="surface account-form posting-panel deletion-panel"
      aria-labelledby="delete-heading"
      aria-busy={loading || busy}
    >
      <p className="eyebrow">Confira antes de excluir</p>
      <h3 id="delete-heading" tabIndex={-1} ref={heading}>
        Excluir lançamento
      </h3>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {removed ? (
        <p role="status" className="notice notice-success">
          Este lançamento foi excluído do histórico e do cálculo de saldo.
        </p>
      ) : (
        item && (
          <>
            <p>
              <strong>{item.description}</strong>
            </p>
            <p>
              {item.account_name} · {item.category_name}
            </p>
            <p>
              {item.type === 'income' ? 'Receita' : 'Despesa'} de {formatMoney(item.amount)} em{' '}
              {formatDate(item.effective_date)} ·{' '}
              {item.status === 'posted' ? 'Efetivado' : 'Planejado'}.
            </p>
            <p className="field-hint">
              O lançamento sairá do histórico e deixará de compor o saldo. Esta ação não pode ser
              desfeita pela interface.
            </p>
            <Button
              type="button"
              className="wide-button"
              disabled={busy || loading || blocked || disabled}
              onClick={confirm}
            >
              {busy ? 'Excluindo…' : 'Confirmar exclusão'}
            </Button>
          </>
        )
      )}
      {(!snapshot || blocked) && !loading && !removed && (
        <Button type="button" variant="outline" disabled={busy} onClick={reload}>
          Recarregar situação
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        {removed ? 'Voltar ao histórico' : 'Cancelar e voltar ao histórico'}
      </Button>
    </section>
  )
}
