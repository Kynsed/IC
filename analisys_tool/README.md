# Verificação factual de extrações

Este componente recebe candidatos do [extrator](../extraction_tool/README.md), compara-os com HTML ou texto preservado e emite decisões rastreáveis. A análise não faz chamadas a LLMs. O parser estrutural usa `html.parser` da biblioteca padrão.

O núcleo exige Python 3.10+; a interface web opcional exige Flask (`pip install -r requirements.txt`). Mantenha `../ic_contract.py` junto aos dois módulos: ele é o contrato compartilhado.

## Linha de comando

Na pasta `analisys_tool`:

```powershell
python verificar.py verificar --extracao ../extraction_tool/results/ID_data.json --fonte ../extraction_tool/results/ID.html
python verificar.py lote --dir ../extraction_tool/results
python verificar.py servidor --porta 5001
```

Substitua `ID` pelo UUID real. Para os exemplos legados incluídos:

```powershell
python verificar.py verificar --extracao exemplos/memorias_postumas_data.json --fonte exemplos/memorias_postumas_text.txt
```

| Opção de `verificar` | Efeito |
| --- | --- |
| `--schema contrato.json` | Valida tipos, campos e estrutura; deve coincidir com o manifesto, quando presente. |
| `--gabarito anotacoes.json` | Avalia o detector entre afirmações presentes e anotadas. |
| `--aplicar-reparos` | Gera cópia dos dados, audita tentativas e revalida cada alteração. |
| `--sem-reparo` | Não calcula sugestões; incompatível com aplicar reparos. |
| `--saida pasta` | Diretório dos relatórios. |
| `--formato json,csv,html` | Formatos dos relatórios; o JSON contém contrato e proveniência. |
| `--config config.json` | Parâmetros explícitos, incluindo `data_referencia` ISO para regras de ano. |
| `--tipo-fonte html` ou `texto` | Força o parser. |
| `--falhar-se-alucinacao` | Retorna 1 se a verificação inicial tiver afirmações reprovadas. |

Entradas inválidas retornam código 2 com mensagem. A interface em http://127.0.0.1:5001/ aceita JSON colado, arquivo JSON/CSV, fonte e schema opcional. JSON inválido é erro 400; não é reinterpretado como CSV. A conferência do conjunto completo de artefatos do manifesto está disponível na biblioteca/CLI; uploads web avulsos ficam registrados como dados em memória.

## Contrato e proveniência

O schema exige array de objetos, propriedades explícitas e `additionalProperties: false`. Aceita objetos/listas aninhados, tipos escalares, união de tipos, obrigatoriedade, enum/const, limites numéricos/de tamanho e pattern. Keywords fora do subconjunto implementado são rejeitadas; não há coerção de JSON, preenchimento automático ou recuperação de fragmentos internos de uma resposta inválida.

As extensões `x-entity-key: true` e `x-source-labels: ["rótulo"]` identificam campos de identidade e rótulos explícitos da fonte. Na ausência de identidade declarada, existe um léxico limitado de nomes como nome, título e identificador. O schema gerado pelo extrator a partir de nomes permite escalares e null; use schema explícito quando o tipo esperado for conhecido.

Quando existe `ID_manifest.json` ao lado de `ID_data.json`, o carregador confere versão, UUID, status concluído, schema e hashes de fonte, entrada processada, prompt, resposta bruta e candidatos. O par deve ser exatamente o JSON e o HTML relacionados. Conteúdo alterado, arquivo ausente ou par trocado interrompe a análise. O hash verifica integridade em relação ao manifesto local; não autentica a origem remota. O HTML é o snapshot DOM adquirido pelo extrator, não uma nova visita ao site.

Arquivos sem manifesto recebem `legado_sem_manifesto`; eles não adquirem retrospectivamente histórico de modelo ou resposta bruta. Sem schema, objetos únicos e wrappers legados reconhecidos são adaptados para listas. Com schema, a forma original deve ser um array válido. CSV sem schema mantém strings e quebras internas; com schema, células não textuais precisam conter JSON do tipo declarado. União com string é ambígua em CSV e exige usar JSON. A transformação CSV é registrada no relatório de arquivo.

## Julgamento contextual

Cada folha mantém valor JSON original, tipo, caminho e escopo. Campos superiores preservam seus nomes; campos aninhados usam JSON Pointer, por exemplo `/pessoas/0/idade`. Objetos que agrupam atributos herdam a identidade do ancestral mais próximo; itens com identidade própria são julgados separadamente.

