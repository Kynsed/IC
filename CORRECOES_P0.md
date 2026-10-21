# Registro das correções P0 — 2026-10-05

Continuação da segunda fase autorizada após o diagnóstico. A implementação cobre contrato, proveniência, julgamento contextual, reparo reverificado e avaliação sintética. Não altera o PDF de referência nem o DOCX de fundamentação já existente. Nenhum commit ou publicação foi realizado.

> Em 2026-10-07 o extrator passou a usar somente o Gemini. As menções à OpenAI, à temperatura 0 e aos 22 testes do extrator valem para 2026-10-05; o estado atual está na seção final, [Atualização 2026-10-21](#atualização-2026-10-21--extrator-somente-gemini).

## Resultado verificado

- Verificador: **155 testes aprovados**, incluindo os 77 anteriores e novas regressões.
- Extrator: **22 testes aprovados**, com rede e navegador reais bloqueados nos testes.
- Interface do extrator: teste JavaScript aprovado para zero, false, null, estruturas aninhadas e downloads.
- CLI: teste gera JSON corrigido tipado, auditoria e relatório posterior, preservando o arquivo original; opções de reparo incompatíveis são rejeitadas.
- Integração completa: execução real de `process_task` com provedor simulado gerou artefatos consumidos por `verificar`, com manifesto validado, UUID e tipos preservados.
- Revisão independente identificou três falhas adicionais (derivado sem base, adaptação anterior ao schema e inteiro grande); todas receberam correção e regressão.

Comandos executados a partir da raiz, em Python 3.12.8 com as dependências do extrator e Flask disponíveis:

```powershell
python -B -m unittest discover -s extraction_tool/testes -v
node extraction_tool/testes/test_interface.js
cd analisys_tool
python -B -m unittest discover -s testes -t .
python -B avaliar_benchmark.py --json benchmark/resultado_v1.json --texto benchmark/resultado_v1.txt
```

Os erros de timeout, truncamento e exportação vistos nos logs da suíte do extrator são cenários simulados esperados, com asserções sobre o status de falha e seus artefatos. Não foram usadas chaves ou chamadas reais de provedores.

## Arquivos e motivos

Os identificadores BUG e R abaixo retomam o diagnóstico anterior. Os caminhos da tabela são relativos à raiz deste repositório.

| Arquivo alterado ou criado | Mudança e vínculo com o diagnóstico |
| --- | --- |
| `ic_contract.py` | Contrato compartilhado e parsing completo; valida tipos, obrigatoriedade, extras e nesting; rejeita JSON duplicado/constantes inválidas e keywords não suportadas. P0 contrato; R05; BUG-009/010. |
| `extraction_tool/updated_app.py` | Snapshot, entrada processada, prompt, resposta bruta e manifesto com hashes/UUID/modelo/parâmetros; falhas e truncamentos não viram candidatos; exportação precisa terminar para concluir; visão recebe imagem; uploads distintos; encerramento de driver garantido. P0 proveniência; R03/R05/R08/R11; BUG-009 a 013, 019/020. |
| `extraction_tool/templates/index.html` | Entrada de schema explícito e acesso aos artefatos de auditoria; integração do contrato na interface. R05/R11. |
| `extraction_tool/static/js/main.js` | Estruturas aninhadas exibidas sem perder zero/false; downloads refletem artefatos disponíveis inclusive em falhas. BUG-021; R11. |
| `extraction_tool/testes/test_contrato_auditoria.py` | 22 testes offline para provedores simulados, schemas, snapshots, falhas, visão, uploads e exportação. Regressões dos bugs acima. |
| `extraction_tool/testes/test_interface.js` | Executa o fluxo de renderização/download com DOM mínimo; regressão de BUG-021. |
| `extraction_tool/README.md` | Documenta contrato, configurações reais do código, artefatos, execução, testes e limites da captura/modelos. |
| `analisys_tool/neurosimbolico/contrato.py` | Disponibiliza o módulo compartilhado ao executar o verificador a partir da sua pasta. R05. |
| `analisys_tool/neurosimbolico/proveniencia.py` | Confere manifesto, schema, caminhos, hashes e par fonte/extração; distingue legado, execução validada e imagem não suportada. R08/R11. |
| `analisys_tool/neurosimbolico/afirmacoes.py` | Folhas recursivas preservam tipos, JSON Pointer, rótulo, identidade e escopo; CSV preserva quebras internas e exige conversão declarada; schema valida a forma original antes de adaptações legadas. Derivados mantêm vínculo mesmo com base vazia. P0 contrato/contexto; BUG-007/014. |
| `analisys_tool/neurosimbolico/config.py` | Valida intervalos/tipos dos parâmetros e registra data de referência; rejeita configuração desconhecida. R11, reprodutibilidade. |
| `analisys_tool/neurosimbolico/dom.py` | Corrige fechamento de linhas/células, inclusive HTML com fechamento omitido. BUG-003; R08/R14. |
| `analisys_tool/neurosimbolico/normalizacao.py` | Números completos sem concatenação de magnitudes; reconhecimento da identidade monetária. BUG-001/005. |
| `analisys_tool/neurosimbolico/evidencias.py` | Limites de tokens, todas as ocorrências exatas/numéricas, moeda e indícios locais de negação. BUG-001/004/005/008; R09/R11. |
| `analisys_tool/neurosimbolico/contexto.py` | Vincula identidade a uma entidade única e atributo a rótulo/estrutura; trata dois campos, tabelas, outro atributo da mesma entidade e texto rotulado. Incerteza não vira suporte pleno. Substitui o julgamento principal por maioria de coincidências. BUG-002/004/008/018; R09/R14. |
| `analisys_tool/neurosimbolico/predicados.py` | Similaridade/cobertura não provam fatos; valida moeda; usa data registrada; derivado literal preserva negação e base ausente é não verificável; serializa caminho/valor bruto e total de evidências. BUG-005/007/008; R09/R11. |
| `analisys_tool/neurosimbolico/restricoes.py` | Coesão transporta chunks da entidade textual para limitar os reparos. BUG-006/018. |
| `analisys_tool/neurosimbolico/reparo.py` | Candidatos somente na entidade e atributo demonstrados; remove fallback global e desempate por semelhança; transformação profunda preserva caminhos/tipos e valida schema. BUG-006; R12. |
| `analisys_tool/neurosimbolico/verificador.py` | Integra schema e proveniência; contexto por entidade, com herança de identidade para atributos aninhados; propaga resultado final da base aos derivados; falha operacional torna registro crítico; reverifica reparos e rejeita regressões/troca de identidade. BUG-002/006/007/017; R07/R09/R11/R12. |
| `analisys_tool/neurosimbolico/metricas.py` | Rejeita rótulos de gold desconhecidos e explicita lacunas de anotação; métricas do detector não alegam medir omissões da extração. BUG-016; R15/R18. |
| `analisys_tool/neurosimbolico/cli.py` | Aceita schema; grava cópia corrigida, relatório posterior e auditoria; rejeita entradas/opções inválidas. R05/R11/R12. |
| `analisys_tool/neurosimbolico/servidor.py` | Formato explícito, JSON inválido não vira CSV, schema opcional e parâmetros inválidos retornam 400. BUG-015; R05. |
| `analisys_tool/neurosimbolico/__init__.py` | Exporta `reparar_e_reverificar` como API segura da orquestração. R12. |
| `analisys_tool/testes/test_contrato_integracao.py` | 28 testes de contrato, nesting, dependências, CSV, gold, proveniência/tampering, web, tipos e reverificação/CLI. |
| `analisys_tool/testes/test_regressoes_p0.py` | 19 regressões de contexto, limites lexicais, números, moeda, tabelas, ocorrências repetidas, negação, ambiguidade e data de referência. |
| `analisys_tool/testes/test_verificacao.py` | Atualiza um teste de autor repetido sem rótulo: permanece ancorado ao item correto, porém PARCIAL porque o atributo não está demonstrado. Não houve alteração da fonte para fabricar suporte. |
| `analisys_tool/neurosimbolico/avaliacao.py` | Avaliação independente por fatos tipados e identidade; mede extração, detector e dano/benefício do reparo, incluindo omissões e cobertura de anotação. R15/R18. |
| `analisys_tool/testes/test_avaliacao.py` | 31 testes de contagem, omissões, extras, duplicatas, reordenação, nesting, abstenções, danos e anotação incompleta. |
| `analisys_tool/avaliar_benchmark.py` | Runner offline com saídas JSON/texto e falhas operacionais explícitas. R15/R18. |
| `analisys_tool/benchmark/corpus_v1.json` | 23 casos manuais versionados: cenários factuais, layouts, adversariais e duas rejeições contratuais. Gold não é derivado das decisões do sistema. R09/R14/R15. |
| `analisys_tool/benchmark/README.md` | Protocolo, escopo, alinhamento por identidade e limites metodológicos. |
| `analisys_tool/benchmark/resultado_v1.json` | Execução auditável, dados antes/depois, tentativas, métricas e decisões divergentes. |
| `analisys_tool/benchmark/resultado_v1.txt` | Resumo legível dos mesmos resultados. |
| `analisys_tool/README.md` | Atualiza o uso e remove descrições antigas de maioria/global fallback que já não representam o fluxo. |
| `README.md` | Atualiza integração, dependências dos testes e acesso à avaliação. |
| `CORRECOES_P0.md` | Este registro de arquivos, motivos, validação e limites. |

## Benchmark antes/depois

Corpus SHA-256: `ce49f2116b73bac1563cbeb88560bd8e680bdee0b48829f868773faa3de9ccc2`.

**21 casos factuais concluídos, 2 rejeições contratuais esperadas e nenhum erro operacional.** A comparação abaixo usa os mesmos 21 casos antes e depois. Os casos rejeitados são mostrados separadamente no relatório, sem saída corrigida fictícia.

| Medida por fatos exatos | Antes | Após reparo reverificado |
| --- | ---: | ---: |
| Verdadeiros positivos | 39 | 46 |
| Falsos positivos | 14 | 4 |
| Falsos negativos | 12 | 5 |
| Precisão | 0,735849 | 0,920000 |
| Revocação | 0,764706 | 0,901961 |
| F1 | 0,750000 | 0,910891 |

Foram recuperados 7 fatos corretos e removidos 10 incorretos; nenhum fato correto foi perdido e nenhum incorreto foi introduzido. Remoção e recuperação são medidas separadas: abstenção pode remover um FP sem recuperar o fato ausente.

O detector acertou 52 das 54 decisões anotadas. Detectou 12 dos 14 erros factuais; duas decisões ficaram PARCIAL (associação inline sem rótulos e negação). Não houve falso suporte neste conjunto. Cobertura conclusiva: 51/53 fatos anotados nas três classes factuais (96,23%). Precisão condicional entre erros preditos com anotação factual: 1,0; revocação incluindo os inconclusivos: 0,857143. Acurácia multiclasse: 0,962963. Cobertura acompanha as métricas condicionais para não esconder abstenções/inconclusivos.

## Limites e trabalho científico restante

O gold é independente das decisões do algoritmo, mas os exemplos foram usados no desenvolvimento. Este é um conjunto de regressão pequeno e sintético, **não um conjunto externo de teste**, não é CIL e não contém respostas reais de LLM. Portanto, o aumento de F1 não comprova generalização nem redução de alucinações em produção ou no experimento proposto no PDF.

Continuam necessários para as conclusões científicas: corpus externo com amostragem/anotação revisadas, extrações reais e condições registradas, comparação de configurações/modelos e análise de incerteza. Não foram executadas chamadas pagas ou aquisição Selenium real nesta fase. OCR/verificação de imagens, inferência semântica geral e suporte comprovado a layouts arbitrários permanecem fora da implementação.

O contrato default permite vários tipos escalares; schemas específicos são necessários para restringir tipos por tarefa. Heurísticas de identificação, negação e domínio são limitadas. Score/confiabilidade não são probabilidades calibradas. Dados legados não têm proveniência completa. Uploads avulsos da interface não conferem o pacote de manifesto; para essa garantia local, use CLI/biblioteca com os arquivos originais.

Os artefatos salvos e os hashes permitem revisar uma execução; não garantem que uma nova chamada a um provedor remoto produza a mesma resposta. O pipeline preserva as incertezas em vez de reportar que todo caso está resolvido.

## Atualização 2026-10-21 — extrator somente Gemini

Em 2026-10-07, `updated_app.py`, `templates/index.html` e `static/js/main.js` passaram a usar somente a API Gemini. A OpenAI foi removida; o seletor oferece `gemini-3.8-flash` (padrão), `gemini-3.7-flash` e `gemini-3.6-flash`; o nível de raciocínio virou opção da interface; e a chave pode vir de `GEMINI_API_KEY`. Foram criados `test_gemini_thinking.py` e `test_gemini_thinking.js`. Os testes e a documentação deste registro não acompanharam a mudança: 14 testes de `test_contrato_auditoria.py` e o `test_interface.js` passaram a falhar. Esta atualização os realinha.

**Temperatura.** O P0 fixava temperatura 0 nos dois provedores. Desde 2026-10-07 a requisição não envia `temperature`, e vale o padrão do modelo. Em 2026-10-21 essa escolha foi mantida, por seguir a recomendação do Google para os modelos Gemini 3, e passou a ser registrada no manifesto como `"temperature": "default"`. Manifestos gerados entre 2026-10-07 e 2026-10-21 não têm esse campo, mas as chamadas correspondentes também não enviaram temperatura.

| Arquivo | Mudança |
| --- | --- |
| `extraction_tool/updated_app.py` | Registra `"temperature": "default"` nos parâmetros do manifesto; a requisição não muda. |
| `extraction_tool/testes/test_contrato_auditoria.py` | Usa o modelo Gemini padrão e uma chave fictícia em variável de ambiente, sem ler o `.env` real. Os testes da OpenAI viraram equivalentes Gemini: imagem em `inline_data`, erro de conexão sem expor a chave e bloqueio sem candidato. Novos: parâmetros da requisição (chave no header, sem temperatura), partes de raciocínio fora da resposta bruta, extensão de imagem recusada e identificadores OpenAI recusados. |
| `extraction_tool/testes/test_interface.js` | Seleciona um modelo Gemini e simula `response.ok`, que a interface passou a verificar. |
| `extraction_tool/README.md` | Modelos, nível de raciocínio, credenciais, imagens, parâmetros, artefatos e testes do fluxo atual. |
| `extraction_tool/.env` (não versionado) | Explica `GEMINI_API_KEY` e sua precedência; remove a referência à OpenAI. |
| `README.md` | Inclui o teste JavaScript do nível de raciocínio na validação. |
| `CORRECOES_P0.md` | Aviso no início e esta seção. |

### Resultado verificado

Python 3.12.8 e Node.js 22.20.0, a partir da raiz:

- Extrator: **34 testes aprovados** (23 em `test_contrato_auditoria.py`, 11 em `test_gemini_thinking.py`).
- `test_interface.js` e `test_gemini_thinking.js` aprovados.
- Verificador: **155 testes aprovados**, sem alteração.
- Benchmark: `avaliar_benchmark.py` reproduz byte a byte o `resultado_v1.json` salvo.
- Integração: a checagem de ponta a ponta citada em “Resultado verificado” não faz parte da suíte automatizada. Ela foi refeita manualmente com Gemini simulado: `process_task` gerou artefatos que `verificar` aceitou como `manifesto_validado`, com 3 de 3 afirmações `SUPORTADA` e `thinking_level` e `temperature` registrados.

Nenhuma chamada real ao Gemini foi feita nesta atualização. As três execuções reais de 2026-10-07 em `extraction_tool/results/` falharam com HTTP 503 (alta demanda), então o fluxo somente Gemini ainda não produziu uma extração real.
