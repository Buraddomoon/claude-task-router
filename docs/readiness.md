# Critérios de prontidão

O escopo V1.0 é um launcher local para Claude Code em Linux/macOS: início
explícito da tarefa, decisão local, continuidade da sessão e controle manual.
A V0.1 registrou o fluxo básico; a V1.0 acrescenta estabilidade por execução,
recuperação, avaliação versionada, homologação interativa e atualização segura.

| Requisito | Entrega e evidência |
| --- | --- |
| Selecionar modelo por mecanismo real | Argumentos CLI e hooks, [arquitetura](architecture.md), `ctr doctor`, smokes reais |
| Classificar localmente com critérios explícitos | #17/#18, [corpus, avaliação e limites](classifier-evaluation.md); zero inferência para classificação |
| Escolher somente no início | #13/#14; regressões de retomada sem classificador/configuração atual |
| Preservar escolha durante continuações | #12; escolha, ID compatível e observação separados; nova confirmação por execução |
| Permitir alteração manual | #20; [/model em PTY real](interactive-qa.md), override em new/resume/model e testes offline |
| Manter runtime leve e contexto sem instruções extras | Biblioteca padrão, benchmark local, hooks silenciosos e regressões |
| Instalar, atualizar e recuperar | #15/#21; [gerações, rollback e testes do artefato](installation.md), migrações transacionais |
| Conferir o escopo inteiro antes da versão final | #22; [matriz requisito → código → teste → evidência](final-audit.md) |

A entrega #12 cobre #13/#14/#15. A entrega #16 cobre #17/#18. A entrega #19
cobre #20/#21/#22. Os vínculos são subissues nativas do GitHub, com evidências
versionadas no repositório. Pais são encerrados somente após as partes
estarem em main e verificadas.

## Portas de lançamento

A conferência final exige a suíte completa, os benchmarks, a avaliação com
limites predefinidos, o wheel instalado fora do checkout e a matriz de CI
Linux/Python 3.11 e 3.14 e macOS Intel/Python 3.14 no commit final.
A release/tag `v1.0.0` é criada somente após esses checks; sua descrição
identifica o commit e a execução de CI aprovados e inclui wheel com checksum.
O número 1.0.0 nos arquivos de preparação não substitui essas portas.

## Limites de aceite

- O launcher preserva a escolha e pede confirmação ao controle nativo que
  cobre fallbacks de conteúdo; não controla todas as políticas do provedor.
  Cadeias por turno podem não produzir hook. `effective_model` é evidência
  observada, não garantia sobre todas as respostas.
- Sem hooks, o modelo efetivo pode ficar desconhecido. Isso é mostrado em
  stderr/metadados; escolhas e IDs fixados anteriores continuam preservados.
- O corpus pequeno e sintético avalia tiers contra uma rubrica explícita.
  Não comprova qualidade de resposta, economia real ou anotação externa cega.
  Linguagem indireta, contexto omitido e regras desconhecidas podem falhar;
  há override e `min_tier`.
- `recover` cria sessão nova e exige contexto fornecido pelo usuário; não
  recupera histórico excluído. O banco do roteador não guarda conversas.
- O `/model` nativo pode salvar o padrão global do Claude. Na versão testada,
  o picker com tecla `s` permite mudar apenas a sessão; o launcher sempre
  passa a escolha explícita da tarefa.
- Runtime Linux/macOS, Python 3.11+, Claude Code 2.1.251+; homologação nativa
  executada em Linux/Claude 2.1.323. macOS é coberto pela CI offline, sem
  alegar homologação interativa de uma conta macOS.
- IDE, backend Codex, Windows, dashboard e proxy permanecem fora do escopo.

Os limites acima são fronteiras documentadas do produto. Falhas que violem
esse contrato devem gerar uma nova issue antes de afirmar nova prontidão.
