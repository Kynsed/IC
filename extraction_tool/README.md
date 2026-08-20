Este repositorio contém os arquivos necessários para realização dos testes realizados duranta a Avaliação Experimental do TCC: **Extração e estruturação de informações de páginas HTML usando LLMs**.

### Arquivos:

### updated_app.py:
Arquivo principal responsável por:  
-Geração da Interface Web para extração de informação de páginas HTML.  
-Navegação web (usando Selenium) até a URL definida na Interface.  
-Limpeza do código-fonte da página Web removendo informações não-relevantes (cabeçalhos, rodapés, etc) (usando BeautifulSoup).  
-Chamada do Modelo da OpenAI (**gpt-4o-mini**) ou do **Google Gemini** para extração das informações (definidas na Interface web) do código-fonte limpo.  
-Apresentação dos resultados em forma de Tabela.  
-Exportação dos Resultados no formato CSV e JSON.  

### style.css, main.js e index.html:
Arquivos auxiliares para formatação da Interface Web.  
A Interface deve ser aberta em um Navegador no seguinte endereço: http://127.0.0.1:5000/

#### index.html 
Responsável pela estrutura da Interface web. Define o conteúdo e a organização hierárquica que será apresentada na página.
#### style.css
Responável pela aparência, design e apresentação da página. Usa a estrutura definida no HTML para tornar a página visualmente atraente.
#### index.html
Adiciona interatividade e lógica funcional à página. Permite que a Interface/página Web responda às ações do usuário e manipule os dados.  

#### Sintaxe de uso:
> python .\updated_app.py

### Modelos disponíveis

| Modelo na interface | Provedor | Observação |
|---|---|---|
| OpenAI GPT-4o Mini | OpenAI | modelo usado nos experimentos do TCC |
| OpenAI GPT-4o Vision | OpenAI | exige o envio de uma imagem |
| Google Gemini 3.6 Flash | Google | versão fixa; preferir esta em experimentos |
| Google Gemini 3.1 Flash Lite | Google | mais rápido (~1,8 s contra ~6,6 s) |
| Google Gemini Flash (`gemini-flash-latest`) | Google | apelido: aponta para outro modelo a cada atualização do Google, **não use em experimentos** |

Os modelos Gemini são multimodais: aceitam texto e, quando uma imagem da página é
enviada, passam a analisá-la — sem variante "vision" separada.

O suporte a modelos locais via **Ollama foi removido**, junto com o campo "URL da
API do LLM". As opções que existiam (llama3.1, gemma3n:e4b, gemma3:12b,
gemma3:latest, qwen2.5vl:7b) estavam uma geração atrás e traziam inconsistências:
o código referenciava um `llama3.2-vision:11b` que nunca esteve no seletor, e o
`gemma3:latest` era anunciado como "com suporte a imagens" enquanto a checagem
correspondente estava comentada no código.

### Chaves de API

**Gemini** — informada no campo **Chave da API do Gemini**, que aparece na
interface quando um modelo Gemini é selecionado. Não há chave padrão nem leitura
de variável de ambiente: campo em branco significa nenhuma chave, e a chamada
falha com mensagem explícita. A chave é enviada no corpo da requisição (POST),
nunca na query string, e não é gravada em disco nem registrada em log.

Em uso programático (fora da interface), passe a chave explicitamente:

```python
dados = extract_fields_with_llm(texto, campos, 'gemini-3.6-flash', api_key='SUA_CHAVE')
```

**OpenAI** — lida da variável de ambiente `OPENAI_API_KEY`, que pode vir de um
arquivo `.env` ao lado do `updated_app.py` (ele **não deve ser versionado**):

```
OPENAI_API_KEY=sua-chave-aqui
```

O carregamento é feito pela função `carregar_env()`, sem dependência de
`python-dotenv`. Variáveis já definidas no ambiente do sistema têm precedência
sobre o `.env`. Apenas os *nomes* das variáveis carregadas vão para o log, nunca
os valores.

O botão **Testar Conexão com LLM** valida a chave antes de iniciar uma extração.

### Detalhes da integração com o Gemini

A chamada usa a API REST através da biblioteca `requests`, que já é dependência do
projeto: **não é necessário instalar `google-genai` nem `google-generativeai`**.

Dois parâmetros diferem da chamada à OpenAI, por necessidade e não por escolha:

- `maxOutputTokens = 8192` (contra 2.000 na OpenAI). Os modelos Gemini 3.x
  raciocinam antes de responder, e os tokens de raciocínio saem do **mesmo**
  orçamento da resposta. Nesta tarefa de extração o modelo gasta de 1.000 a 1.900
  tokens pensando: com o limite de 2.000, a resposta é cortada
  (`finishReason=MAX_TOKENS`), o JSON chega truncado e **toda extração falha** como
  "Erro na extração". Manter o mesmo número dos dois lados daria orçamentos
  efetivos muito diferentes.
- `thinkingLevel = "low"`, que reduz o tempo de resposta pela metade (11,2 s → 6,3 s
  na página de teste) sem perda de qualidade — extração é cópia estruturada, não
  inferência.

O prompt, a temperatura (`0`) e a ausência de formato de resposta forçado são
idênticos aos da OpenAI, de modo que a comparação de fidelidade entre os modelos
permaneça justa.

### Estrutura de pastas

O Flask espera os arquivos da interface em `templates/` e `static/`:

```
updated_app.py
templates/index.html
static/css/style.css
static/js/main.js
```

#### TCC_Metricas_Avaliacao_Resumo.ipynb
Responsável pelos cálculos das Metricas ROUGE-1 e BERTScore-F1 para os Resumos gerados pelo modelo  (**gpt-4o-mini**)


#### URLs_Datasets_TCC.txt
Contém todas as URLs utilizadas, de todos os 4 Datasets, para extração dos dados e informações adicionais como data da busca (i.e extração) e como foram realizadas as buscas dos itens nos sites.
