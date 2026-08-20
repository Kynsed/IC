# Verificação neuro-simbólica de extrações por LLM

Componente **simbólico** do pipeline neuro-simbólico descrito na documentação da IC
*"Integração de pipelines neuro-simbólicos na extração e estruturação de dados com LLM"*
(ICMC/USP).

O componente **neural** é o [`extraction_tool`](../extraction_tool): o `gpt-4o-mini`
lê a página e devolve registros estruturados. Esta ferramenta recebe essa saída e
executa a **verificação factual explícita pós-geração**: cada afirmação gerada é
confrontada diretamente com a estrutura e o conteúdo do HTML de origem, produzindo
um veredito rastreável — sem re-treino do modelo, sem acesso a pesos e **sem nova
chamada ao LLM**.

Requisito de projeto: a indexação da página usa apenas `html.parser` da biblioteca
padrão. **Não há BeautifulSoup em nenhum ponto do pipeline de verificação.**

---

## Instalação

O núcleo (biblioteca + CLI) roda **só com a biblioteca padrão do Python 3.9+**.
Flask é necessário apenas para a interface web opcional:

```bash
pip install -r requirements.txt
```

## Uso

### 1. Linha de comando

```bash
python verificar.py verificar --extracao exemplos/memorias_postumas_data.json --fonte exemplos/memorias_postumas_text.txt
```

Opções principais:

| Opção | Efeito |
|---|---|
| `--fonte` | HTML bruto da página **ou** o `{task_id}_text.txt` do extraction_tool |
| `--gabarito` | anotação manual; habilita precisão/revocação/F1 do verificador |
| `--formato` | `json,csv,html` (padrão: os três) |
| `--saida` | diretório de saída (padrão `relatorios/`) |
| `--aplicar-reparos` | grava um JSON corrigido com os valores ancorados na página (ver *Reparo*) |
| `--coesao-minima` | limiar da regra de localidade no DOM (padrão `0.70`) |
| `--tipo-fonte` | força `html` ou `texto` (padrão: detecção automática) |
| `--falhar-se-alucinacao` | encerra com código 1 se houver afirmação reprovada |

### 2. Lote sobre os resultados do extraction_tool

Pareia automaticamente `{task_id}_data.json` com `{task_id}.html` ou `{task_id}_text.txt`
e emite um consolidado (`consolidado.csv` / `.json`) com as métricas de cada extração:

```bash
python verificar.py lote --dir ../extraction_tool/results
```

### 3. Interface web

```bash
python verificar.py servidor --porta 5001
```

Abre em <http://127.0.0.1:5001/> (porta 5001 para conviver com a interface do
extraction_tool, que usa a 5000). Aceita upload ou colagem da extração e da fonte.

### 4. Como biblioteca

```python
from neurosimbolico import verificar, escrever_html

rel = verificar("results/abc_data.json", "results/abc.html")
print(rel.metricas["taxa_alucinacao"])
for r in rel.alucinacoes:
    print(r.afirmacao.campo, r.veredito, r.regra, r.notas)
escrever_html(rel, "relatorio.html")
```

---

## O pipeline

```
saída do LLM (extraction_tool)              fonte (HTML bruto ou texto limpo)
            |                                            |
   decomposição em afirmações atômicas          indexação simbólica (html.parser)
            |                                            |
            +------------------> predicados <------------+
                                     |
                          restrições de registro / conjunto
                                     |
                    veredito + evidência + reparo ancorado
```

| Etapa | Módulo | O que faz |
|---|---|---|
| Normalização | `normalizacao.py` | texto, números (pt-BR/en-US), datas, ISBN/EAN. `fold()` **preserva o comprimento**, para que todo casamento volte ao offset exato do original |
| Indexação | `dom.py` | árvore DOM tolerante a marcação malformada, caminhos CSS, atributos de conteúdo (`content`, `alt`, `datetime`, `href`…) |
| Evidências | `evidencias.py` | busca literal, tolerante a separadores, numérica por equivalência de valor, cobertura lexical e similaridade (`difflib`) |
| Decomposição | `afirmacoes.py` | registro → afirmações atômicas com tipo semântico inferido |
| Predicados | `predicados.py` | cadeia de verificação por tipo, do mais forte ao mais fraco |
| Restrições | `restricoes.py` | coerência entre campos do registro e entre registros |
| Reparo | `reparo.py` | candidatos de correção extraídos da subárvore que ancora o registro |
| Métricas | `metricas.py` | factualidade da extração + avaliação do próprio verificador |
| Relatórios | `relatorio.py` | JSON, CSV e HTML autocontido com a citação destacada |

