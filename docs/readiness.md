# Critérios de prontidão

Revisão de 13/11/2026 após esclarecimento do usuário sobre o planejamento do projeto inteiro. A V0.1 entregou um launcher funcional, 31 testes e smoke real de criação/retomada. Todas as suas 11 issues foram concluídas, mas isso não estabelece prontidão final. A V1.0 permanece aberta até cumprir os critérios abaixo.

O escopo final continua sendo o launcher local para Claude Code em Linux/macOS, com tarefa iniciada explicitamente, decisão local no início, continuidade e override manual. Não é necessário acrescentar interface web, proxy, Windows ou roteamento do Codex para concluir esse escopo.

| Requisito original | Evidência atual | O que falta para encerrar |
| --- | --- | --- |
| Pesquisar interfaces e usar mecanismo real para selecionar modelo | ADR, opções CLI verificadas e smoke real | Conferência final das interfaces suportadas em #22 |
| Classificar localmente e priorizar economia/qualidade | Regras PT/EN e benchmark de latência | Avaliação independente e calibração em #17 e #18 |
| Escolher somente no início, sem reclassificar continuação | Testes de new/resume e smoke real | Entregue em #13; model separado de effective_model e resolved_model |
| Manter modelo durante as continuações | ID explícito persistido no fluxo básico | Entregue em #13/#14; divergências registradas e confirmação por execução, sem garantia sobre o provedor |
| Permitir alteração manual | Comandos model/--model e hook simulados | Homologar /model no terminal real, #20 |
| Solução leve, sem chamadas de classificação e sem instruções extras no contexto | Biblioteca padrão, zero inferência na classificação, hooks silenciosos | Manter esses limites na avaliação e regressão, #18 e #22 |
| Instalar e usar com continuidade confiável | Comando local instalado, CI Linux/macOS | Recuperação e migrações entregues em #15; testes finais do artefato em #21 |
| Planejar o projeto inteiro com issues/subissues | V0.1 encerrada e V1.0 com vínculos nativos | Encerrar somente mediante aceite das entregas #12, #16 e #19 |

## Lacunas da revisão e situação após #12

- Corrigido em #13: eventos auto não substituem mais a escolha solicitada nem o ID compatível já fixado. A migração recupera escolhas manuais anteriores.
- Corrigido em #14: cada execução invalida a confirmação anterior e recebe execution_id próprio; hooks e transcrições atrasados não substituem escolhas atuais.
- “Renomeie a variável e corrija o algoritmo de consenso” recebe economy. O caso mostra que uma intenção trivial reconhecida pode dominar trabalho adicional não reconhecido (#17 e #18).
- O smoke real validou print/new/resume; a interface interativa `/model` foi validada apenas por simulação (#20).

## Encerramento

A [milestone V1.0](https://github.com/Buraddomoon/claude-task-router/milestone/2) tem três entregas:

- Entrega implementada e validada: [#12 — estabilidade da escolha e recuperação](https://github.com/Buraddomoon/claude-task-router/issues/12), com #13, #14 e #15.
- [#16 — classificação avaliada independentemente](https://github.com/Buraddomoon/claude-task-router/issues/16), com #17 e #18.
- [#19 — homologação e versão final reproduzível](https://github.com/Buraddomoon/claude-task-router/issues/19), com #20, #21 e #22.

A conferência #22 deve relacionar código, testes e evidências aos requisitos. Políticas internas do Claude/provedor precisam ter comportamento e limites explícitos; não podem ser apresentadas como garantia absoluta de um launcher externo. Não existe uma porcentagem de conclusão tecnicamente comprovada neste momento. Novas falhas encontradas nessa conferência devem ser registradas antes do encerramento, sem ampliar artificialmente o escopo.
