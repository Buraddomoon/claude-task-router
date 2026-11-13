# Rubrica e protocolo — #17

Congelados antes da calibração de #18. Corpus sintético escrito a partir dos
tipos de trabalho do produto, com justificativas explícitas por tarefa;
os rótulos não vêm da saída do classificador. Não é amostra de uso real,
nem anotação cega por avaliadores externos independentes.

- `economy`: somente operações mecânicas delimitadas, como ortografia,
  renomeação local, formatação, tradução curta e explicação de um comando.
  Duas dessas operações continuam simples se não houver mudança funcional.
- `balanced`: programação usual delimitada, correção funcional ou ambiguidade.
  Uma referência a requisitos cujo conteúdo não foi fornecido não basta
  para reduzir a escolha a economy.
- `advanced`: controle de acesso, pagamentos, migração de dados, corretude
  distribuída, concorrência e investigação de falhas não determinísticas.
  Ações compostas recebem o maior tier necessário entre as ações solicitadas.
- Citações, identificadores e caminhos são objetos de trabalho. Sua presença
  isolada não equivale a solicitar implementação sensível. Exclusões explícitas
  de trabalho não elevam o tier; uma ação positiva restante ainda conta.

São 56 tarefas PT/EN, 28 de desenvolvimento e 28 de avaliação, com os grupos
simple/common/complex/composed/negative/reference/quoted. Cada grupo tem
duas tarefas por idioma em cada divisão. A redação e os rótulos são versionados;
nenhum caso deriva de prompts privados do usuário ou da conta.

## Separação e aceite predefinido

Use somente `python3 evaluation/run.py --split development` para calibrar.
Execute `--split evaluation` depois de congelar as regras. Não ajuste as regras
usando erros de avaliação; registre-os como limites ou crie uma nova versão do
protocolo e um novo conjunto reservado. O hash SHA-256 identifica o corpus de
cada relatório; o commit identifica as regras. O baseline registra somente a
divisão de desenvolvimento, antes de alterar regras.

Critérios na divisão de avaliação, definidos antes da calibração:

| Métrica | Limite |
| --- | --- |
| Acurácia de tier exato | ≥ 85% |
| Subdimensionamento (tier menor / todas as tarefas) | ≤ 10% |
| Superdimensionamento (tier maior / todas as tarefas) | ≤ 15% |
| advanced rotulado como economy | 0 casos |
| Latência local p95 em tarefas do corpus | ≤ 2 ms |
| Latência local p95 em entrada máxima de 256 KiB | ≤ 150 ms |

O relatório mostra contagens, matriz de confusão, métricas por categoria,
erros com justificativas, plataforma/Python, tempos e critérios aprovados.
Limites de latência são folgados para máquinas comuns e variam por ambiente.
Os testes de configuração continuam verificando floor/override e limite de
varredura; são requisitos separados da acurácia do corpus padrão.

Critérios estruturais: runtime somente com biblioteca padrão; nenhuma chamada
de IA para classificar; zero instruções de roteamento inseridas no contexto;
retomada usa escolha salva, sem nova classificação. A suíte de regressão
verifica esses contratos e a integração com o cliente simulado.

Acerto de tier contra esta rubrica não prova qualidade das respostas, economia
de tokens, custo da conta ou superioridade de modelos. Isso exigiria outro
estudo com execuções reais, critérios de qualidade e medição de faturamento.
