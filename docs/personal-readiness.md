# Prontidão para uso pessoal — #23

O usuário esclareceu que não pretende vender o projeto. O objetivo desta
etapa é uso próprio confiável no Claude Code; comercialização, marca,
cobrança, suporte contratado e concessão de licença pública saíram do escopo.
A licença não foi alterada. Codex não foi acrescentado como backend.
A release funcional v1.0.0 e suas evidências continuam preservadas.

## Entregas prioritárias

| Área | Entrega | Evidência |
| --- | --- | --- |
| Tarefa nova/continuação | `run`, atalho com prompt, abertura da última tarefa, marcadores PT/EN, recência, override e proteção contra erro anterior | [guia diário](daily-use.md), test_boundary.py/test_launcher.py |
| Classificação | Prefixo simples não desativa risco; restrições de formato não forçam tier maior sozinhas | política v4, corpus fixo, regressões adversariais |
| Modelos e login | Interface/auth sanitizada; check nativo com zero turnos; probe real explícito e falhas visíveis | [modelos e erros](models-and-errors.md), teste nativo 2.1.323 e regressões |
| Execução/sessão | Timeout print com código 124, sinal ao grupo, locks até o fim, UUID/decisão preservados, recuperação explícita | test_launcher.py e smokes reais |
| Segurança/privacidade | Estado 0700/0600, recusa de symlink/hardlink/FIFO, nomes sem controles invisíveis e diagnóstico por campos permitidos | [SECURITY.md](../SECURITY.md), test_state.py/test_launcher.py |
| Operação simples | Setup validado, backup consistente, restauração em estado novo, uninstall gerenciado preservando dados | [manutenção](maintenance.md), test_maintenance.py/test_install.py |
| Integridade durante manutenção | Tarefa instalada mantém lease; atualização/remoção recusadas enquanto o cliente roda, inclusive com estado personalizado | integração com artefato instalado em test_install.py |
| Eficiência medida | Resultados positivos e negativos preservados, verificadores objetivos e orçamento limitado | [relatório real](real-efficiency.md) e três relatórios JSON |
| CI/distribuição | Actions fixadas em SHA, cancelamento de execução substituída, timeout, suíte/avaliação/wheel fora do checkout em Linux/macOS | workflow CI; release 1.1.0 somente após CI final aprovada |

80 testes passaram localmente. O pacote instalado verifica setup, modelos,
entrada automática, retomada, override/hook, diagnóstico e backup/restauração
fora da árvore fonte. A descrição da release v1.1.0 registra o commit e a
execução final de CI, além do checksum do wheel distribuído.
O [smoke pessoal real](personal-validation.md) registra a instalação 1.1.0,
Claude 2.1.325, picker só na sessão, retomada automática e saída por Ctrl-C.

## Limites que não podem ser vendidos como garantias

O classificador e a fronteira de tarefa são heurísticos. Não compreendem
toda linguagem, código citado, contexto de arquivos ou mudanças de assunto
dentro do terminal já aberto. Sem marcador claro, um novo prompt em `run`
é tarefa nova; `--continue`, UUID e `--new` resolvem dúvidas explicitamente.
Não há reclassificação de continuações nem classificador remoto no contexto.

O ensaio v4 mostrou custo estimado menor e tempo menor no conjunto conhecido,
mas **mais tokens**. O v3 inicial piorou todas as três métricas. Não há prova
de economia geral, redução de tokens, faturamento real ou qualidade em tarefas
arbitrárias. Essa lacuna é visível; não será preenchida com percentuais
inventados. A escolha de modelos deve continuar inspecionável e reversível.

Autenticação e restrições de modelo são do Claude/provedor. Um check local
não garante autorização futura. O launcher não impede todos os fallbacks
internos; uma observação de modelo não comprova todas as respostas. Erros
nativos permanecem visíveis e não disparam retry nem troca silenciosa.

O estado não é criptografado e não isola malware com o mesmo usuário do SO.
Backups têm metadados privados. Histórico e política de retenção do Claude
são separados. A instalação deve permanecer pessoal, em diretório dedicado.

## Validações pendentes e itens futuros

- **macOS com conta e terminal nativo:** não foi executado neste host Linux.
  A CI cobre o SO, subprocessos, sinais, locks, instalação e artefato com
  cliente simulado. O roteiro de PTY está disponível; não se afirma homologação
  de conta real macOS. É necessário realizá-lo antes de confiar nesse fluxo
  em uma máquina macOS específica.
- **Economia/qualidade no trabalho real do usuário:** acompanhar tarefas reais
  diversas e qualidade revisada pelo usuário antes de generalizar o resultado
  das microtarefas. O harness opt-in está pronto, sem coleta automática.
- **Fatura/quota:** não foram auditadas. O CLI fornece estimativas; a conta
  usada tem autenticação de assinatura, sem comprovação de preço faturado.
- **Mais linguagem/contexto na detecção:** futuro, se o uso mostrar necessidade;
  não justificar proxy, servidor ou IA extra por mensagem só para isso.
- **Assinatura de artefatos, instalador binário, frontend, cobrança e marca:**
  não necessários para o uso próprio atual; não implementados.

Não há bloqueio técnico conhecido nos fluxos Linux cobertos pelos testes,
mas isso não equivale a 100% de certeza nem encerra as validações acima.
Falhas novas devem gerar issue com reprodução e diagnóstico sanitizado.
