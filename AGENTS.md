# FinSight — Instruções permanentes para o Codex

> Este arquivo se aplica à pasta em que está localizado e às suas subpastas. Para abranger todo o repositório, coloque-o na raiz do repositório. Em caso de dúvida sobre produto, consulte `README_CODEX.md`; para continuidade consulte `docs/SESSION_STATE.md` e `docs/DEVLOG.md`.

O `README_CODEX.md` é a especificação técnica para o Codex. O `README.md` na raiz do repositório, quando existir, é a apresentação pública para o GitHub. Não sobrescrever o README público durante a atualização de regras técnicas.

## Contexto e stack

FinSight é um produto financeiro pessoal **multiusuário desde o MVP**. Frontend: React + JavaScript (JSX), Vite, Tailwind CSS, shadcn/ui e Recharts. Backend: Python + FastAPI, PostgreSQL, SQLAlchemy e Alembic. Testes E2E e API: Playwright **com TypeScript**; testes unitários/backend: Pytest. CI: GitHub Actions. Infra local: Docker Compose.

Siga o escopo e a modelagem no `README_CODEX.md`. No MVP: contas, categorias, receitas/despesas, transferências, metas, dashboard e importação CSV com revisão. PDF após CSV; cartões/faturas na V2.0; múltiplas moedas no futuro. Não implemente funcionalidades fora do escopo sem aprovação.

## Leitura e continuidade

1. No início de cada sessão, leia o `README_CODEX.md` (especialmente seções 18–22), `docs/SESSION_STATE.md` e trechos relevantes de `docs/DEVLOG.md`.
2. Confira o repositório com **comandos Git somente de leitura**, como `git status --short --branch`, `git log -5 --oneline` e `git diff --stat` (quando houver Git). Não assuma que o checkpoint está atualizado.
3. Se houver alterações não reconhecidas, conflitos, contexto ausente ou divergências, sinalize antes de editar ou descartar trabalho.
4. Mantenha `docs/DEVLOG.md` com evidências reais e `docs/SESSION_STATE.md` com o próximo passo seguro. Use a Skill `$evidencias` para registrar progresso e `$retomar` para retomadas.

## Portão de aprovação Git — obrigatório

**Antes de cada ação que cria/troca branch, executa commit, push, abre PR ou faz merge, pare e peça autorização explícita daquela ação.** Não agrupe aprovações futuras nem presuma autorização por um pedido genérico de implementação. É permitido consultar status/diff/log sem aprovação.

Antes da ação, apresente em português:
- O que foi feito ou será feito e por que.
- Impactos (API, banco, interface, segurança, testes, documentação), requisitos RF/RNF envolvidos e riscos.
- Arquivos e trechos afetados, com caminhos relativos e **linhas reais verificadas**; se não houver linhas ainda, diga que são arquivos novos/planejados.
- Testes executados e resultado factual (ou `NÃO EXECUTADO` com motivo).
- Comando/ação Git específica, branch de origem/destino quando aplicável e mensagem curta de commit em inglês.
- O que permanece pendente e pedido inequívoco de autorização.

Aprovação para **branch não autoriza commit**; aprovação para commit não autoriza push/PR/merge. Se a conversa reiniciar, peça autorização novamente antes de ações ainda não executadas.

## Fluxo de contribuição

- `main` é estável. Desenvolver em branches temáticas: `feature/*`, `fix/*`, `test/*`, `refactor/*`, `chore/*`, `docs/*` e `ci/*` **após aprovação de criação/troca**.
- Testes de uma funcionalidade ficam na mesma branch dela. `test/*` é somente para trabalho independente em automação/infra de testes; não criar branch permanente de testes.
- Commits pequenos, coerentes e em inglês, preferencialmente Conventional Commits, com aprovação individual. Antes de commitar, conferir `git diff` e selecionar arquivos específicos; não usar `git add .` indiscriminadamente.
- Não fazer push, abrir PR nem merge automaticamente. Preparar descrição de PR com escopo, requisitos, testes, riscos e referência ao DEVLOG; pedir aprovação antes de abrir.
- Nunca usar `git reset --hard`, `git clean -fd`, `git push --force` ou apagar trabalho sem autorização específica.

## Segurança e privacidade — repositório público

- Nunca incluir `.env` real, tokens, senhas, segredos JWT, credenciais de banco, extratos financeiros reais, dados de usuários ou backups privados em código, logs, testes, capturas ou commits.
- Usar `.env.example` com placeholders e dados fictícios para seeds, fixtures e demo. Se detectar segredo exposto, avisar e recomendar revogação/rotação, sem reproduzi-lo.
- Autenticar e autorizar **cada recurso** por usuário no backend; conhecer um UUID não autoriza acesso. Não confiar em `user_id` fornecido pelo cliente.
- Usar `NUMERIC`/`Decimal` para dinheiro; preservar integridade das transferências; evitar dupla contabilização/duplicatas em importações.
- Não publicar dados reais em screenshots/evidências. Priorizar evidências reproduzíveis e sintéticas.
- Não escolher licença automaticamente.

## Qualidade e comunicação

- Manter frontend em JS e testes Playwright em TS. Criar testes relevantes para mudanças funcionais; executar verificações disponíveis e relatar as não executadas.
- Não inventar progresso, saídas, números de linhas, URLs de PR ou hashes.
- Explicar decisões técnicas de modo didático para estudo posterior. Registrar no DEVLOG por unidade lógica de trabalho.
- Este `AGENTS.md` é a regra persistente; Skills aprofundam procedimentos. Se houver conflito, parar e solicitar esclarecimento, priorizando segurança e a exigência de aprovação.
