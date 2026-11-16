# ADR 0001 — Fronteiras de tarefa na conversa nativa

Data: 16/11/2026. Viabilidade #38; implementação #39; validação #40; entrega #32.
Estado: **implementação bloqueada por capacidade pública não demonstrada**.

## Decisão

Não implementar a troca automática de tarefa dentro do Claude Code interativo
com as interfaces verificadas. A #38 entrega esta investigação; #39, #40 e #32
continuam abertas. O bloqueio não significa impossibilidade em versões futuras.
Nenhuma mudança de comportamento do launcher foi autorizada por esta ADR.

Falta demonstrar uma operação pública que, ao reconhecer uma fronteira antes
de processar o prompt, aplique o modelo escolhido e isole a nova tarefa na
conversa nativa aberta. Observar o prompt e bloquear sua execução não oferece
esse controle. Reconhecer marcadores somente em `ctr run` também não atende #32.

## Superfícies verificadas

Consulta à documentação oficial em 16/11/2026; prova real em Linux x86_64,
Python 3.14.3, Claude Code **2.1.325**. A versão mínima do launcher permanece
2.1.251; não foram executadas provas nativas em todas as versões intermediárias.

| Superfície pública | O que permite | Lacuna para #32 |
| --- | --- | --- |
| `UserPromptSubmit` | Receber o prompt antes da inferência, permitir/bloquear, adicionar contexto e nomear sessão | Não documenta setter de modelo ou criação/troca de sessão |
| `UserPromptExpansion` | Observar/bloquear expansão de comandos e adicionar contexto | Não oferece os controles ausentes |
| `PreModelSwitch` | Permitir, negar ou pedir confirmação de uma troca já solicitada | Não inicia troca nem substitui o destino |
| `PostModelSwitch` | Observar uma troca já aplicada | Não a provoca nem a torna atômica com uma fronteira |
| `SessionStart` / `SessionEnd` | Observar início/fim; início admite contexto e mensagem inicial | Não solicitam outra sessão a partir do prompt |
| `/model`, `/clear`, `/resume` | Usuário muda modelo, abre contexto vazio e recupera sessão anterior | São comandos manuais separados; não há composição automática por hook demonstrada |
| CLI `--model`, `--session-id`, `--resume` | Launcher define modelo/identidade ao iniciar processo | Não controla o processo interativo já aberto |
| Settings `model`, variável `ANTHROPIC_MODEL` | Configuração de seleção, abaixo da seleção explícita | Alterar defaults não demonstra controle por prompt ou transação de sessão; mutação global afetaria outros terminais |
| Agent SDK `ClaudeSDKClient.set_model()` | Host SDK controla modelo da sessão que possui | Exigiria host/interface de conversa próprios; não demonstra controle sobre a TUI nativa existente |
| Skill com `model` | Override temporário durante o turno; volta ao modelo da sessão depois | Carrega conteúdo de skill e não mantém decisão por tarefa nem cria sessão isolada |

Fontes: [hooks e seus contratos de saída](https://code.claude.com/docs/en/hooks),
[CLI](https://code.claude.com/docs/en/cli-reference),
[configuração e prioridade de modelos](https://code.claude.com/docs/en/model-config#setting-your-model),
[sessões](https://code.claude.com/docs/en/sessions#manage-context-within-a-session),
[Agent SDK Python](https://code.claude.com/docs/en/agent-sdk/python#claudesdkclient),
[frontmatter de skills](https://code.claude.com/docs/en/skills#frontmatter-reference).
As lacunas da última coluna são a conclusão desta investigação, não uma promessa
do fornecedor sobre versões futuras.

`UserPromptSubmit` também pode receber eventos de tarefas agendadas, mensagens
de outras sessões e retornos de agentes. Uma futura integração deve distinguir
essas origens antes de reconhecer uma fronteira como pedido humano.

## Prova mínima nativa

O [roteiro e relatório](../native-boundary-feasibility.md) e a
[evidência sanitizada](../../evaluation/native-boundary-feasibility.json)
registram ordem, UUIDs, modelos e três respostas curtas, com ferramentas
desabilitadas e sem classificação por IA.

- Um prompt bloqueado não gerou resposta; o terminal continuou disponível.
- Pedido inicial, continuação e mudança explícita de assunto foram observados
  na mesma sessão, com respostas no mesmo Haiku. O hook ficou silencioso.
- O picker mudou para Sonnet somente após intervenção e confirmação nativas;
  foram observados `PreModelSwitch` e `PostModelSwitch`, source `picker`.
- `/clear` gerou outro UUID. `/resume UUID` recuperou a conversa anterior,
  incluindo sua escolha manual. Essas duas ações não consumiram turnos de IA.

O ensaio demonstra as capacidades positivas acima. A falta de um controle
suportado resulta do contrato público consultado; não se tentou provar uma
impossibilidade universal enviando campos JSON inventados ou inspecionando
endpoints privados. Nenhum experimento com SDK foi necessário para concluir
que uma interface própria não satisfaz o aceite da conversa nativa.

## Contrato exigido antes de desbloquear #39

| Situação | Comportamento obrigatório da futura integração |
| --- | --- |
| Nova tarefa clara | Confirmar a fronteira quando necessário, classificar localmente no máximo uma vez, preservar tarefa anterior e aplicar modelo antes de executar o prompt em nova identidade |
| Continuação | Preservar identidade, contexto, escolha e ID compatível; zero classificações |
| Ambiguidade, citação, negação ou instrução composta sem fronteira inequívoca | Não encerrar/trocar tarefa; manter contexto e oferecer escolha explícita ao usuário |
| Override manual | Tem prioridade até uma nova fronteira confirmada; observações automáticas não reescrevem intenção |
| Reinício/retomada | Reutilizar decisão persistida; não usar o prompt de continuação para decidir modelo |
| Falha entre reconhecer e aplicar a decisão | Não finalizar tarefa anterior nem executar prompt no destino errado; informar falha, sem retry remoto ou troca silenciosa |
| Recuperação | Preservar origem e decisão; novo UUID/contexto somente por ação explícita, como `recover` já faz |
| Concorrência e hooks atrasados | Locks por tarefa, identidade de execução e revisão de escolha impedem observações de outra execução de confirmar/alterar a atual |
| Privacidade | Prompt apenas em memória para regras limitadas; banco sem texto, transcrição ou credenciais; zero instruções de roteamento no contexto |

Antes da implementação, uma nova prova deve demonstrar controle **e ordem**:
evento de entrada → decisão local única → aplicação confirmada de modelo e
identidade → primeira resposta no destino. Também deve demonstrar abortar a
transição sem perder a tarefa anterior. O custo de integrar um host SDK ou
recriar entrada/saída, permissões e ciclo de terminal é maior que acrescentar
um hook, e muda o produto. Só se justifica com escopo revisto e evidência.

## Alternativa segura e desbloqueio

O fluxo disponível continua sendo sair e executar `ctr new`, ou retomar com
`ctr resume`. `/model` e `/clear` mantêm sua semântica nativa e não criam
fronteiras gerenciadas no banco. Um aviso/bloqueio de hook poderia pedir ação
manual, mas não entregaria a capacidade pedida; não foi adicionado.

Não usar automação de teclas como mecanismo de produção, alteração do binário,
proxy, login capturado, endpoint privado ou instruções de classificação no
contexto. O PTY do ensaio serve apenas para testar comandos públicos.

Desbloquear #39 exige interface pública que satisfaça o contrato e prova na
TUI. Desbloquear o aceite de #40 exige também #30: máquina macOS com conta
autorizada. A CI simulada não substitui nenhuma dessas duas evidências.
