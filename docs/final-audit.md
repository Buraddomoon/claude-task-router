# Conferência de encerramento V1.0 — #22

Revisão de 13/11/2026, após a homologação #20/#21 e a avaliação #17/#18.
Escopo conferido contra as entregas originais [#1](https://github.com/Buraddomoon/claude-task-router/issues/1),
[#4](https://github.com/Buraddomoon/claude-task-router/issues/4) e
[#7](https://github.com/Buraddomoon/claude-task-router/issues/7), complementadas
pelas portas de prontidão #12/#16/#19. Não se acrescentou backend de IDE,
Codex, Windows, classificação remota ou proxy.

| Requisito | Código | Verificação | Evidência |
| --- | --- | --- | --- |
| Interface real de seleção/continuidade | launcher.py: build_command/doctor/hook_settings | Flags locais do Claude 2.1.323 e smoke new/resume | [ADR](architecture.md), [smokes](validation.md) |
| Política local PT/EN, limitada e explicável | classifier.py/config.py | test_classifier.py; avaliação congelada e benchmark | [avaliação](classifier-evaluation.md), [relatório](../evaluation/results.json) |
| Classificação apenas no começo | cli.py: new/resume/recover | Retomada e recuperação com classificador/configuração que falham se chamados | test_launcher.py |
| Identidade e diretório original | state.py: create/get; launcher.py | Retomada em outro cwd; UUID único; latest por projeto | test_launcher.py/test_state.py e [PTY real](interactive-qa.md) |
| Separar escolha/efetivo/ID fixado | state.py: observe/launch_model | Fallback automático, manual, restauração e aliases divergentes | #13, test_state.py/test_launcher.py |
| Confirmar por execução e rejeitar hooks antigos | state.py: launched/observe/reconcile_transcript | Tokens de execução, timestamps e compare-and-set concorrente | #14, test_state.py |
| Controle manual e persistência | cli.py: model/resume; hook.py | /model real, override inicial/retomada, hook offline command/picker/sdk | [#20](interactive-qa.md), test_launcher.py |
| Terminal, stdout e código de saída | launcher.py: run | PTY real, SIGINT em grupo, SIGTERM, falhas do cliente e Popen | [#20](interactive-qa.md), test_launcher.py |
| Concorrência e privacidade | state.py: task_lock/connect | Lock entre processos, permissões 0700/0600, prompt ausente no banco | test_state.py/test_launcher.py |
| Recuperação explícita sem retry | cli.py: recover; state.py: recover | Sessão/projeto ausente, UUID novo, escolha/snapshot preservados | #15, test_launcher.py e [smoke real](validation.md) |
| Migração íntegra e recuperação de falhas | state.py: Store | v1/v2/v3, schema futuro, rollback de DDL e seis processos concorrentes | test_migrations.py |
| Artefato instalado independente do checkout | pyproject.toml; installed_smoke.py | Proveniência do módulo, versão metadata/CLI, new/resume/model e hooks instalados | [#21](installation.md), CI Linux/macOS |
| Atualização, colisão e rollback | scripts/install.py/install.sh | Novo venv antes da ativação, estado preservado, geração legada e falha de build | test_install.py e [guia](installation.md) |
| Runtime leve, sem rede na classificação | classifier.py e hooks silenciosos | Latência típica/máxima, socket/processo proibidos no teste de classificação, retomada sem classificação | test_classifier.py, benchmark, avaliação |
| Evidência e distribuição reproduzíveis | CI e release v1.0.0 | Suíte, wheel e avaliação nos três jobs; checksum e fonte fixada por tag | Checks/artefatos e descrição da release |

Os nomes de código/teste acima referem-se aos diretórios
[`claude_task_router/`](../claude_task_router/) e [`tests/`](../tests/).
O banco contém somente metadados, hash/tamanho do prompt e caminho validado
da transcrição; conteúdo de conversas e credenciais não são persistidos.

## Interfaces nativas reconferidas

`ctr doctor` e `claude --help` confirmaram `--model`, `--session-id`, `--resume`
e `--settings` em Claude Code 2.1.323. As fontes primárias foram reconferidas:
[CLI](https://code.claude.com/docs/en/cli-reference),
[seleção e padrão de modelos](https://code.claude.com/docs/en/model-config#setting-your-model),
[confirmação de fallback](https://code.claude.com/docs/en/model-config#ask-before-switching),
[PostModelSwitch](https://code.claude.com/docs/en/hooks#postmodelswitch).
O hook observa mudanças de sessão; cadeias de fallback por turno podem não
produzir esse evento. `/model nome` pode salvar o padrão do usuário; o picker
oferece `s` para troca só na sessão na versão atual. O launcher não interfere
nessas políticas nem promete fixar o provedor internamente.

## Sequência de liberação e referências

1. #20: PTY real com duas respostas curtas, troca manual, UUID preservado,
   continuação após Ctrl-C e ausência de processo/lock órfão. #21: pacote
   instalado fora da árvore, atualização e rollback. A CI `ea0f343` passou
   nos três jobs: [execução 43476570467](https://github.com/Buraddomoon/claude-task-router/actions/runs/43476570467).
2. #17: corpus/rubrica congelados em `c2e17d8`; #18: regras congeladas em
   `e28cecc`, depois avaliação reservada aprovada em `a97112d`.
3. Preparar pacote 1.0.0, executar suíte completa, benchmark, avaliação,
   instalação local e smoke do wheel fora do checkout.
4. Publicar o commit final; aguardar aprovação dos três jobs da CI desse
   commit. Somente então criar tag/release v1.0.0 com o SHA, link dessa
   execução, wheel e SHA256SUMS; fechar #22/#19 e a milestone.

O status de liberação é verificável na
[release v1.0.0](https://github.com/Buraddomoon/claude-task-router/releases/tag/v1.0.0),
cuja descrição registra a CI do commit final sem exigir uma alteração
autorreferente neste documento. A reprodutibilidade é funcional: fonte
fixada, testes e artefatos identificados por hash. Não se promete identidade
binária de builds feitos com versões diferentes de Python/setuptools.

## Limitações remanescentes aceitas

[Prontidão](readiness.md) consolida fronteiras nativas, heurística, ausência
de medição de faturamento e escopo suportado. A classificação permanece
heurística; o acerto no corpus não demonstra qualidade de resposta nem
economia real. A CI macOS valida fluxos offline; a interação de conta foi
homologada em Linux. Uma sessão sem resposta nova e SessionStart sem modelo
fica explicitamente sem confirmação, preservando a escolha/ID anterior.
