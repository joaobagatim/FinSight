import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'

const labels = { income: 'Receita', expense: 'Despesa' }

export default function CategoriesPanel({ ownerId, onExpired }) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState('expense')
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const live = useRef(false)
  const sending = useRef(false)
  const version = useRef(0)
  const heading = useRef(null)

  function failed(failure, fallback, setter = setError) {
    if (failure.status === 401) onExpired()
    else setter(errorMessage(failure, fallback))
  }

  useEffect(() => {
    let current = true
    live.current = true
    api
      .categories(ownerId)
      .then((result) => {
        if (current) setPage(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setListError(errorMessage(failure, 'Não foi possível carregar suas categorias.'))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
      live.current = false
      version.current += 1
    }
  }, [ownerId, onExpired])

  async function reload(append = false) {
    const request = ++version.current
    setLoading(true)
    setListError('')
    try {
      const result = await api.categories(ownerId, append ? page.items.length : 0)
      if (!live.current || request !== version.current) return false
      setPage((previous) => ({
        ...result,
        items: append ? [...previous.items, ...result.items] : result.items,
      }))
      return true
    } catch (failure) {
      if (live.current && request === version.current)
        failed(failure, 'Não foi possível carregar suas categorias.', setListError)
      return false
    } finally {
      if (live.current && request === version.current) setLoading(false)
    }
  }

  async function edit(id, desiredActive) {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    setError('')
    setSuccess('')
    try {
      const snapshot = await api.category(ownerId, id)
      if (!live.current) return
      setEditing({ ...snapshot, desiredActive })
      setName(snapshot.data.name)
      setType(snapshot.data.type)
      setBlocked(false)
      heading.current?.focus()
    } catch (failure) {
      if (live.current) failed(failure, 'Não foi possível consultar esta categoria.')
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  function reset() {
    setEditing(null)
    setName('')
    setBlocked(false)
    setError('')
  }

  async function reconcile() {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    try {
      if (await reload()) {
        reset()
        setSuccess('Lista atualizada. Confira as categorias antes de iniciar outro cadastro.')
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    if (sending.current || blocked) return
    if (!name.trim() || Array.from(name.trim()).length > 100) {
      setError('Informe um nome com até 100 caracteres.')
      return
    }
    sending.current = true
    setBusy(true)
    setError('')
    setSuccess('')
    const statusChange = editing?.desiredActive !== undefined
    try {
      await api.saveCategory(
        ownerId,
        statusChange
          ? { is_active: editing.desiredActive }
          : editing
            ? { name: name.trim() }
            : { name: name.trim(), type },
        editing?.data.id,
        editing?.etag,
      )
      if (!live.current) return
      reset()
      setSuccess('Categoria salva. Seu histórico foi preservado.')
      await reload()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else if (failure.status === 409)
        setError(
          'Já existe uma categoria com esse nome e tipo, inclusive entre as desativadas. Escolha outro nome ou reative a existente.',
        )
      else if (failure.status === 412) {
        setBlocked(true)
        setError(
          'Esta categoria foi alterada em outro lugar. Suas alterações não foram salvas. Recarregue e revise os dados.',
        )
      } else if (failure.status === 0 || failure.status >= 500) {
        setBlocked(true)
        setError(
          'Não foi possível confirmar a alteração. Confira os dados atuais antes de tentar novamente.',
        )
      } else failed(failure, 'Não foi possível salvar. Confira os dados e tente novamente.')
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  const statusChange = editing?.desiredActive !== undefined
  const title = statusChange
    ? editing.desiredActive
      ? 'Reativar categoria'
      : 'Desativar categoria'
    : editing
      ? 'Editar categoria'
      : 'Nova categoria'
  return (
    <div className="accounts-layout">
      <section className="accounts-list" aria-labelledby="categories-heading" aria-busy={loading}>
        <div className="section-bar">
          <div>
            <h2 id="categories-heading">Suas categorias</h2>
            <p className="muted">Dê significado às suas receitas e despesas.</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading || busy}
            onClick={() => reload()}
          >
            Atualizar categorias
          </Button>
        </div>
        {listError && (
          <p role="alert" className="notice notice-error">
            {listError}
          </p>
        )}
        {loading && <p role="status">Carregando categorias…</p>}
        {!loading && !listError && page.items.length === 0 && (
          <div className="empty-accounts">
            <h3>Como você organiza seu dinheiro?</h3>
            <p>Crie categorias como Alimentação para despesas ou Salário para receitas.</p>
          </div>
        )}
        <ul className="account-cards" aria-label="Categorias cadastradas">
          {page.items.map((category) => (
            <li key={category.id} className="surface account-card">
              <h3>{category.name}</h3>
              <p className="account-type">
                {labels[category.type]}
                {!category.is_active && ' · Desativada'}
              </p>
              <div className="account-actions">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || blocked || Boolean(editing)}
                  onClick={() => edit(category.id)}
                >
                  Editar
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || blocked || Boolean(editing)}
                  onClick={() => edit(category.id, !category.is_active)}
                >
                  {category.is_active ? 'Desativar' : 'Reativar'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
        {page.has_more && (
          <Button
            type="button"
            variant="outline"
            disabled={loading || busy}
            onClick={() => reload(true)}
          >
            Carregar mais categorias
          </Button>
        )}
      </section>
      <section
        className="surface account-form"
        aria-labelledby="category-form-heading"
        aria-busy={busy}
      >
        <p className="eyebrow">Cada movimento tem seu lugar</p>
        <h2 id="category-form-heading" ref={heading} tabIndex={-1}>
          {title}
        </h2>
        {success && (
          <p role="status" className="notice notice-success">
            {success}
          </p>
        )}
        <form onSubmit={submit} aria-label={title}>
          <fieldset disabled={busy || blocked}>
            <legend className="sr-only">Dados da categoria</legend>
            {statusChange ? (
              <>
                <p>
                  <strong>{editing.data.name}</strong>
                </p>
                <p>
                  {editing.desiredActive
                    ? 'A categoria voltará a ficar ativa.'
                    : 'A categoria ficará desativada. Os lançamentos existentes e seu histórico serão preservados.'}
                </p>
              </>
            ) : (
              <>
                <label className="field" htmlFor="category-name">
                  Nome da categoria
                  <input
                    id="category-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    required
                    placeholder="Ex.: Alimentação"
                  />
                </label>
                <div className="field">
                  <label htmlFor="category-type">Tipo de categoria</label>
                  <select
                    id="category-type"
                    value={type}
                    onChange={(event) => setType(event.target.value)}
                    disabled={Boolean(editing)}
                  >
                    <option value="expense">Despesa</option>
                    <option value="income">Receita</option>
                  </select>
                </div>
                {editing && (
                  <p className="field-hint">
                    O tipo permanece protegido para manter a compatibilidade com os lançamentos
                    existentes.
                  </p>
                )}
              </>
            )}
            <Button type="submit" className="wide-button">
              {busy
                ? 'Salvando…'
                : statusChange
                  ? 'Confirmar alteração'
                  : editing
                    ? 'Salvar alterações'
                    : 'Cadastrar categoria'}
            </Button>
          </fieldset>
        </form>
        {error && (
          <p role="alert" className="notice notice-error">
            {error}
          </p>
        )}
        {blocked && !editing && (
          <Button type="button" variant="outline" disabled={busy} onClick={reconcile}>
            Conferir categorias
          </Button>
        )}
        {blocked && editing && (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => edit(editing.data.id, editing.desiredActive)}
          >
            Recarregar dados
          </Button>
        )}
        {editing && (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => {
              reset()
              void reload()
            }}
          >
            Voltar para categorias
          </Button>
        )}
        <p className="field-hint">
          Categorias de receita e despesa são separadas. Desativar preserva o histórico; não exclui
          registros.
        </p>
      </section>
    </div>
  )
}
