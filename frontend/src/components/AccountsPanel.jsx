import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, parseMoney, today } from '@/lib/money'

const types = {
  checking: 'Conta corrente',
  savings: 'Poupança',
  cash: 'Dinheiro',
  investment: 'Investimentos',
}

export default function AccountsPanel({ ownerId, onExpired }) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [balance, setBalance] = useState('0,00')
  const [date, setDate] = useState(today)
  const [pending, setPending] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const savingNow = useRef(false)
  const live = useRef(false)
  const generation = useRef(0)

  useEffect(() => {
    live.current = true
    const version = ++generation.current
    api
      .accounts(ownerId)
      .then((result) => {
        if (live.current && version === generation.current) setPage(result)
      })
      .catch((failure) => {
        if (!live.current || version !== generation.current) return
        if (failure.status === 401) onExpired()
        else setListError(errorMessage(failure, 'Não foi possível carregar suas contas.'))
      })
      .finally(() => {
        if (live.current && version === generation.current) setLoading(false)
      })
    return () => {
      live.current = false
      generation.current += 1
    }
  }, [ownerId, onExpired])

  async function reload(append = false) {
    const version = ++generation.current
    setLoading(true)
    setListError('')
    try {
      const result = await api.accounts(ownerId, append ? page.items.length : 0)
      if (live.current && version === generation.current) {
        setPage((previous) => ({
          ...result,
          items: append ? [...previous.items, ...result.items] : result.items,
        }))
      }
    } catch (failure) {
      if (!live.current || version !== generation.current) return
      if (failure.status === 401) onExpired()
      else setListError(errorMessage(failure, 'Não foi possível carregar suas contas.'))
    } finally {
      if (live.current && version === generation.current) setLoading(false)
    }
  }

  async function persist(intent) {
    if (savingNow.current) return
    savingNow.current = true
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      await api.createAccount(ownerId, intent.data, intent.key)
      if (!live.current) return
      setPending(null)
      setName('')
      setBalance('0,00')
      setSuccess('Conta cadastrada. Você já pode encontrá-la na lista.')
      await reload()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) {
        onExpired()
      } else {
        if ([403, 409, 422].includes(failure.status)) setPending(null)
        setError(
          errorMessage(
            failure,
            failure.status === 409
              ? 'Atualize a lista de contas antes de tentar um novo cadastro.'
              : 'Não foi possível confirmar o cadastro. Confira os dados e tente novamente.',
          ),
        )
      }
    } finally {
      savingNow.current = false
      if (live.current) setSaving(false)
    }
  }

  function submit(event) {
    event.preventDefault()
    if (savingNow.current || pending) return
    setError('')
    let openingBalance
    try {
      openingBalance = parseMoney(balance)
    } catch (failure) {
      setError(failure.message)
      return
    }
    if (!name.trim() || Array.from(name.trim()).length > 100) {
      setError('Informe um nome com até 100 caracteres.')
      return
    }
    const intent = {
      key: crypto.randomUUID(),
      data: {
        name: name.trim(),
        type,
        currency: 'BRL',
        opening_balance: openingBalance,
        opening_date: date,
      },
    }
    setPending(intent)
    void persist(intent)
  }

  return (
    <div className="accounts-layout">
      <section className="accounts-list" aria-labelledby="accounts-heading" aria-busy={loading}>
        <div className="section-bar">
          <div>
            <h2 id="accounts-heading">Suas contas</h2>
            <p className="muted">Um ponto de partida para organizar seu dinheiro.</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={() => reload()}
          >
            Atualizar lista
          </Button>
        </div>
        {listError && (
          <p className="notice notice-error" role="alert">
            {listError}
          </p>
        )}
        {loading && (
          <p className="muted" role="status">
            Carregando contas…
          </p>
        )}
        {!loading && !listError && page.items.length === 0 && (
          <div className="empty-accounts">
            <span className="empty-symbol" aria-hidden="true">
              ↗
            </span>
            <h3>Sua primeira conta começa aqui.</h3>
            <p>Cadastre uma conta corrente, poupança ou carteira para dar o primeiro passo.</p>
          </div>
        )}
        <ul className="account-cards" aria-label="Contas cadastradas">
          {page.items.map((account) => (
            <li key={account.id} className="surface account-card">
              <div className="account-card-heading">
                <h3>{account.name}</h3>
                <span className="account-type">
                  {types[account.type] || 'Conta'}
                  {!account.is_active && ' · Arquivada'}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Saldo inicial</dt>
                  <dd className={account.opening_balance.startsWith('-') ? 'negative-money' : ''}>
                    {formatMoney(account.opening_balance)}
                  </dd>
                </div>
                <div className="opening-date">
                  <dt>Posição ao final de</dt>
                  <dd>{formatDate(account.opening_date)}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
        {page.has_more && (
          <Button type="button" variant="outline" disabled={loading} onClick={() => reload(true)}>
            Carregar mais contas
          </Button>
        )}
        <p className="field-hint">
          Os valores acima são saldos iniciais. Receitas, despesas e saldos atualizados estarão
          disponíveis em outra etapa.
        </p>
      </section>
      <section className="surface account-form" aria-labelledby="account-form-heading">
        <p className="eyebrow">Organize o presente</p>
        <h2 id="account-form-heading">Nova conta</h2>
        <p className="muted">Dê um nome e escolha a posição de abertura.</p>
        {success && (
          <p className="notice notice-success" role="status">
            {success}
          </p>
        )}
        <form
          onSubmit={submit}
          aria-label="Nova conta"
          aria-describedby={error ? 'account-error' : undefined}
        >
          <fieldset disabled={saving || Boolean(pending)}>
            <legend className="sr-only">Dados da conta</legend>
            <label className="field" htmlFor="account-name">
              Nome da conta
              <input
                id="account-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Ex.: Minha conta principal"
                required
              />
            </label>
            <div className="field">
              <label htmlFor="account-type">Tipo de conta</label>
              <select
                id="account-type"
                value={type}
                onChange={(event) => setType(event.target.value)}
              >
                {Object.entries(types).map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <label className="field" htmlFor="account-balance">
              Saldo inicial (R$)
              <input
                id="account-balance"
                inputMode="decimal"
                value={balance}
                onChange={(event) => setBalance(event.target.value)}
                required
                aria-describedby="balance-hint"
              />
            </label>
            <p className="field-hint" id="balance-hint">
              Use vírgula nos centavos, por exemplo: 1.234,56. O saldo pode ser negativo.
            </p>
            <label className="field" htmlFor="account-date">
              Data de abertura
              <input
                id="account-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                required
                aria-describedby="date-hint"
              />
            </label>
            <p className="field-hint" id="date-hint">
              Informe a posição da conta ao final dessa data.
            </p>
            <Button type="submit" className="wide-button">
              {saving ? 'Salvando…' : 'Cadastrar conta'}
            </Button>
          </fieldset>
          {error && (
            <p className="notice notice-error" id="account-error" role="alert">
              {error}
            </p>
          )}
        </form>
        {pending && !saving && (
          <div className="retry-account">
            <p>
              Não foi possível confirmar a resposta. Repita esta tentativa para conferir o cadastro.
            </p>
            <Button type="button" className="wide-button" onClick={() => persist(pending)}>
              Tentar novamente
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
