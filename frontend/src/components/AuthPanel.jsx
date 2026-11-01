import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'

export default function AuthPanel({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const registering = mode === 'register'

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    const length = Array.from(password).length
    if (length < 15 || length > 128 || !password.trim()) {
      setError('Use uma senha entre 15 e 128 caracteres, que não contenha apenas espaços.')
      return
    }
    if (registering && (!name.trim() || Array.from(name.trim()).length > 120)) {
      setError('Informe um nome com até 120 caracteres.')
      return
    }
    setBusy(true)
    setError('')
    setMessage('')
    try {
      if (registering) {
        await api.register({ name: name.trim(), email: email.trim(), password })
        setMode('login')
        setName('')
        setMessage('Solicitação recebida. Entre com seu e-mail e senha para continuar.')
      } else {
        onAuthenticated(await api.login(email.trim(), password))
      }
    } catch (failure) {
      setError(
        errorMessage(
          failure,
          registering
            ? 'Confira os dados do cadastro e tente novamente.'
            : 'Não foi possível entrar com esses dados. Confira seu e-mail e senha.',
        ),
      )
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  function changeMode() {
    setMode(registering ? 'login' : 'register')
    setPassword('')
    setError('')
    setMessage('')
  }

  return (
    <section className="access-layout" aria-labelledby="access-title">
      <div className="access-intro">
        <p className="eyebrow">Comece pelo que importa</p>
        <h1 id="access-title">
          {registering ? 'Um novo olhar para o seu dinheiro.' : 'Seu próximo passo começa aqui.'}
        </h1>
        <p>Um espaço para organizar suas contas, com mais clareza e no seu ritmo.</p>
        <span className="access-decoration" aria-hidden="true">
          F.
        </span>
      </div>
      <div className="surface access-card">
        <h2>{registering ? 'Criar seu acesso' : 'Entrar no FinSight'}</h2>
        <p className="muted">
          {registering ? 'Preencha seus dados para começar.' : 'Que bom ter você por aqui.'}
        </p>
        {message && (
          <p className="notice notice-success" role="status">
            {message}
          </p>
        )}
        <form
          onSubmit={submit}
          aria-label={registering ? 'Cadastro' : 'Entrar'}
          aria-describedby={error ? 'access-error' : undefined}
        >
          <fieldset disabled={busy}>
            <legend className="sr-only">Dados de acesso</legend>
            {registering && (
              <label className="field" htmlFor="access-name">
                Nome
                <input
                  id="access-name"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                />
              </label>
            )}
            <label className="field" htmlFor="access-email">
              E-mail
              <input
                id="access-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="field" htmlFor="access-password">
              Senha
              <input
                id="access-password"
                type="password"
                autoComplete={registering ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                aria-describedby="password-hint"
              />
            </label>
            <p id="password-hint" className="field-hint">
              Use entre 15 e 128 caracteres. Sua senha diferencia espaços e letras maiúsculas.
            </p>
            {error && (
              <p id="access-error" className="notice notice-error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="wide-button">
              {busy ? 'Aguarde…' : registering ? 'Criar acesso' : 'Entrar'}
            </Button>
          </fieldset>
        </form>
        <p className="access-switch">
          {registering ? 'Já tem cadastro?' : 'Primeira vez por aqui?'}{' '}
          <button type="button" className="text-button" disabled={busy} onClick={changeMode}>
            {registering ? 'Entrar na conta' : 'Criar acesso'}
          </button>
        </p>
      </div>
    </section>
  )
}
