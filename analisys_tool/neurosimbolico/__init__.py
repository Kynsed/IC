"""
Pipeline neuro-simbólico de verificação factual de extrações por LLM.

Pesquisa de Iniciação Científica -- ICMC/USP
"Integração de pipelines neuro-simbólicos na extração e estruturação de dados com LLM"

O componente **neural** é o `extraction_tool` (gpt-4o-mini sobre o conteúdo da
página). Este pacote implementa o componente **simbólico**: verificação factual
explícita, determinística e rastreável das afirmações geradas, confrontando-as
diretamente com a estrutura e o conteúdo do HTML de origem.

Não há re-treino, acesso a pesos, nem nova chamada ao LLM na verificação --
e a indexação do HTML usa apenas `html.parser` da biblioteca padrão
(sem BeautifulSoup).

Uso programático:

    from neurosimbolico import verificar, escrever_html

    relatorio = verificar("results/abc_data.json", "results/pagina.html")
    print(relatorio.metricas["taxa_alucinacao"])
    escrever_html(relatorio, "relatorio.html")
"""

from .afirmacoes import Afirmacao, Registro, carregar_registros, decompor
from .config import Config, Veredito
from .dom import SourceIndex, parse_html, parse_source, parse_text
from .evidencias import Evidence, EvidenceBase
from .metricas import agregar, avaliar_contra_gabarito
from .predicados import ResultadoAfirmacao, verificar_afirmacao
from .relatorio import (
    escrever_csv,
    escrever_html,
    escrever_json,
    gerar_html,
    resumo_texto,
)
from .reparo import Sugestao, aplicar_reparos, sugerir_correcoes
from .restricoes import ResultadoRestricao, calcular_coesao
from .verificador import Relatorio, RelatorioRegistro, verificar, verificar_dados, reparar_e_reverificar

__version__ = "1.0.0"

__all__ = [
    "Afirmacao", "Registro", "carregar_registros", "decompor",
    "Config", "Veredito",
    "SourceIndex", "parse_html", "parse_text", "parse_source",
    "Evidence", "EvidenceBase",
    "ResultadoAfirmacao", "verificar_afirmacao",
    "ResultadoRestricao", "calcular_coesao",
    "Sugestao", "sugerir_correcoes", "aplicar_reparos",
    "agregar", "avaliar_contra_gabarito",
    "Relatorio", "RelatorioRegistro", "verificar", "verificar_dados", "reparar_e_reverificar",
    "escrever_json", "escrever_csv", "escrever_html", "gerar_html", "resumo_texto",
    "__version__",
]
