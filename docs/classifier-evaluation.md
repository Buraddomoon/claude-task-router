# Avaliação do classificador — #17 e #18

Protocolo e corpus foram congelados no commit `c2e17d8` antes de alterar as
regras. Os rótulos foram escritos para tipos de trabalho e não gerados pelas
saídas do classificador. [Rubrica e limites de aceite](../evaluation/rubric.md),
[56 casos com justificativas](../evaluation/corpus.json).

O baseline usou somente os 28 casos de desenvolvimento. A calibração usou essa
mesma divisão; as regras foram congeladas em `e28cecc` antes de executar os
28 casos de avaliação. Não houve ajuste posterior com base nessa avaliação.

| Medida | Baseline, desenvolvimento | Calibrado, desenvolvimento | Avaliação reservada |
| --- | --- | --- | --- |
| Política | local-rules-v1 | local-rules-v2 | local-rules-v2 |
| Acertos exatos | 17/28 (60,71%) | 28/28 | 28/28 |
| Subdimensionados | 4/28 | 0/28 | 0/28 |
| Superdimensionados | 7/28 | 0/28 | 0/28 |
| advanced → economy | 1 | 0 | 0 |
| p95 local típico | 0,0158 ms | 0,0263 ms | 0,0262 ms |
| p95 na entrada máxima de 256 KiB | 9,2250 ms | 18,0365 ms | 18,6683 ms |

Medição Linux/Python 3.14.3 em 13/11/2026. A entrada máxima é validada inteira,
mas as regras examinam no máximo 65.536 caracteres. Todas as portas de aceite
predefinidas passaram. Relatórios completos: [baseline](../evaluation/baseline-development.json),
[desenvolvimento calibrado](../evaluation/calibrated-development.json) e
[avaliação](../evaluation/results.json), incluindo hash, matriz de confusão e
resultados por categoria. O conjunto reservado contém 11 economy, 9 balanced
e 8 advanced. O corpus é pequeno e sintético: não demonstra acurácia em uso
real, qualidade de respostas ou economia de faturamento. Não houve avaliação
cega por pessoas externas, nem chamadas de IA para produzir os resultados.

## O que mudou e o que continua limitado

Operações mecânicas só recebem economy quando as cláusulas reconhecidas
continuam simples. “Renomeie a variável e corrija o algoritmo de consenso”
agora recebe advanced; correção funcional adicional recebe pelo menos balanced.
Consenso, eleição de líder e tolerância a falhas são sinais de raciocínio
complexo. Identificadores/caminhos e citações delimitadas não são tratados
como ações; exclusões comuns de trabalho são removidas por regras locais.

Essas regras não são um parser de linguagem natural. Verbos desconhecidos,
negações indiretas, citações aninhadas ou sem fechamento, ironia, contexto
omitido em arquivos e outros idiomas podem levar a uma decisão inadequada.
Uma operação aparentemente mecânica pode ter risco real que o texto não
explica. Examine `reasons`, use override ou configure `min_tier: balanced`
quando economia automática não for apropriada. Nenhuma regra consulta arquivos
referenciados ou altera o modelo de tarefas já existentes.

## Reproduzir

```bash
python3 evaluation/run.py --split development
python3 evaluation/run.py --split evaluation
python3 -m unittest discover -s tests -v
python3 benchmarks/run.py
```

A avaliação retorna código não zero se um limite falhar. A CI executa a
avaliação em Linux/macOS e publica o relatório junto do wheel. Depois de
publicado, esse conjunto passa a ser uma regressão fixa; futuras calibrações
que consultem seus erros precisam de outro conjunto reservado para alegar
nova avaliação independente. Classificação continua local e sem instruções
extras no contexto; a retomada não consulta classificador ou configuração nova.
