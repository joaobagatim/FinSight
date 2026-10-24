import BrandMark from './components/BrandMark.jsx'
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
  return (
    <div className="app-shell min-h-screen">
      <a className="skip-link" href="#conteudo">
        Pular para o conteúdo
      </a>

      <header className="site-header">
        <a className="brand" href="#conteudo" aria-label="FinSight — início">
          <BrandMark />
          <span>
            FinSight<span className="brand-dot">.</span>
          </span>
        </a>
        <Button asChild variant="ghost" size="sm" className="about-link">
          <a href="#sobre">
            Sobre o projeto <span aria-hidden="true">↗</span>
          </a>
        </Button>
      </header>

      <main id="conteudo" tabIndex={-1}>
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
            <p>Estas possibilidades fazem parte do nosso plano e ainda não estão disponíveis.</p>
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
      </main>

      <footer className="site-footer">
        <span>FinSight</span>
        <p>Feito para enxergar além dos números.</p>
      </footer>
    </div>
  )
}
