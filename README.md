# IC — extração e verificação factual com LLM

Pesquisa de Iniciação Científica — ICMC/USP

Kelvin Ribeiro Silva · Orientador: Prof. Dr. Alneu de Andrade Lopes

O projeto separa a extração neural de candidatos da verificação simbólica contra a fonte preservada. A conformidade com um contrato JSON e a presença de palavras na página são verificações intermediárias: o julgamento também considera entidade, atributo e contexto.

| Componente | Papel |
| --- | --- |
| [extraction_tool](extraction_tool/README.md) | Aquisição de HTML/imagem, chamada ao Gemini, validação do contrato e preservação dos artefatos da execução. |
| [ic_contract.py](ic_contract.py) | Contrato compartilhado, com tipos, campos obrigatórios e estrutura aninhada. |
| [analisys_tool](analisys_tool/README.md) | Verificação determinística, evidências, sugestões de reparo e reverificação. |
| [Benchmark](analisys_tool/benchmark/README.md) | Corpus sintético com gabarito manual e avaliações separadas de extração, detector e reparo. |

## Executar

Em um terminal, na pasta do extrator:

```powershell
cd extraction_tool
python updated_app.py
```

A interface fica em http://127.0.0.1:5000/. O extrator requer as dependências e credenciais descritas no seu README. Mesmo a opção de página de exemplo chama o Gemini; somente os testes usam respostas simuladas.

Em outro terminal, na pasta do verificador:

```powershell
cd analisys_tool
python verificar.py lote --dir ../extraction_tool/results
```

O novo fluxo usa o JSON e o HTML originais relacionados pelo manifesto. O verificador confere hashes e contrato antes da análise. Imagens são preservadas, mas sua verificação factual direta não está implementada. Arquivos antigos sem manifesto continuam utilizáveis, identificados como legados no relatório.

## Validar localmente

A partir da raiz, com as dependências do extrator e Flask instaladas:

```powershell
python -B -m unittest discover -s extraction_tool/testes -v
node extraction_tool/testes/test_interface.js
node extraction_tool/testes/test_gemini_thinking.js
cd analisys_tool
python -B -m unittest discover -s testes -t .
python -B avaliar_benchmark.py --json benchmark/resultado_v1.json --texto benchmark/resultado_v1.txt
```

Os testes não chamam provedores externos. O núcleo do verificador usa a biblioteca padrão; os testes web requerem Flask e são ignorados explicitamente quando ele não está disponível. Os testes JavaScript requerem Node.js.

O benchmark é sintético e foi usado durante o desenvolvimento. Seus resultados não estimam generalização, desempenho no CIL ou qualidade de um modelo de LLM. Veja os resultados e os limites no [registro das correções P0](CORRECOES_P0.md).
