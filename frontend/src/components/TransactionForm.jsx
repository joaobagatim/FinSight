import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, parseMoney, today } from '@/lib/money'

export default function TransactionForm({
  ownerId,
  references,
  intent,
  onIntent,
  onExpired,
  onSaved,
}) {
  const [description, setDescription] = useState(intent?.data.description ?? '')
  const [accountId, setAccountId] = useState(intent?.data.account_id ?? '')
  const [categoryId, setCategoryId] = useState(intent?.data.category_id ?? '')
  const [type, setType] = useState(intent?.data.type ?? 'expense')
  const [status, setStatus] = useState(intent?.data.status ?? '')
  const [amount, setAmount] = useState(intent ? intent.data.amount.replace('.', ',') : '')
  const [date, setDate] = useState(intent?.data.effective_date ?? today())
  const [notes, setNotes] = useState(intent?.data.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const sending = useRef(false)
  const live = useRef(false)
  const accounts = references.accounts.filter((account) => account.is_active)
  const categories = references.categories.filter(
    (category) => category.is_active && category.type === type,
  )
  const selected = accounts.find((account) => account.id === accountId)

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  async function persist(pending) {
    if (sending.current) return
    sending.current = true
    // Preserve uncertainty before dispatch, including when navigation unmounts this form.
    onIntent({ ...pending, uncertain: true })
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      await api.createTransaction(ownerId, pending.data, pending.key)
      if (!live.current) return
      onIntent(null)
      setDescription('')
      setAmount('')
      setNotes('')
      setStatus('')
      setSuccess('Lançamento cadastrado. Consulte o saldo na data desejada.')
      onSaved()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        onIntent({
          ...pending,
          conflict: failure.status === 409,
          uncertain: pending.uncertain || ![403, 422, 429, 409].includes(failure.status),
          rejected: [403, 422].includes(failure.status),
        })
        setError(
          failure.status === 409
            ? 'Esta tentativa tem dados diferentes dos já recebidos. Confira o histórico antes de iniciar outro cadastro.'
            : failure.status === 422
              ? 'Confira se a conta e a categoria continuam ativas, se os tipos são compatíveis e se a data é posterior à abertura.'
              : errorMessage(
                  failure,
                  'Não foi possível confirmar o cadastro. Confira os dados e tente novamente.',
                ),
        )
      }
    } finally {
      sending.current = false
      if (live.current) setSaving(false)
    }
  }

  function submit(event) {
    event.preventDefault()
    if (sending.current || intent) return
    setError('')
    let money
    try {
      money = parseMoney(amount)
      if (money.startsWith('-') || money === '0.00')
        throw new Error('Informe um valor maior que zero. O tipo define se é receita ou despesa.')
    } catch (failure) {
      setError(failure.message)
      return
    }
    if (!selected || !categories.some((category) => category.id === categoryId)) {
      setError(
        'Selecione uma conta ativa e uma categoria compatível. Carregue mais opções ou cadastre em Contas e Categorias.',
      )
      return
    }
    if (!date || date <= selected.opening_date) {
      setError(
        `A data deve ser posterior a ${formatDate(selected.opening_date)}, a posição de abertura da conta.`,
      )
      return
    }
    if (
      !['planned', 'posted'].includes(status) ||
      !description.trim() ||
      Array.from(description.trim()).length > 255 ||
      Array.from(notes.trim()).length > 2000
    ) {
      setError(
        'Informe a situação, uma descrição com até 255 caracteres e observações com até 2.000 caracteres.',
      )
      return
    }
    const pending = {
      ownerId,
      key: crypto.randomUUID(),
      accountName: selected.name,
      categoryName: categories.find((category) => category.id === categoryId).name,
      data: {
        description: description.trim(),
        account_id: accountId,
        category_id: categoryId,
        amount: money,
        type,
        status,
        effective_date: date,
        notes: notes.trim() || null,
      },
    }
    onIntent(pending)
    void persist(pending)
  }

  return (
    <section
      className="surface account-form"
      aria-labelledby="transaction-form-heading"
      aria-busy={saving || references.loading}
    >
      <p className="eyebrow">Cada movimento conta</p>
      <h2 id="transaction-form-heading">Novo lançamento</h2>
      <p className="muted">Registre uma receita ou despesa da sua conta.</p>
      {references.loading && <p role="status">Carregando contas e categorias…</p>}
      {references.error && (
        <p role="alert" className="notice notice-error">
          {references.error}
        </p>
      )}
      {success && (
        <p role="status" className="notice notice-success">
          {success}
        </p>
      )}
      <form onSubmit={submit} aria-label="Novo lançamento">
        <fieldset
          disabled={saving || Boolean(intent) || references.loading || Boolean(references.error)}
        >
          <legend className="sr-only">Dados do lançamento</legend>
          <div className="field">
            <label htmlFor="movement-type">Tipo de lançamento</label>
            <select
              id="movement-type"
              value={type}
              onChange={(event) => {
                setType(event.target.value)
                setCategoryId('')
              }}
            >
              <option value="expense">Despesa</option>
              <option value="income">Receita</option>
            </select>
          </div>
          <label className="field" htmlFor="movement-description">
            Descrição
            <input
              id="movement-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              required
              placeholder="Ex.: Mercado da semana"
            />
          </label>
          <div className="field">
            <label htmlFor="movement-account">Conta do lançamento</label>
            <select
              id="movement-account"
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              required
            >
              <option value="">Selecione uma conta ativa</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
              {intent && !accounts.some((account) => account.id === accountId) && (
                <option value={accountId}>{intent.accountName}</option>
              )}
            </select>
          </div>
          <div className="field">
            <label htmlFor="movement-category">Categoria do lançamento</label>
            <select
              id="movement-category"
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
              required
            >
              <option value="">
                Selecione uma categoria de {type === 'income' ? 'receita' : 'despesa'}
              </option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
              {intent && !categories.some((category) => category.id === categoryId) && (
                <option value={categoryId}>{intent.categoryName}</option>
              )}
            </select>
          </div>
          {!references.loading && (!accounts.length || !categories.length) && (
            <p className="field-hint">
              Cadastre contas e categorias ativas nas áreas correspondentes ou carregue mais opções
              abaixo.
            </p>
          )}
          <label className="field" htmlFor="movement-amount">
            Valor (R$)
            <input
              id="movement-amount"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              required
              placeholder="150,00"
            />
          </label>
          <p className="field-hint">
            Use um valor positivo com vírgula nos centavos. Receita ou despesa define o sinal.
          </p>
          <label className="field" htmlFor="movement-date">
            Data do lançamento
            <input
              id="movement-date"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              required
            />
          </label>
          {selected && (
            <p className="field-hint">
              Informe uma data posterior a {formatDate(selected.opening_date)}, a posição de
              abertura.
            </p>
          )}
          <div className="field">
            <label htmlFor="movement-status">Situação do lançamento</label>
            <select
              id="movement-status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              required
            >
              <option value="">Selecione a situação</option>
              <option value="posted">Efetivado</option>
              <option value="planned">Planejado</option>
            </select>
          </div>
          <p className="field-hint">
            Efetivados entram no saldo a partir da data informada. Planejados não alteram o saldo
            real.
          </p>
          <label className="field" htmlFor="movement-notes">
            Observações (opcional)
            <textarea
              id="movement-notes"
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
          <Button type="submit" className="wide-button">
            {saving ? 'Salvando…' : 'Cadastrar lançamento'}
          </Button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {intent && (
        <div className="retry-account">
          <p>
            Em conferência: {intent.accountName} · {intent.categoryName} ·{' '}
            {formatMoney(intent.data.amount)}.
          </p>
          <p>
            Os dados desta tentativa estão preservados. Sair ou recarregar a página perde essa
            intenção; confira o histórico antes de iniciar outro cadastro.
          </p>
          <p>Encerrar a tentativa não cancela um lançamento que já tenha sido salvo.</p>
          {!saving && !intent.conflict && (
            <Button type="button" className="wide-button" onClick={() => persist(intent)}>
              Conferir e repetir tentativa
            </Button>
          )}
          {!saving && intent.rejected && !intent.uncertain && !intent.conflict && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onIntent(null)
                setError('Revise os dados antes de cadastrar novamente.')
              }}
            >
              Revisar dados da tentativa
            </Button>
          )}
          {!saving && (intent.conflict || intent.uncertain) && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onIntent(null)
                setDescription('')
                setAmount('')
                setNotes('')
                setStatus('')
                setError('')
              }}
            >
              Conferi o histórico: encerrar tentativa
            </Button>
          )}
        </div>
      )}
    </section>
  )
}
