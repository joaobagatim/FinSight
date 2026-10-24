---
name: evidencias
description: Documentar implementações, decisões de arquitetura, testes e evidências do FinSight para estudo e auditoria. Use após mudanças relevantes, antes de pedir aprovação de commit, ao concluir testes ou quando o usuário solicitar um resumo técnico do que foi feito.
---

# Diário técnico e evidências

1. Ler `AGENTS.md`, README seções 21–22 e as últimas entradas de `docs/DEVLOG.md`.
2. Inspecionar arquivos modificados e evidências reais; diferenciar claramente **planejado**, **implementado**, **validado**, **falhou** e **não testado**.
3. Para cada unidade lógica, adicionar entrada cronológica ao `docs/DEVLOG.md` (preferencialmente append-only):
   - Data e título; requisitos RF/RNF/RN pertinentes; status.
   - O que foi alterado, por que e **como funciona** (didático e objetivo).
   - Impactos e riscos, especialmente segurança, isolamento multiusuário e dinheiro.
   - Caminhos relativos e linhas **verificadas** via ferramenta de busca/editor (`arquivo:Lx-Ly`), ou arquivo/função quando as linhas não puderem ser verificadas.
   - Evidências: comandos executados, resultado factual e links para CI/PR somente se existirem.
   - Testes: PASSOU / FALHOU / NÃO EXECUTADO com motivo.
   - Branch, commit e PR verificados, ou 'pendente de autorização'.
   - Pendências e próximo passo curto.
4. Atualizar `docs/SESSION_STATE.md` como checkpoint: tarefa, progresso, Git observado, bloqueios, testes, aprovações pendentes, próximo passo seguro.
5. Usar somente dados sintéticos/sanitizados. Não copiar `.env`, tokens, senhas, PDFs/CSVs financeiros reais, PII, backups ou logs sensíveis para evidências. Evitar arquivos gerados grandes.
6. Antes de cada commit, incluir essas alterações documentais no relatório pré-commit; **não commitar** nem criar branch sem aprovação. Registrar que documentação pendente não equivale a commit existente.
7. Se verificações não foram realizadas, relatar sem inventar. Não afirmar 'aprovado' ou 'concluído' sem base observável.

## Entrada sugerida

```md
## AAAA-MM-DD — Título
- **Requisito:** RF-... / RNF-...
- **Status:** implementado (não validado) | validado | bloqueado
- **Mudança:** ...
- **Motivo e funcionamento:** ...
- **Impactos:** ...
- **Onde:** `arquivo.ext:Lx-Ly` — ...
- **Evidências:** `comando` → resultado real
- **Testes:** ...
- **Git:** branch/commit/PR verificados ou pendente
- **Riscos e pendências:** ...
- **Próximo passo:** ...
```