## Vereditos

| Veredito | Significado |
|---|---|
| `SUPORTADA` | ancorada deterministicamente na fonte |
| `PARCIAL` | suporte incompleto ou aproximado (requer revisão) |
| `NAO_SUPORTADA` | o valor não existe na fonte — alucinação de valor |
| `ATRIBUICAO_INCORRETA` | o valor existe, mas pertence a **outro item** da página |
| `INVALIDA` | viola restrição de tipo/formato (ISBN sem dígito verificador, ano implausível) |
| `ABSTENCAO` | o modelo declarou ausência do dado — **não** conta como alucinação |
| `ERRO_EXTRACAO` | falha da ferramenta, não do conteúdo |

A separação entre `NAO_SUPORTADA` e `ATRIBUICAO_INCORRETA` corresponde às duas
famílias de erro apontadas na documentação: *valores não presentes no código-fonte*
e *associações de informações em posições incorretas no DOM*.

## Catálogo de regras

**Predicados** (nível da afirmação) — `LEX-EXATO`, `LEX-TOLERANTE`, `LEX-APROXIMADO`,
`LEX-JANELA`, `LEX-COBERTURA`, `NUM-LITERAL`, `NUM-ANCORADO`, `NUM-MOEDA`,
`NUM-SEM-ROTULO`, `NUM-AUSENTE`, `ID-ANCORADO`, `SIM-CHECKSUM`, `SIM-ANO-INTERVALO`,
`SIM-NEGATIVO`, `SIM-URL-FORMATO`, `DATA-LITERAL`, `DATA-EQUIVALENTE`,
`TXT-COBERTURA-*`, `DER-VINCULADO`, `DER-CONTEUDO-NOVO`, `DER-BASE-NAO-ANCORADA`,
`DOM-FORA-DA-ANCORA`.

**Restrições** (nível do registro/conjunto) — `R-PRECO-ORDEM`, `R-ANO-VS-DATA`,
`R-QUANTIDADE-POSITIVA`, `R-RESUMO-TAMANHO`, `R-COESAO-DOM`, `R-REGISTRO-INFUNDADO`,
`R-COMPLETUDE`, `R-REGISTROS-DUPLICADOS`, `R-VALOR-CONSTANTE`, `R-ANCORAS-DISTINTAS`.

Três regras merecem nota, por endereçarem falhas que a simples busca textual não pega:

- **`R-COESAO-DOM` / `DOM-FORA-DA-ANCORA`** — a *âncora* de um registro é a subárvore
  **mais específica** que concentra ao menos `coesao_minima` dos seus campos ancorados.
  Um campo sem nenhuma ocorrência dentro dela veio de outro item da página. Valores que
  ocorrem em vários pontos (o autor repetido em todos os livros do catálogo) são
  **re-ancorados** antes do julgamento, o que evita falso positivo.
- **`SIM-CHECKSUM`** — ISBN/EAN inventado pelo modelo em geral não fecha o dígito
  verificador. A regra distingue *ausente e mal formado* (fabricação) de *ausente porém
  bem formado* (ainda não suportado) e de *presente na página* (suportado).
- **`DER-*`** — o campo `Resumo` que o extraction_tool acrescenta é condensação da
  `Descrição`; sua base factual é esse campo, não a página. Verifica-se o vínculo
  (cobertura, números e entidades introduzidas) e, se a `Descrição` não estiver
  ancorada, o resumo herda a alucinação (`DER-BASE-NAO-ANCORADA`).

## Reparo

Para cada afirmação reprovada, o verificador procura candidatos de correção **dentro da
subárvore que ancora o registro**, usando os rótulos da própria página (`Editora:` →
valor seguinte), ocorrências numéricas compatíveis com o tipo do campo e identificadores
com dígito verificador válido. Cada candidato vem com o caminho de onde foi retirado.

Nada é aplicado sem `--aplicar-reparos`, e a substituição é deliberadamente
conservadora: campo sem candidato ancorado vira `"Não disponível"` — nunca mantém o
valor alucinado. Registros marcados por `R-REGISTRO-INFUNDADO` **não recebem sugestão
alguma**: preencher um item que não existe na página com valores de outros itens seria
apenas trocar uma fabricação por outra.

No exemplo incluído, das 10 afirmações reprovadas 4 recebem correção ancorada
(ISBN, editora e preço do item correto, ano correto) e 6 viram abstenção explícita.

