import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import GoalFields from '@/components/GoalFields'
import { api, errorMessage } from '@/services/api'

export default function EditGoalPanel({ ownerId, goalId, onExpired, onSaved, onClose }) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const live = useRef(false)
  const sending = useRef(false)
  const heading = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    sending.current = true
    heading.current?.focus()
    api
      .goal(ownerId, goalId)
      .then((result) => {
        if (current) setSnapshot(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível consultar esta meta.'))
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
  }, [ownerId, goalId, onExpired])
  async function reload() {
    if (sending.current) return
    sending.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.goal(ownerId, goalId)
      if (!live.current) return
      setSnapshot(result)
      setBlocked(false)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível conferir a situação da meta.')
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }
  async function save(data) {
    if (sending.current || blocked || !snapshot) return
    sending.current = true
    setBusy(true)
    setError('')
    try {
      await api.updateGoal(ownerId, goalId, data, snapshot.etag)
      if (live.current) onSaved()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Esta meta mudou em outra operação. Recarregue a situação e revise antes de confirmar.'
            : 'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar salvar novamente.',
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }
  return (
    <section
      className="surface account-form goals-panel"
      aria-labelledby="edit-goal-heading"
      aria-busy={busy || loading}
    >
      <h3 id="edit-goal-heading" tabIndex={-1} ref={heading}>
        Editar meta
      </h3>
      {loading && <p role="status">Consultando a meta…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {snapshot && !loading && (
        <GoalFields
          key={snapshot.etag}
          initial={snapshot.data}
          editing
          disabled={busy || blocked}
          onSave={save}
        />
      )}
      {(!snapshot || blocked) && !loading && (
        <>
          <p className="field-hint">
            Recarregar consulta a situação atual e substitui o rascunho, sem enviar outra alteração.
          </p>
          <Button type="button" variant="outline" disabled={busy} onClick={reload}>
            Recarregar situação da meta
          </Button>
        </>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        Voltar às metas
      </Button>
    </section>
  )
}
