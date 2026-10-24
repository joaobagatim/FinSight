---
name: retomar
description: Recuperar com segurança o contexto do FinSight após pausa, nova sessão, limite de tokens ou troca de agente. Use ao iniciar ou retomar trabalho e quando for necessário identificar progresso real, pendências, branch e próximo passo sem repetir implementações.
---

# Retomada segura do desenvolvimento

1. Ler `AGENTS.md`, `README_CODEX.md` (escopo, fases e seções 18–22), `docs/SESSION_STATE.md`, últimas entradas de `docs/DEVLOG.md` e ADRs pertinentes.
2. Verificar estado **real** do repositório com comandos não destrutivos: `git status --short --branch`, `git log -5 --oneline`, `git diff --stat`, `git diff --cached --stat`. Se não houver repositório Git ou arquivos, declarar lacunas, sem presumir estado.
3. Inspecionar os arquivos citados pelo checkpoint. Não tratar o DEVLOG como prova isolada. Confirmar implementação e testes quando viável; evitar repetir trabalhos finalizados.
4. Distinguir: (a) concluído e verificado, (b) implementado mas não verificado, (c) parcial, (d) ainda não iniciado, (e) dependente de aprovação.
5. Apresentar resumo em português: fase e objetivo, branch observada, arquivos relevantes, últimas evidências, estado do diff, riscos, divergências entre documentação e Git, **próximo passo mínimo e seguro**.
6. Corrigir o `SESSION_STATE.md` caso esteja desatualizado, após explicar divergências; não sobrescrever trabalho de usuário nem descartar alterações. Não realizar ações Git que modifiquem estado sem aprovação.
7. Se próximo passo pedir criar/trocar branch, commit, push, PR ou merge, usar `$commit-review` e obter autorização específica antes de executar. Aprovações de sessões anteriores não se estendem automaticamente a ações pendentes.
8. Caso faltem informações, pedir somente o mínimo necessário para evitar prejuízo, mostrando primeiro o que foi possível comprovar.

## Saída resumida

- **Estado atual comprovado:** ...
- **Último trabalho e evidências:** ...
- **Diferenças em relação ao checkpoint:** ...
- **Aprovações pendentes:** ...
- **Próximo passo seguro:** ...