O fluxo verifica limites de palavras/números, magnitude e moeda, depois o vínculo da evidência com a entidade e o atributo. Todas as ocorrências exatas e numéricas entram na decisão; o relatório pode limitar a apresentação de trechos, registrando a quantidade total. Tabelas usam linhas/cabeçalhos; texto precisa de rótulos suficientes para demonstrar uma associação. Valores repetidos ou identidade ambígua permanecem inconclusivos.

| Decisão | Interpretação |
| --- | --- |
| `SUPORTADA` | Evidência suficiente segundo as regras implementadas. Não equivale a uma prova semântica universal. |
| `PARCIAL` | Similaridade, cobertura ou contexto insuficiente; requer revisão. |
| `NAO_SUPORTADA` | Valor/conteúdo não ancorado pelas regras. |
| `ATRIBUICAO_INCORRETA` | Evidência associada a outra entidade ou outro atributo. |
| `INVALIDA` | Restrição de formato/domínio violada. |
| `ABSTENCAO` | Ausência declarada; não conta como fato recuperado. |
| `ERRO_EXTRACAO` | Marcador legado de falha operacional; registro crítico. |
| `NAO_VERIFICAVEL` | Não foi possível executar uma verificação suficiente, como derivado sem base. |

Similaridade aproximada e conjunto de tokens não demonstram relações nem negação e não recebem suporte pleno. A detecção de negação é conservadora, limitada a padrões locais. Regras de domínio, como plausibilidade de ano e ISBN, permanecem heurísticas explícitas. Os índices numéricos do relatório não são probabilidades calibradas.

`Resumo`/ `Summary` dependem da descrição irmã quando presente. A propagação ocorre depois do contexto: base reprovada impede suporte ao derivado, base parcial limita a decisão e base ausente torna o vínculo não verificável. Paráfrases não recebem automaticamente suporte pleno por compartilhar vocabulário.

## Reparo e reverificação

```powershell
python verificar.py verificar --extracao dados.json --fonte pagina.html --schema contrato.json --aplicar-reparos
```

Candidatos vêm de uma entidade única e de um rótulo compatível; não existe busca global de substitutos. Valores conflitantes não são desempatados pela similaridade com o erro. A orquestração não substitui a identidade por outra pessoa/produto da página. Cada tentativa preserva tipos e caminhos, passa novamente pelo contrato e pela verificação contextual e só é aceita com suporte pleno e sem rebaixar fatos antes suportados.

Sem candidato, pode ser aplicada abstenção quando o contrato permite null. Se o contrato proíbe ausência, o valor permanece reprovado e a tentativa rejeitada fica registrada. No modo legado, strings sem candidato usam “Não disponível” e outros tipos usam null. Remover um erro por abstenção não significa recuperar o fato verdadeiro.

São gerados `*_corrigido.json`, `*_pos_reparo.json` e `*_reparos.json`, além do relatório inicial. A auditoria contém valores antes/depois, candidato, evidência, decisão e motivo da aceitação/rejeição. Arquivos originais não são sobrescritos. Use `reparar_e_reverificar` na biblioteca; `aplicar_reparos` é apenas a transformação de baixo nível e não comprova factualidade.

```python
from neurosimbolico import verificar, reparar_e_reverificar
from pathlib import Path

relatorio = verificar("dados.json", "pagina.html")
corrigidos, posterior, tentativas = reparar_e_reverificar(
    relatorio, Path("pagina.html").read_text(encoding="utf-8-sig"))
```

## Avaliação e testes

```powershell
python -B -m unittest discover -s testes -t .
python -B avaliar_benchmark.py --json benchmark/resultado_v1.json --texto benchmark/resultado_v1.txt
```

As taxas em `metricas.py` descrevem decisões do próprio verificador. A avaliação por `--gabarito` usa true=correto/false=incorreto por índice e campo; rótulos desconhecidos são rejeitados e lacunas de anotação são exibidas. Ela não mede a recuperação de registros omitidos.

O [benchmark independente das decisões do detector](benchmark/README.md) compara candidatos e reparos a fatos esperados manualmente, incluindo FP, FN, omissões, entidades extras e danos do reparo. Alinhamento por identidade explícita permite reordenação, inclusive em coleções aninhadas. O corpus é sintético e serviu ao desenvolvimento: é um conjunto de regressão, não uma avaliação externa. Veja [resultado_v1.txt](benchmark/resultado_v1.txt) e o [registro de mudanças](../CORRECOES_P0.md).

Continuam fora desta entrega: avaliação CIL, chamadas reais comparativas a LLMs, OCR de imagens, inferência semântica geral e generalização comprovada para layouts arbitrários. Fontes inline sem rótulos e algumas negações ficam inconclusivas. A data e os parâmetros devem ser fixados para comparar execuções.
