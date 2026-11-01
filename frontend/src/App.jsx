import { useCallback, useEffect, useRef, useState } from 'react'
import BrandMark from './components/BrandMark.jsx'
import AuthPanel from './components/AuthPanel.jsx'
import AccountsPanel from './components/AccountsPanel.jsx'
import { api, errorMessage, watchSessionChanges } from '@/services/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const possibilities = [
  {
    number: '01',
    title: 'Organizar o presente',
    description: 'Reunir receitas e despesas para entender melhor o seu dia a dia.',
  },
  {
    number: '02',
    title: 'Enxergar o que importa',
    description: 'Transformar informações em uma visão mais clara da sua vida financeira.',
  },
  {
    number: '03',
    title: 'Planejar o amanhã',
    description: 'Acompanhar metas e dar mais direção aos seus próximos passos.',
  },
]

export default function App() {
  const [view, setView] = useState('home')
  const [user, setUser] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const main = useRef(null)
  const authVersion = useRef(0)

  useEffect(() => {
    if (view !== 'home') main.current?.focus()
  }, [view])

  useEffect(
    () =>
      watchSessionChanges(() => {
        authVersion.current += 1
        setUser(null)
        setBusy(false)
        setView('home')
        setNotice('Seu acesso mudou em outra aba. Acesse novamente para continuar.')
      }),
    [],
  )

  const authenticated = useCallback((profile) => {
    authVersion.current += 1
    setUser(profile)
    setView('accounts')
    setNotice('')
  }, [])

  const expired = useCallback(() => {
    authVersion.current += 1
    setUser(null)
    setView('access')
    setNotice('Sua sessão terminou. Entre novamente para continuar.')
  }, [])

  async function enter() {
    if (busy) return
    const version = ++authVersion.current
    setBusy(true)
    setNotice('')
    try {
      const profile = await api.profile()
      if (version === authVersion.current) {
        setBusy(false)
        authenticated(profile)
      }
    } catch (error) {
      if (version !== authVersion.current) return
      if (error.status === 401) {
        setUser(null)
        setView('access')
      } else {
        setNotice(errorMessage(error, 'Não foi possível acessar sua conta. Tente novamente.'))
      }
    } finally {
      if (version === authVersion.current) setBusy(false)
    }
  }

  async function logout() {
    if (busy) return
    setBusy(true)
    setNotice('')
    try {
      await api.logout()
      setUser(null)
      setView('home')
      requestAnimationFrame(() => main.current?.focus())
    } catch (error) {
      setNotice(errorMessage(error, 'Não foi possível confirmar a saída. Tente novamente.'))
    } finally {
      setBusy(false)
    }
  }

  function home() {
    authVersion.current += 1
    setBusy(false)
    setView('home')
  }

  return (
    <div className="app-shell min-h-screen">
      <a className="skip-link" href="#conteudo">
        Pular para o conteúdo
      </a>

      <header className="site-header">
        <a className="brand" href="#conteudo" aria-label="FinSight — início" onClick={home}>
          <BrandMark />
          <span>
            FinSight<span className="brand-dot">.</span>
          </span>
        </a>
        <nav className="header-actions" aria-label="Principal">
          {view === 'home' && (
            <Button asChild variant="ghost" size="sm" className="about-link">
              <a href="#sobre">
                Sobre o projeto <span aria-hidden="true">↗</span>
              </a>
            </Button>
          )}
          {view !== 'accounts' && (
            <Button type="button" size="sm" onClick={enter} disabled={busy}>
              {busy ? 'Aguarde…' : user ? 'Minhas contas' : 'Acessar FinSight'}
            </Button>
          )}
          {user && (
            <Button type="button" variant="outline" size="sm" onClick={logout} disabled={busy}>
              {busy ? 'Aguarde…' : 'Sair'}
            </Button>
          )}
        </nav>
      </header>

      <main id="conteudo" tabIndex={-1} ref={main}>
        {notice && (
          <p className="notice notice-error" role="alert">
            {notice}
          </p>
        )}
        {view === 'access' && <AuthPanel onAuthenticated={authenticated} />}
        {view === 'accounts' && user && (
          <section className="workspace">
            <p className="eyebrow">Seu espaço</p>
            <h1>Olá, {user.name}.</h1>
            <p className="muted workspace-description">
              Vamos organizar suas contas, um passo de cada vez.
            </p>
            <AccountsPanel key={user.id} ownerId={user.id} onExpired={expired} />
          </section>
        )}
        {view === 'home' && (
          <>
            <section className="hero" aria-labelledby="hero-title">
              <p className="eyebrow">Uma nova perspectiva financeira</p>
              <h1 id="hero-title">
                Mais clareza para cuidar do seu <em>amanhã.</em>
              </h1>
              <p className="hero-description">
                Cada escolha conta. Estamos construindo um espaço para você entender seu dinheiro,
                organizar o presente e planejar o que vem pela frente.
              </p>
              <Badge variant="outline" className="development-note">
                <span className="status-dot" aria-hidden="true" />
                <span>
                  Em desenvolvimento <span aria-hidden="true">·</span> Este é só o começo
                </span>
              </Badge>
              <span className="hero-decoration" aria-hidden="true">
                F
              </span>
            </section>
            <section className="about-section" id="sobre" aria-labelledby="about-title">
              <div className="section-heading">
                <p className="eyebrow">O que vem pela frente</p>
                <h2 id="about-title">Um olhar completo, passo a passo.</h2>
                <p>
                  Estas possibilidades fazem parte do nosso plano e ainda não estão disponíveis.
                </p>
              </div>
              <ul className="possibilities">
                {possibilities.map(({ number, title, description }) => (
                  <li key={number}>
                    <span className="possibility-number" aria-hidden="true">
                      {number}
                    </span>
                    <h3>{title}</h3>
                    <p>{description}</p>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </main>

      <footer className="site-footer">
        <span>FinSight</span>
        <p>Feito para enxergar além dos números.</p>
      </footer>
    </div>
  )
}
