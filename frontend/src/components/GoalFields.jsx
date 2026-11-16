import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { parseMoney } from '@/lib/money'
import { goalStatuses } from '@/lib/goals'

export default function GoalFields({ initial, editing = false, disabled, onSave }) {
  const [name, setName] = useState(initial?.name ?? '')
  const [amount, setAmount] = useState(initial?.target_amount?.replace('.', ',') ?? '')
  const [date, setDate] = useState(initial?.target_date ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [status, setStatus] = useState(initial?.status ?? 'active')
  const [error, setError] = useState('')
  function submit(event) {
    event.preventDefault()
    if (disabled) return
    setError('')
    try {
      const target = parseMoney(amount)
      if (target.startsWith('-') || target === '0.00')
        throw new Error('Informe um valor alvo maior que zero.')
      if (!name.trim() || Array.from(name.trim()).length > 150)
        throw new Error('Informe um nome com até 150 caracteres.')
      if (Array.from(description.trim()).length > 2000)
        throw new Error('Use até 2.000 caracteres na descrição.')
      onSave({
        name: name.trim(),
        target_amount: target,
        target_date: date || null,
        description: description.trim() || null,
        ...(editing ? { status } : {}),
      })
    } catch (failure) {
      setError(failure.message)
    }
  }
  return (
    <form onSubmit={submit} aria-label={editing ? 'Editar meta' : 'Nova meta'}>
      <fieldset disabled={disabled}>
        <legend className="sr-only">Dados da meta</legend>
        <label className="field" htmlFor="goal-name">
          Nome da meta
          <input
            id="goal-name"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="goal-amount">
          Valor alvo (R$)
          <input
            id="goal-amount"
            required
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="goal-date">
          Prazo da meta (opcional)
          <input
            id="goal-date"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="goal-description">
          Descrição da meta (opcional)
          <input
            id="goal-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {editing && (
          <label className="field" htmlFor="goal-status">
            Situação do objetivo
            <select
              id="goal-status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {Object.entries(goalStatuses).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        {editing && (
          <p className="field-hint">
            Concluir ou cancelar é uma decisão sobre o objetivo. Não comprova que o valor foi
            acumulado e não reserva, libera ou movimenta dinheiro.
          </p>
        )}
        <Button type="submit" className="wide-button">
          {editing ? 'Confirmar alterações da meta' : 'Cadastrar meta'}
        </Button>
      </fieldset>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
    </form>
  )
}
