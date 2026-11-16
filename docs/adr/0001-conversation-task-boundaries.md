# ADR 0001 — Fronteiras de tarefa na conversa nativa

Data: 16/11/2026. Viabilidade #38; implementação #39; validação #40; entrega #32.
Estado: **supervisão nativa comprovada em Linux; implementação experimental;
aceite completo de #32/#39/#40 pendente**.

## Decisão

Usar um supervisor opt-in (`--conversation-routing`) para substituir o processo
Claude no mesmo terminal quando uma fronteira explícita é reconhecida. O hook
segura o prompt; o supervisor encerra o cliente antigo com SIGTERM, espera sua
saída e inicia outra TUI nativa com `--model` e `--session-id`. O prompt passa
por socket Unix privado, somente em memória. Nenhuma tecla é sintetizada.

A investigação inicial concluiu cedo demais que a ausência de setter no hook
bloqueava toda integração. A [nova prova](../native-supervisor-proof.md)
demonstrou a composição de hook público, supervisão POSIX e flags públicas da
CLI. O setter continua ausente; a substituição do processo resolve o controle
para fronteiras explícitas. A tela reinicia, sem o usuário sair ou executar
outro comando. Isso é diferente da troca de modelo dentro do mesmo processo.

A #38 entrega a viabilidade ampliada. #39 tem uma implementação experimental;
#40 publicou avaliação com recall insuficiente para mudanças livres. #32/#39/#40
continuam abertas. A opção exige Claude 2.1.295+ para bloquear falhas de hook;
o modo padrão e sua versão mínima 2.1.251 permanecem preservados.

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
| CLI `--model`, `--session-id`, `--resume` | Launcher define modelo/identidade ao iniciar processo | Usada pelo supervisor ao substituir o cliente; não muda modelo dentro do mesmo processo |
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
direto no hook resulta do contrato público consultado; não se tentou provar uma
impossibilidade universal enviando campos JSON inventados ou inspecionando
endpoints privados. Nenhum experimento com SDK foi necessário para concluir
que uma interface própria não satisfaz o aceite da conversa nativa.

## Contrato e pendências do aceite

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

O supervisor e seus testes demonstram controle **e ordem** para marcadores:
evento de entrada → decisão local única → aplicação confirmada de modelo e
identidade → primeira resposta no destino. Saída forçada, falha de estado ou
falha de inicialização não executam um retry; a tarefa anterior fica preservada.
O custo de integrar um host SDK ou
recriar entrada/saída, permissões e ciclo de terminal é maior que acrescentar
um hook, e muda o produto. Só se justifica com escopo revisto e evidência.

## Operação e pendências

Sem a opção experimental, o fluxo continua sendo sair e executar `ctr new`, ou
retomar com `ctr resume`. No modo experimental, `Nova tarefa: ...` / `New task: ...`
inicia a transição; mensagens sem fronteira inequívoca preservam tarefa/modelo,
com aviso visível quando há abstenção. `/model` continua sincronizado.
`/clear` e `/resume` nativos não criam tarefas gerenciadas: a gate bloqueia
prompts de UUID diferente; saia e retome pelo `ctr` para sincronizar a identidade.

Não usar automação de teclas como mecanismo de produção, alteração do binário,
proxy, login capturado, endpoint privado ou instruções de classificação no
contexto. O PTY do ensaio serve apenas para testar comandos públicos.

O controle antes bloqueado foi demonstrado em Linux. Ainda faltam detecção
de mudanças livres com os limiares fixados, maior cobertura de falhas nativas
e #30: máquina macOS com conta autorizada. A origem de `UserPromptSubmit`
também não distingue todas as mensagens humanas de eventos internos: não
homologamos este modo com tarefas agendadas ou retornos de agentes. A CI
simulada não substitui essas evidências. Ver [resultados](../../evaluation/conversation-boundary-results.json).
