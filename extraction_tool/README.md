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

O suporte a modelos locais via **Ollama foi removido**.

O carregamento é feito pela função `carregar_env()`, sem dependência de
`python-dotenv`. Variáveis já definidas no ambiente do sistema têm precedência
sobre o `.env`. Apenas os *nomes* das variáveis carregadas vão para o log, nunca
os valores.

O botão **Testar Conexão com LLM** valida a chave antes de iniciar uma extração.

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
