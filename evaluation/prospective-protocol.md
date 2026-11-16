# Avaliação prospectiva — #35 / #31

Revisão 1, 16/11/2026. O arquivo `prospective-protocol.json` é a definição
executável. O commit desta revisão antecede a instrumentação e qualquer
ensaio novo. Não altera regras do classificador. O protocolo só se torna uma
coorte executável após seleção e autorização das tarefas e congelamento do
manifesto privado; este documento sozinho não comprova o aceite da #35.

## Amostra e separação

Oito tarefas reais novas: duas correções, duas funcionalidades, duas
refatorações e duas investigações, em pelo menos dois projetos autorizados.
Cada tarefa contém uma solicitação inicial e uma continuação predeterminada.
Uma repetição, dois braços, dois turnos: 32 chamadas planejadas. Baseline
Sonnet fixo; roteado usa a política/configuração congelada, classificação
somente no primeiro turno, decisão e UUID reutilizados na continuação.

O responsável fornece snapshot Git limpo, dois arquivos de prompt UTF-8 e
um comando de aceitação por tarefa. Deve declarar autorização e ausência
de uso dos casos em calibração anterior. O harness rejeita os hashes dos
prompts públicos de calibração; a declaração humana cobre casos privados
e semântica equivalente. IDs públicos são opacos; paths, comandos,
repositórios e textos permanecem no manifesto privado fora deste Git.
Não selecionar oito exercícios artificiais para preencher a amostra.

Cada braço/repetição recebe cópia isolada do mesmo commit do projeto.
O segundo turno continua a sessão do primeiro no mesmo diretório. O teste
funcional roda após cada turno, com limite de tempo, em ambos os braços.
Uma tarefa de investigação deve ter critérios objetivos no seu comando de
aceitação e revisão humana do diagnóstico. Não executar testes fornecidos
por terceiros sem a autorização das tarefas/projetos.

## Congelamento e ambiente

Antes da primeira chamada, gerar um lock sanitizado contendo hashes do
protocolo, manifesto completo, prompts, comandos de aceitação, snapshots dos
projetos, arquivos do roteador e do harness. Guardar o manifesto privado
0600 e o lock; alterações exigem nova coorte. Validar novamente todos os
hashes antes de executar. Não adaptar limiares depois de ver resultados.

Alternar a ordem baseline/roteado por índice de tarefa e repetição. Registrar
ordem, Python, plataforma, versão e SHA-256 do executável nativo antes e
depois de cada chamada; observar modelos efetivos e deriva de alias.
Não desativar atualização ou políticas do provedor. Deriva, origem de
contadores incerta, custo ausente ou resultado incompleto tornam a coorte
inconclusiva; preservar tentativas, tempos e custos conhecidos.

Cache natural compartilhado não pode ser isolado por este harness. Separar
entrada nova, escrita de cache, leitura de cache e saída. Registrar carga
local e duração sem atribuir variações de rede/cache ao roteador. A ordem
alternada mitiga, mas não elimina esse viés. A versão/hashes não garantem
imobilidade do backend. Uma repetição não permite significância estatística,
intervalos confiáveis nem alegação de economia geral.

## Orçamento e interrupção

Teto total estimado US$ 8,00, US$ 0,25 por chamada, effort low, até 12 turnos
nativos por chamada, timeout de 180 s. Autorizar esse teto explicitamente
antes de rodar. Um teto menor exige nova revisão congelada, sem consumo
prévio; não iniciar ensaio incompleto intencionalmente para declarar sucesso.
Não há retries automáticos. Qualquer repetição manual é nova tentativa,
preserva o relatório anterior e consome orçamento adicional autorizado.

O limite nativo pode ser excedido pelo turno corrente e pode considerar
custos cumulativos em resume. Reservar headroom por chamada, registrar
excesso e parar quando não houver margem, houver custo desconhecido,
falha de execução, timeout, interrupção ou deriva de versão. Custo ausente
fica `null`, nunca zero. Tentativas iniciadas são salvas antes do spawn.

## Rubrica e decisão

Por turno: sucesso do cliente, identidade de sessão/modelo confirmada,
aceitação funcional com código zero. Revisão humana cega dos artefatos
locais: `pass`, `fail` ou `pending`, e regressão crítica `true`, `false` ou
`null`. Pass exige atender à solicitação, preservar comportamento necessário
e não introduzir defeitos críticos. Exemplo: teste passa mas uma correção
remove validação necessária → `fail` e regressão crítica. Teste passa sem
revisão → `pending`, resultado inconclusivo. Falha funcional → reprovação.
Não confundir a avaliação automatizada deste agente com revisão humana.

Zero perdas funcionais e zero regressões críticas em todos os pares são
pré-requisitos. Comparar custo CLI, tempo de parede e tokens separadamente,
somando também falhas e tentativas parciais. Exibir subtotais de new/resume,
custo/uso marginal e cumulativo e overhead local de classificação/launcher.
Para provar melhoria observada na amostra, a métrica deve cair estritamente
e a coorte inteira ser comparável e aprovada na rubrica. Para economia nas
três métricas, todas devem cair. Uma métrica pior marca essa meta como
não atingida; dados incompletos ou revisão pendente → inconclusivo.

Estimativa CLI não é fatura API nem quota de assinatura. Sem evidência
independente dessas fontes, ambas permanecem não verificadas (`null`).
Não consultar endpoints privados nem persistir credenciais. Nunca inferir
redução de tokens do preço do modelo. Limites se aplicam mesmo a resultados
positivos. A #31 fica aberta enquanto os aceites não forem demonstrados.

## Depois da avaliação

Publicar somente IDs, hashes e metadados permitidos. Artefatos e prompts
ficam localmente para revisão. Investigar desperdícios da v4 separadamente,
sem tratar reanálise de casos conhecidos como nova amostra. Qualquer ajuste
da política após observar esta amostra a transforma em desenvolvimento;
congelar outro conjunto reservado antes de nova alegação independente.

## Verificação simples autorizada em 16/11/2026

O usuário autorizou somente testes simples com baixo gasto. Antes da chamada,
define-se smoke técnico separado: uma tarefa pública trivial, dois turnos
new/resume, no braço roteado, sem ferramentas, um turno nativo por chamada,
timeout de 90 s, teto por chamada US$ 0,025 e agregado US$ 0,05 estimados.
Verificar UUID persistido, uma classificação no new e zero no resume,
proveniência estável e subtração de contadores cumulativos. Os prompts
pedem uma resposta fixa curta, conferida por igualdade. Não ajustar regras
com base nesse smoke. Essa autorização não abrange a coorte de US$ 8,00
acima. O smoke não é ensaio de economia nem substitui tarefas/revisão humana.
