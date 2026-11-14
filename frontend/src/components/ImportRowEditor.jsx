import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { parseMoney } from '@/lib/money'

const fields = (row) => ({
  date: row.transaction_date ?? '',
  description: row.description ?? '',
  amount: row.amount?.replace('.', ',') ?? '',
  type: row.type ?? '',
  category_id: row.category_id ?? '',
})

export default function ImportRowEditor({ ownerId, jobId, rowId, onExpired, onSaved, onClose }) {
  const [snapshot, setSnapshot] = useState(null)
  const [form, setForm] = useState(null)
  const [categories, setCategories] = useState({ items: [], has_more: false })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const live = useRef(false),
    working = useRef(true),
    heading = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    working.current = true
    heading.current?.focus()
    Promise.all([api.importRow(ownerId, jobId, rowId), api.categories(ownerId)])
      .then(([row, page]) => {
        if (current) {
          setSnapshot(row)
          setForm(fields(row.data))
          setCategories(page)
          setBlocked(false)
        }
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else
          setError('Não foi possível consultar o registro e suas categorias. Recarregue a revisão.')
      })
      .finally(() => {
        if (current) {
          working.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, jobId, rowId, onExpired, refresh])
  function reload() {
    if (working.current) return
    working.current = true
    setLoading(true)
    setError('')
    setSnapshot(null)
    setForm(null)
    setRefresh((value) => value + 1)
  }
  async function more() {
    if (working.current) return
    working.current = true
    setLoading(true)
    setError('')
    try {
      const page = await api.categories(ownerId, categories.items.length)
      if (live.current)
        setCategories((previous) => ({ ...page, items: [...previous.items, ...page.items] }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais categorias.')
    } finally {
      working.current = false
      if (live.current) setLoading(false)
    }
  }
  async function save(event) {
    event.preventDefault()
    if (working.current || blocked || !snapshot || !form) return
    setError('')
    let data
    try {
      const amount = parseMoney(form.amount),
        description = form.description.trim()
      if (amount.startsWith('-') || amount === '0.00')
        throw new Error(
          'Informe um valor absoluto maior que zero; o tipo define receita ou despesa.',
        )
      if (!description || Array.from(description).length > 255 || /\p{C}/u.test(description))
        throw new Error(
          'Use uma descrição de 1 a 255 caracteres, sem quebras de linha ou caracteres não permitidos.',
        )
      if (!form.date || !['income', 'expense'].includes(form.type))
        throw new Error('Confira a data e o tipo do registro.')
      data = {
        transaction_date: form.date,
        description,
        amount,
        type: form.type,
        category_id: form.category_id || null,
      }
    } catch (failure) {
      setError(failure.message)
      return
    }
    working.current = true
    setBusy(true)
    let saved = null
    try {
      const response = await api.updateImportRow(ownerId, jobId, rowId, data, snapshot.etag)
      if (live.current) saved = response.data
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(failure.status !== 422)
        setError(
          failure.status === 412
            ? 'Este registro mudou em outra operação. Recarregue a revisão e confira os dados antes de salvar.'
            : failure.status === 422
              ? 'Confira a data após a abertura, valor, tipo e uma categoria ativa compatível da sua conta.'
              : failure.status === 409
                ? 'Esta prévia não permite mais revisão deste registro. Recarregue para conferir.'
                : 'Não foi possível confirmar o resultado. Recarregue o registro antes de enviar novamente.',
        )
      }
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
    if (saved && live.current) onSaved(saved)
  }
  const options = form
    ? categories.items.filter((category) => category.is_active && category.type === form.type)
    : []
  return (
    <section
      className="surface account-form import-row-editor"
      aria-labelledby="import-row-edit-heading"
      aria-busy={loading || busy}
    >
      <h3 id="import-row-edit-heading" ref={heading} tabIndex={-1}>
        Revisar registro{snapshot ? ' ' + snapshot.data.row_number : ''}
      </h3>
      <p className="field-hint">
        Salvar uma correção desmarca o registro. Confira novamente e selecione-o na prévia quando os
        dados estiverem prontos. Isso não cria lançamentos. Alterações sem salvar ficam apenas nesta
        tela.
      </p>
      {loading && <p role="status">Consultando revisão…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {snapshot && !snapshot.data.editable && (
        <p className="notice notice-error">
          Este registro está disponível somente para consulta. Confira a situação da conta e da
          prévia.
        </p>
      )}
      {snapshot && form && (
        <form onSubmit={save} aria-label="Corrigir registro da prévia">
          <fieldset disabled={loading || busy || blocked || !snapshot.data.editable}>
            <label className="field" htmlFor="review-date">
              Data do registro
              <input
                id="review-date"
                type="date"
                required
                value={form.date}
                onChange={(event) =>
                  setForm((previous) => ({ ...previous, date: event.target.value }))
                }
              />
            </label>
            <label className="field" htmlFor="review-description">
              Descrição do registro
              <input
                id="review-description"
                required
                value={form.description}
                onChange={(event) =>
                  setForm((previous) => ({ ...previous, description: event.target.value }))
                }
              />
            </label>
            <label className="field" htmlFor="review-amount">
              Valor absoluto (R$)
              <input
                id="review-amount"
                required
                inputMode="decimal"
                value={form.amount}
                onChange={(event) =>
                  setForm((previous) => ({ ...previous, amount: event.target.value }))
                }
              />
            </label>
            <label className="field" htmlFor="review-type">
              Tipo do registro
              <select
                id="review-type"
                required
                value={form.type}
                onChange={(event) =>
                  setForm((previous) => ({
                    ...previous,
                    type: event.target.value,
                    category_id: '',
                  }))
                }
              >
                <option value="">Selecione o tipo</option>
                <option value="expense">Despesa</option>
                <option value="income">Receita</option>
              </select>
            </label>
            <label className="field" htmlFor="review-category">
              Categoria do registro
              <select
                id="review-category"
                value={form.category_id}
                onChange={(event) =>
                  setForm((previous) => ({ ...previous, category_id: event.target.value }))
                }
              >
                <option value="">Sem categoria — ainda não poderá selecionar</option>
                {options.map((category) => (
                  <option value={category.id} key={category.id}>
                    {category.name}
                  </option>
                ))}
                {form.category_id &&
                  !options.some((category) => category.id === form.category_id) && (
                    <option value={form.category_id} disabled>
                      {snapshot.data.category_name ?? 'Categoria anterior'} — indisponível nesta
                      lista
                    </option>
                  )}
              </select>
            </label>
            <p className="field-hint">
              Escolha uma categoria ativa do mesmo tipo para liberar a seleção. Confira
              transferências e estornos no arquivo; não os trate automaticamente como receita ou
              despesa.
            </p>
            <Button type="submit">Salvar correção do registro</Button>
          </fieldset>
        </form>
      )}
      {categories.has_more && (
        <Button type="button" variant="outline" disabled={loading || busy} onClick={more}>
          Carregar mais categorias para revisão
        </Button>
      )}
      <div className="account-actions">
        <Button type="button" variant="outline" disabled={loading || busy} onClick={reload}>
          Recarregar revisão do registro
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
          Voltar à prévia
        </Button>
      </div>
      <p className="field-hint">
        Recarregar descarta alterações locais não salvas e consulta a versão atual.
      </p>
    </section>
  )
}
