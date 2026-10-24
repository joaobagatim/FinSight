---
name: commit-review
description: Revisar mudanças antes de criar ou trocar branches, commitar, fazer push, abrir PR ou merge no FinSight. Use quando o usuário pedir revisão de diff, proposta de commit, estratégia de branch ou qualquer operação Git que dependa de aprovação explícita.
---

# Revisão pré-Git e commits incrementais

1. Ler `AGENTS.md` e seções 19–22 do `README_CODEX.md`. Conferir `docs/SESSION_STATE.md` e a última entrada aplicável de `docs/DEVLOG.md`.
2. Inspecionar Git **sem alterar o estado**: `git status --short --branch`, `git diff --stat`, `git diff`, `git diff --cached`, `git log -5 --oneline`; se não houver Git, informar isso claramente. Conferir `git diff --check` se aplicável.
3. Agrupar alterações por propósito. Recomendar branch temática apropriada. Não criar branch sem apresentar primeiro a intenção e receber autorização explícita.
4. Para cada commit proposto, registrar: **objetivo**, arquivos e linhas existentes confirmadas (ou arquivo novo), requisitos, impactos, riscos, testes realmente executados, resultados e mensagem curta em inglês no padrão Conventional Commits.
5. Procurar credenciais, `.env`, dumps, extratos, PII e dados bancários. Não imprimir conteúdo sensível no relatório. Impedir proposta de commit inseguro até correção.
6. Antes de executar qualquer operação Git que modifique estado ou remoto (inclusive `git switch -c`, `git checkout`, `git add`, `git commit`, `git push`, criar PR e merge), apresentar exatamente os comandos pretendidos e **solicitar autorização**. `git add` também deve estar coberto pelo plano de staging aprovado; não incluir arquivos extras.
7. Com autorização específica, executar somente a ação autorizada. Revalidar arquivos se o estado tiver mudado. Não presumir que autorização de commit cobre push ou PR.
8. Informar resultado **observado**: hash real ou erro, branch real, testes reais. Atualizar documentação no próximo conjunto de mudanças quando pertinente, sem gerar commit adicional sem aprovação.

## Modelo de relatório obrigatório

- **Operação solicitada:** criar branch / stage e commit / push / abrir PR / merge
- **O que foi feito / será feito:** ...
- **Por que e o que impacta:** ...
- **Arquivos / linhas:** `caminho:linhas` — mudança; para arquivo novo, marcar `novo`
- **Requisitos e riscos:** ...
- **Testes e evidências:** `comando` → PASSOU / FALHOU / NÃO EXECUTADO (motivo)
- **Comando Git e mensagem proposta:** ...
- **Pendências:** ...
- **Aprovação:** 'Autoriza esta ação específica?'

Não inventar line numbers, resultados ou links. Não criar branch permanente de testes: testes funcionais acompanham suas features.