## Métricas

Sobre a extração: taxa de ancoragem, de suporte parcial, de alucinação e de abstenção
(global, por campo e por tipo), restrições violadas e um índice de confiabilidade por
registro (média ponderada dos vereditos, penalizada pelas restrições violadas).

Sobre o **verificador**, quando há gabarito: precisão, revocação, F1, acurácia e matriz
de confusão da detecção de alucinações, em dois regimes — `permissivo` (só reprovadas)
e `estrito` (`PARCIAL` também conta como detecção).

Formato do gabarito (`true` = valor extraído correto):

```json
{ "registros": [ { "Título": true, "ISBN": false }, { "Preço Atual": false } ] }
```

---

## Exemplo incluído

`exemplos/` traz uma extração real: a página de *Memórias Póstumas de Brás Cubas*
da Livraria Conservadora, extraída pelo `extraction_tool` com `gemini-3.6-flash`
pedindo autor, número de páginas, preço, descrição e editora (o campo `Resumo` é
acrescentado automaticamente pela ferramenta).

```bash
python verificar.py verificar --extracao exemplos/memorias_postumas_data.json --fonte exemplos/memorias_postumas_text.txt
```

Resultado — 5 registros, 30 afirmações, 10 verificáveis:

| Métrica | Valor |
|---|---|
| Taxa de ancoragem | 90,0% |
| Suporte parcial | 10,0% |
| **Taxa de alucinação** | **0,0%** |
| Taxa de abstenção | 66,7% |
| Restrições violadas | 4 × `R-COMPLETUDE` |

O modelo devolveu o livro (registro 4) e mais 4 itens do carrossel de produtos
relacionados, dos quais só capturou o preço. Nenhum valor foi inventado: autor,
páginas, preço, editora e descrição do livro estão todos ancorados na página, a
descrição por transcrição literal (`TXT-EXATO`). Os 4 registros esvaziados são
sinalizados pela `R-COMPLETUDE` (5 de 6 campos indisponíveis).

O único caso não pleno é o `Resumo`: `PARCIAL` por `DER-VINCULO-PARCIAL`, com 71%
de cobertura sobre a `Descrição` e cinco termos que não vêm dela (*prima, narrada,
ironia, comentada, especial*). É paráfrase legítima, não alucinação — e o veredito
intermediário é exatamente o comportamento pretendido: a verificação é de ancoragem
na fonte, não de equivalência semântica.

### Nota sobre o modo de verificação

Este exemplo roda em **modo texto**, porque é só isso que o `extraction_tool` grava
hoje. As regras estruturais (`R-COESAO-DOM`, `DOM-FORA-DA-ANCORA`) ficam inativas.
Para uma página com vários produtos, é justamente esse conjunto de regras que detecta
campos colhidos do item errado — valores que existem na página, mas pertencem a outro
produto. **Sempre que possível, verifique contra o HTML bruto** (ver *Obtendo o HTML
bruto do extraction_tool*, adiante).

### Obtendo o HTML bruto do extraction_tool

O `extraction_tool` salva apenas o texto já limpo. Para guardar também o HTML de
origem e habilitar as regras estruturais, basta acrescentar duas linhas em
`process_task` (em `updated_app.py`), logo após a chamada a `process_url`:

```python
html_file = os.path.join(RESULTS_FOLDER, f"{task_id}.html")
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_content)   # exige devolver html_content junto de process_url
```

O modo `lote` já procura por `{task_id}.html` e cai no `_text.txt` quando ele não existe.

## Testes

```bash
python -m unittest discover -s testes -t .
```

75 testes, sem dependências externas. Quatro deles rodam sobre a extração real
de `exemplos/`, como regressão de ponta a ponta.

## Limitações conhecidas

- A ancoragem lexical isolada não distingue um título de produto de uma menção do mesmo
  título em "Produtos Relacionados". Quem cobre esse caso são as regras de registro
  (`R-COESAO-DOM`, `R-REGISTRO-INFUNDADO`), e elas exigem um mínimo de campos ancorados
  (`minimo_campos_coesao`, padrão 3).
- Paráfrases legítimas do modelo em campos longos tendem a cair em `PARCIAL`: a
  verificação é de **ancoragem na fonte**, não de equivalência semântica — por
  construção, já que qualquer julgamento semântico reintroduziria um componente neural
  não auditável no laço de verificação.
- No modo texto não há regras estruturais; a dispersão de linhas é registrada, mas
  nunca reprova sozinha uma afirmação.
