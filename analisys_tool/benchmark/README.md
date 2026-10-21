# Benchmark sintético v1

Este diretório contém um corpus autoral de regressão, com fontes, candidatos,
schemas e gabaritos definidos manualmente. Não contém dados CIL nem respostas de
LLMs. As mesmas famílias de casos motivaram as correções do sistema; portanto,
estes resultados não estimam generalização ou eficácia em extrações reais.

## Execução reproduzível

Na pasta `analisys_tool`, execute:

```powershell
python -B avaliar_benchmark.py --json benchmark/resultado_v1.json --texto benchmark/resultado_v1.txt
python -B -m unittest testes.test_avaliacao -v
```

Não há chamadas de rede ou dependências de modelos. O corpus fixa a data de
referência em `2026-10-05`. Cada execução grava a configuração efetiva, o hash
SHA-256 dos bytes do corpus, as decisões, os dados antes e depois e a auditoria
das tentativas de reparo. `resultado_v1.json` e `resultado_v1.txt` são saídas da
execução local; regenere-as após qualquer alteração no verificador.

O script retorna código 1 para falhas operacionais, 0 quando conclui a avaliação.
Divergências com o gold são resultados científicos, não são ocultadas nem
convertidas em exceções. Os dois casos de contrato inválido devem ser rejeitados
antes do detector; essa rejeição esperada é contabilizada separadamente.

## Casos e anotações

| Casos | Finalidade |
| --- | --- |
| 01 | Extração correta |
| 02 | Valor ausente da fonte |
| 03 | Idade atribuída à pessoa errada |
| 04 | Mesmo número em outra entidade e outro atributo |
| 05 | Normalizações declaradas explicitamente no gold |
| 06 | Ausência representada por `null` |
| 07 | Entidades aninhadas com atributos trocados |
| 08–11 | Tabelas, texto e linhas sem rótulo de atributo |
| 12 | Valor repetido em mais de cinco contextos |
| 13–14 | Negação e identidade da moeda |
| 15–16 | Campo e registro omitidos |
| 17, 20 | Reordenação de entidades, inclusive aninhadas |
| 18 | Exemplo explícito de intervenção prejudicial |
| 19 | Registro extra |
| 21–22 | Campo obrigatório ausente e tipo incorreto |
| 23 | Limites de palavras e números: Ana/Mariana, 30/130 |

`gold` define os fatos esperados dentro do escopo declarado de cada caso.
`gold_evidence` fornece citações e offsets em caracteres Unicode da fonte bruta;
o carregador verifica sua correspondência. Ausência não tem citação positiva.
`expected_decisions` declara a classe factual esperada para cada folha do
candidato, identificada por índice e campo. Campos aninhados usam JSON Pointer,
por exemplo `/pessoas/0/idade`. Essas anotações não são geradas a partir das
decisões do sistema.

O caso 05 explicita as representações canônicas aceitáveis. O avaliador não usa
normalização, similaridade, coesão ou predicados do detector para inventar um
gabarito. Mudar o corpus exige revisão de seu significado e nova versão quando
alterar o protocolo. Nunca ajuste o gold somente para eliminar divergências.

## Três avaliações separadas

1. **Extração:** comparação exata de folhas JSON, preservando tipo e identidade
   da entidade. Um valor errado produz FP e FN; omissões produzem FN; fatos extras
   e duplicados produzem FP. `null` e marcadores declarados de abstenção não são
   fatos, mas `0` e `false` são. A política é estrita: `1`, `1.0`, `"1"` e `true`
   são representações distintas. Métricas sem denominador são `null`.
2. **Detector:** matriz de confusão multiclasse e métricas binárias para os erros
   factuais. `PARCIAL`, `NAO_VERIFICAVEL`, `INVALIDA`, `ABSTENCAO` e
   `ERRO_EXTRACAO` ficam explícitos. Decisões inconclusivas não contam como erros
   corretamente detectados. As métricas condicionadas a decisões conclusivas
   acompanham cobertura; o recall sobre todos os erros anotados inclui os
   inconclusivos no denominador. Predições não anotadas e decisões ausentes são
   exibidas. Predições sem gold não são presumidas incorretas. A precisão de
   detecção de erros (`hallucination_detection_precision_on_annotated_facts`)
   usa somente predições de erro com gold em uma das três classes factuais.
   `error_prediction_factual_annotation_coverage` informa qual fração de todas
   as predições de erro possui essa anotação; `prediction_annotation_coverage`
   informa a cobertura de anotação de todas as predições, em qualquer classe.
   Quando nenhuma predição de erro tem gold factual, sua precisão é `null`.
   Essas coberturas de anotação diferem da cobertura de decisões conclusivas.
   A taxa de falso suporte usa somente predições de suporte em fatos
   anotados nas três classes factuais.
3. **Reparo:** o runner usa `reparar_e_reverificar`, que aplica a política real de
   reparo e revalida as decisões. Os dados resultantes são comparados ao mesmo
   gold independente, sem supor que a revalidação garanta correção. São contados
   fatos corretos recuperados/perdidos e erros removidos/introduzidos. Substituir
   um erro por outro conta como remoção e introdução; abster-se pode remover um
   FP sem recuperar o fato verdadeiro.

`entity_keys` declara o alinhamento de entidades: `['nome']` no nível superior,
ou `{'/': ['grupo'], '/pessoas': ['nome']}` para coleções aninhadas. Reordenações
dessas coleções não são erros. Listas sem identidade declarada são sequências
ordenadas. Identidades duplicadas no gold são inválidas.

`micro_extraction` compara os mesmos casos concluídos antes e depois. Sua
quantidade aparece em `paired_cases`. Casos rejeitados ou com falha não recebem
uma saída pós-reparo fictícia: seus fatos continuam em
`all_candidates_extraction_before`, sua situação permanece no relatório e as
anotações factuais sem decisões continuam como `MISSING` no detector. Assim, o
relatório não confunde excluir uma execução com reduzir seus erros.

`proposed_after` nos casos 16 e 18 é uma intervenção sintética fornecida apenas
para exercitar o avaliador. Seus resultados ficam em
`independent_intervention_example`; não entram nas métricas do reparador real.

Para uma avaliação científica externa, ainda é necessário um corpus separado,
com amostragem e anotação revisadas, extrações reais, condições de execução
registradas e análise de incerteza. Este conjunto pequeno não sustenta uma
alegação de redução de alucinações no CIL ou em um provedor de LLM.
