# IC — Integração de pipelines neuro-simbólicos na extração e estruturação de dados com LLM

Pesquisa de Iniciação Científica — ICMC/USP
Kelvin Ribeiro Silva · Orientador: Prof. Dr. Alneu de Andrade Lopes

Grandes modelos de linguagem extraem dados de páginas HTML com boa proficiência,
mas produzem valores ausentes do código-fonte e associam informações a posições
incorretas do DOM. Este repositório investiga a mitigação dessas alucinações por
**verificação factual explícita pós-geração**, sem re-treino do modelo.

## Os dois componentes

| Diretório | Papel | Descrição |
|---|---|---|
| [`extraction_tool/`](extraction_tool) | **neural** | Interface web que navega até a página, limpa o HTML e extrai campos estruturados via LLM (OpenAI ou Google Gemini). |
| [`analisys_tool/`](analisys_tool) | **simbólico** | Confronta cada afirmação gerada com a estrutura e o conteúdo do HTML de origem, emitindo vereditos rastreáveis. |

O componente simbólico é determinístico: não consulta modelo neural, não usa
aleatoriedade, e indexa o HTML apenas com `html.parser` da biblioteca padrão —
sem BeautifulSoup. Cada veredito carrega a regra que o produziu e a citação exata
da fonte que o sustenta.

## Uso encadeado

```bash
cd extraction_tool && python updated_app.py          # interface em :5000
cd ../analisys_tool && python verificar.py lote --dir ../extraction_tool/results
```

Instruções detalhadas em [extraction_tool/README.md](extraction_tool/README.md) e
[analisys_tool/README.md](analisys_tool/README.md).
