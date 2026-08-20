from flask import Flask, request, jsonify, render_template, send_file
import os
import re
import json
import time
import uuid
import threading
import logging
import base64
from werkzeug.utils import secure_filename
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def carregar_env(caminho=None):
    """
    Carrega pares CHAVE=VALOR de um arquivo .env para as variáveis de ambiente.

    Mantém as chaves de API fora do código-fonte sem exigir a instalação do
    python-dotenv. Variáveis já definidas no ambiente têm precedência: o .env
    é um padrão, não uma imposição.

    Args:
        caminho (str): Caminho do arquivo .env (padrão: ao lado deste script)

    Returns:
        list: Nomes das variáveis carregadas (nunca os valores)
    """
    if caminho is None:
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(caminho):
        return []

    carregadas = []
    try:
        with open(caminho, 'r', encoding='utf-8-sig') as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha or linha.startswith('#') or '=' not in linha:
                    continue
                nome, _, valor = linha.partition('=')
                nome, valor = nome.strip(), valor.strip().strip('"').strip("'")
                if nome and valor and nome not in os.environ:
                    os.environ[nome] = valor
                    carregadas.append(nome)
    except Exception as e:
        logger.warning(f"Não foi possível ler o arquivo .env: {e}")
        return []

    if carregadas:
        # Registrar apenas os nomes: o valor de uma chave nunca vai para o log
        logger.info(f"Variáveis carregadas de .env: {', '.join(carregadas)}")
    return carregadas


carregar_env()

# Inicializar Flask
app = Flask(__name__)

# Configurações
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
RESULTS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Criar diretórios se não existirem
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# Configurar limite de upload
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Dicionário para armazenar tarefas
tasks = {}

def allowed_file(filename):
    """Verifica se o arquivo tem uma extensão permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def scrape_webpage_with_selenium(url, headless=True, wait_time=5):
    """
    Faz o scraping de uma página web usando Selenium para simular um navegador real.
    
    Args:
        url (str): URL da página web a ser extraída
        headless (bool): Se True, executa o navegador em modo headless (sem interface gráfica)
        wait_time (int): Tempo de espera em segundos para carregamento da página
        
    Returns:
        str: Conteúdo HTML da página
    """
    try:
        # Configurar opções do Chrome
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")


        # Forçar idioma preferencial: pt-BR > pt > en-US > en  (Solução para o YouTube)
        ###chrome_options.add_argument("--lang=pt-BR")
        ###prefs = {"intl.accept_languages": "pt-BR,pt,en-US,en"}
        ###chrome_options.add_experimental_option("prefs", prefs)

        
        # Adicionar user-agent para parecer um navegador real
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.7049.84 Safari/537.36")
        
        # Inicializar o driver
        logger.info("Inicializando o Chrome WebDriver...")
        driver = webdriver.Chrome(options=chrome_options)


        # Forçar Accept-Language via DevTools Protocol (CDP) (Solução para o Youtube)
        ###driver.execute_cdp_cmd(
        ###    "Network.setExtraHTTPHeaders",
        ###    {"headers": {"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}}
        ###)

        
        # Acessar a URL
        logger.info(f"Acessando a URL: {url}")
        driver.get(url)
        
        # Aguardar o carregamento da página
        logger.info(f"Aguardando {wait_time} segundos para carregamento completo...")
        time.sleep(wait_time)
        
        # Obter o conteúdo HTML
        html_content = driver.page_source
        
        # Fechar o driver
        driver.quit()
        
        return html_content
    
    except Exception as e:
        logger.error(f"Erro ao acessar a URL com Selenium: {e}")
        return None

def clean_text(html_content):
    """
    Limpa o conteúdo HTML removendo elementos não relevantes como cabeçalho, rodapé, propagandas, etc.
    
    Args:
        html_content (str): Conteúdo HTML da página
        
    Returns:
        str: Texto limpo e processado
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remover elementos não relevantes
    for element in soup.select('script, style, iframe, .ads, .banner, .advertisement, .cookie-notice'):
        if element:
            element.decompose()
    
 
###-----------------------------Parte que nao existia em Summary--------------------------
    # 1. Substituir o conteúdo de <noscript> pelo texto, só se o noscript ainda estiver dentro da árvore
    for noscript in soup.select('noscript'):
        noscript_text = noscript.get_text(separator='\n', strip=True)
        if noscript.parent is not None:
            try:
                noscript.insert_before(noscript_text)
                noscript.decompose()
            except Exception:
                # Se falhar inserir, tenta só remover a tag
                noscript.extract()
        else:
            # Se não tem parent, ignora (não tenta substituir nem nada)
            pass
###-----------------------------------------------------------------------------------------

    # Para outras páginas, extrair texto visível
    # Remover elementos não desejados
    #for element in soup.select('script, style, meta, link, noscript'):
    for element in soup.select('script, style, meta, link'):			     #Removendo "noscript" funciona p/ Magalu
        element.decompose()
    
    # Extrair texto visível
    cleaned_text = soup.get_text(separator='\n', strip=True)
    
    # Remover linhas em branco extras
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
    
    return cleaned_text.strip()

# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Orçamento de saída do Gemini.
#
# Os modelos Gemini 3.x são modelos de raciocínio: os tokens de "pensamento"
# consomem o MESMO orçamento de maxOutputTokens que a resposta. Medido nesta
# tarefa de extração, o modelo gasta de 1.000 a 1.900 tokens pensando -- com o
# limite de 2.000 usado na chamada da OpenAI, a resposta é cortada
# (finishReason=MAX_TOKENS) e o JSON chega truncado, fazendo toda extração
# falhar como "Erro na extração". Daí o limite bem mais alto aqui: ele não
# torna a chamada mais cara, apenas deixa de estrangulá-la.
GEMINI_MAX_OUTPUT_TOKENS = 8192

# Nível de raciocínio. 'low' reduz o tempo de resposta pela metade
# (11,2s -> 6,3s na página de teste) sem perda de qualidade na extração,
# que é uma tarefa de cópia estruturada e não de inferência.
GEMINI_THINKING_LEVEL = "low"

GEMINI_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
}


def is_gemini_model(model_provider):
    """
    Verifica se o modelo selecionado é do Google Gemini.

    Args:
        model_provider (str): Nome do modelo

    Returns:
        bool: True se for um modelo Gemini
    """
    return str(model_provider or "").lower().startswith("gemini")


def get_gemini_api_key(api_key=None):
    """
    Obtém a chave da API do Gemini.

    A chave precisa ser informada explicitamente a cada requisição: não há
    chave padrão nem leitura de variável de ambiente. Campo em branco na
    interface significa nenhuma chave, e a chamada falha com mensagem clara.

    Args:
        api_key (str): Chave informada na interface

    Returns:
        str: Chave da API, ou None se nenhuma foi informada
    """
    return (api_key or "").strip() or None


def call_gemini_api(prompt, model_provider, api_key=None, image_path=None,
                    temperature=0.0, max_tokens=GEMINI_MAX_OUTPUT_TOKENS):
    """
    Chama a API do Google Gemini via REST.

    Usa apenas a biblioteca `requests`, que já é dependência do projeto: não
    exige a instalação do SDK google-genai nem do google-generativeai. A chave
    vai no cabeçalho x-goog-api-key, e não na URL, para não ser registrada em
    logs de acesso.

    A requisição é mantida equivalente à da OpenAI (mesmo prompt, mesma
    temperatura, sem forçar formato de resposta), de modo que a comparação
    entre os modelos permaneça justa.

    Args:
        prompt (str): Prompt para o modelo
        model_provider (str): Nome do modelo (ex.: gemini-3.6-flash)
        api_key (str): Chave da API (opcional, cai na variável de ambiente)
        image_path (str): Caminho da imagem a ser analisada (opcional)
        temperature (float): Temperatura de amostragem
        max_tokens (int): Limite de tokens de saída

    Returns:
        str: Resposta do modelo, ou mensagem iniciada por "Erro" em caso de falha
    """
    chave = get_gemini_api_key(api_key)
    if not chave:
        return ("Erro na API do Gemini: chave não informada. Preencha o campo "
                "'Chave da API do Gemini' na interface.")

    # Montar as partes da mensagem (texto e, opcionalmente, imagem)
    parts = [{"text": prompt}]
    if image_path:
        try:
            extensao = os.path.splitext(image_path)[1].lower()
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            parts.append({
                "inline_data": {
                    "mime_type": GEMINI_MIME_TYPES.get(extensao, "image/jpeg"),
                    "data": image_data,
                }
            })
        except Exception as e:
            logger.error(f"Erro ao ler a imagem para o Gemini: {e}")
            return f"Erro ao processar imagem: {str(e)}"

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "systemInstruction": {
            "parts": [{"text": "Você é um assistente especializado em extrair "
                               "informações estruturadas de textos e imagens."}]
        },
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingLevel": GEMINI_THINKING_LEVEL},
        },
    }

    try:
        logger.info(f"Chamando a API do Gemini (modelo: {model_provider})")
        response = requests.post(
            GEMINI_API_URL.format(model=model_provider),
            json=payload,
            headers={"x-goog-api-key": chave, "Content-Type": "application/json"},
            timeout=180,
        )

        if response.status_code != 200:
            # Nunca registrar a chave no log
            logger.error(f"Erro na API do Gemini: {response.status_code} - {response.text[:500]}")

            # Repassar a mensagem da própria API, bem mais útil que o código HTTP
            detalhe = ""
            try:
                erro = (response.json() or {}).get("error", {})
                detalhe = erro.get("message") or ""
                if erro.get("status") == "INVALID_ARGUMENT" and "API key" in detalhe:
                    return ("Erro na API do Gemini: chave inválida. Verifique o valor "
                            "informado ou gere outra em aistudio.google.com/apikey")
            except ValueError:
                pass

            if response.status_code in (401, 403):
                return "Erro na API do Gemini: chave sem permissão para este modelo"
            if response.status_code == 404:
                return (f"Erro na API do Gemini: modelo '{model_provider}' não encontrado "
                        "ou indisponível para esta chave")
            if response.status_code == 429:
                return "Erro na API do Gemini: limite de requisições excedido"
            return f"Erro na API do Gemini: {response.status_code} - {detalhe[:200]}"

        resultado = response.json()

        candidatos = resultado.get("candidates") or []
        if not candidatos:
            motivo = (resultado.get("promptFeedback") or {}).get("blockReason", "resposta vazia")
            logger.error(f"Gemini não retornou candidatos: {motivo}")
            return f"Erro na API do Gemini: {motivo}"

        partes = candidatos[0].get("content", {}).get("parts", []) or []
        texto = "".join(p["text"] for p in partes if isinstance(p, dict) and "text" in p)

        if not texto:
            motivo = candidatos[0].get("finishReason", "sem conteúdo textual")
            uso = resultado.get("usageMetadata", {})
            logger.error(f"Resposta do Gemini sem texto: {motivo} "
                         f"(pensamento={uso.get('thoughtsTokenCount', 0)} tokens)")
            if motivo == "MAX_TOKENS":
                return (f"Erro na API do Gemini: resposta truncada em {max_tokens} tokens "
                        f"({uso.get('thoughtsTokenCount', 0)} consumidos no raciocínio). "
                        "Aumente GEMINI_MAX_OUTPUT_TOKENS ou reduza o número de campos.")
            return f"Erro na API do Gemini: {motivo}"

        return texto

    except requests.Timeout:
        logger.error("Tempo esgotado ao chamar a API do Gemini")
        return "Erro na API do Gemini: tempo de resposta esgotado"
    except Exception as e:
        logger.error(f"Erro ao chamar a API do Gemini: {e}")
        return f"Erro na API do Gemini: {str(e)}"


def extract_fields_with_llm(text, fields, model_provider="openai",
                            image_path=None, api_key=None):
    """
    Extrai campos específicos do texto ou imagem usando um modelo LLM.
    Adiciona um campo 'Resumo' automaticamente se 'Descrição' ou similar for solicitado.

    Args:
        text (str): Texto processado da página web ou None se usando imagem
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM ("openai", "openai-vision"
                              ou "gemini-*")
        image_path (str): Caminho para a imagem a ser processada (opcional)
        api_key (str): Chave da API informada na interface (usada pelo Gemini)

    Returns:
        list: Lista de dicionários com os campos extraídos para cada resultado encontrado
    """
    import json
    import re
    
    # Verificar se um campo de descrição foi solicitado
    description_field = None
    fields_lower = [f.lower() for f in fields]
    description_keywords = ['descrição', 'descricao', 'description', 'detalhes', 'details']
    for keyword in description_keywords:
        if keyword in fields_lower:
            # Encontrar o nome original do campo
            original_index = fields_lower.index(keyword)
            description_field = fields[original_index]
            break
    
    # Adicionar campo Resumo se Descrição foi solicitada
    fields_to_extract = list(fields) # Criar cópia para não modificar a original
    add_summary_instruction = False
    if description_field and 'Resumo' not in fields_to_extract:
        fields_to_extract.append('Resumo')
        add_summary_instruction = True
        logger.info("Campo de descrição encontrado. Adicionando campo 'Resumo' à extração.")
    
    # Verificar se estamos usando um modelo de visão com uma imagem.
    # Os modelos Gemini são multimodais: entram no modo visão apenas quando
    # uma imagem é de fato enviada, continuando disponíveis para texto puro.
    is_vision_model = (
        model_provider == "openai-vision"
        or (is_gemini_model(model_provider) and bool(image_path))
    )
    
    # Construir o prompt para o LLM
    prompt_base = f"""
    ###Analise {'esta imagem' if is_vision_model and image_path else 'o texto abaixo'} e extraia TODAS as ocorrências das seguintes informações: 
    Analise {'esta imagem' if is_vision_model and image_path else 'o texto abaixo'} e extraia as 5 PRIMEIRAS ocorrências das seguintes informações:
    {', '.join(fields_to_extract)}
    
    Se houver múltiplos itens ou produtos, extraia as informações para CADA UM DELES.
    
    Responda APENAS com um array JSON válido onde cada elemento é um objeto com as chaves correspondentes aos campos solicitados.
    Exemplo de formato esperado:
    [
      {{
        "{fields_to_extract[0]}": "valor1 para item1",
        "{fields_to_extract[1]}": "valor2 para item1",			##Usado na versao vision_select
        ...
      }},
      {{
        "{fields_to_extract[0]}": "valor1 para item2",
        "{fields_to_extract[1]}": "valor2 para item2",			##Usado na versao vision_select
        ...
      }},
      ...
    ]
    
    Se alguma informação não estiver disponível para um item específico, use "Não disponível" como valor.
    Se não encontrar nenhum item, retorne um array com um único objeto contendo os campos solicitados.
    """
    
    # Adicionar instrução para gerar resumo se necessário
    if add_summary_instruction:
        prompt_base += f"\n\nIMPORTANTE: Retorne TODAS as informações contidas no campo '{description_field}', não trunque ou modifique de forma alguma estas informações."

    if add_summary_instruction:
        prompt_base += f"\n\nIMPORTANTE: Para o campo 'Resumo', gere um resumo conciso do campo '{description_field}' com no máximo 30 palavras."
    
    # Adicionar texto se não for modelo de visão
    if not (is_vision_model and image_path):
        prompt = prompt_base + f"\n\nTexto:\n{text}"
    else:
        prompt = prompt_base
    
    try:
        # Usar OpenAI (GPT-4o Mini ou GPT-4o Vision)
        if model_provider.lower() in ["openai", "openai-vision"]:
            ###import os
            ###from openai import OpenAI
            from openai import Client
            
            # Usar a chave de API da variável de ambiente
            ###client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")
            client = Client(api_key=os.environ.get("OPENAI_API_KEY")
            )
            
            # Preparar as mensagens
            if is_vision_model and image_path:
                # Ler a imagem e codificar em base64
                with open(image_path, "rb") as image_file:
                    image_data = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Criar mensagem com conteúdo de imagem
                messages = [
                    {
                        "role": "system", 
                        "content": "Você é um assistente especializado em extrair informações estruturadas de imagens de páginas web."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ]
                
                # Chamar a API da OpenAI com o modelo GPT-4o Vision
                response = client.chat.completions.create(
                    model="gpt-4o",  # Modelo com capacidade de visão
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
            else:
                # Mensagens para modelo de texto
                messages = [
                    {
                        "role": "system", 
                        "content": "Você é um assistente especializado em extrair informações estruturadas de textos."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ]
                
                # Chamar a API da OpenAI com o modelo GPT-4o Mini
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
            
            # Extrair o conteúdo da resposta
            result = response.choices[0].message.content

        # Usar Google Gemini
        elif is_gemini_model(model_provider):
            result = call_gemini_api(
                prompt=prompt,
                model_provider=model_provider,
                api_key=api_key,
                image_path=image_path if is_vision_model else None,
                temperature=0.0,
            )

        # Modelo não reconhecido
        else:
            return [{field: f"Provedor de modelo não suportado: {model_provider}" for field in fields_to_extract}]
        
        # Falha do provedor: repassar a causa em vez de deixá-la virar um
        # genérico "Erro na extração" no parse. Sem isso, uma chave ausente
        # aparece na tabela como se o modelo tivesse falhado.
        if isinstance(result, str) and result.startswith("Erro"):
            logger.error(result)
            return [{field: result for field in fields_to_extract}]

        # Tentar extrair o JSON da resposta
        try:
            # Procurar por padrões de array JSON na resposta
            json_match = re.search(r'(\[.*\])', result, re.DOTALL)
            if json_match:
                result = json_match.group(1)
            
            # Tentar carregar como JSON
            extracted_data_list = json.loads(result)
            
            # Verificar se o resultado é uma lista
            if not isinstance(extracted_data_list, list):
                logger.warning("O resultado não é uma lista, convertendo para lista com um único item")
                extracted_data_list = [extracted_data_list]
            
            # Verificar se todos os campos solicitados estão presentes em cada item
            for item in extracted_data_list:
                for field in fields_to_extract:
                    if field not in item:
                        item[field] = "Não disponível"
            
            return extracted_data_list
        
        except json.JSONDecodeError:
            logger.error(f"Erro ao decodificar JSON da resposta do LLM: {result}")
            # Criar uma lista com um único dicionário com valores padrão
            return [{field: "Erro na extração" for field in fields_to_extract}]
    
    except Exception as e:
        logger.error(f"Erro ao chamar a API do LLM: {e}")
        return [{field: "Erro na API" for field in fields_to_extract}]

def generate_csv(data, output_file):
    """
    Gera um arquivo CSV com os dados extraídos.
    
    Args:
        data (list): Lista de dicionários com os dados extraídos
        output_file (str): Caminho para o arquivo CSV de saída
        
    Returns:
        bool: True se o CSV foi gerado com sucesso, False caso contrário
    """
    try:
        # Converter para DataFrame
        df = pd.DataFrame(data)
        
        # Salvar como CSV utf-8 para Português
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
        
        return True
    
    except Exception as e:
        logger.error(f"Erro ao gerar CSV: {e}")
        return False

def generate_json(data, output_file):
    """
    Gera um arquivo JSON com os dados extraídos.
    
    Args:
        data (list): Lista de dicionários com os dados extraídos
        output_file (str): Caminho para o arquivo JSON de saída
        
    Returns:
        bool: True se o JSON foi gerado com sucesso, False caso contrário
    """
    try:
        # Salvar como JSON com formatação e codificação UTF-8 para Português
        with open(output_file, 'w', encoding='utf-8-sig') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return True
    
    except Exception as e:
        logger.error(f"Erro ao gerar JSON: {e}")
        return False

def create_mock_html():
    """
    Cria um HTML de exemplo para testes.
    
    Returns:
        str: Conteúdo HTML de exemplo
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Página de Exemplo - Livro</title>
    </head>
    <body>
        <header>
            <nav>Menu de Navegação</nav>
            <div class="ads">Anúncio de Cabeçalho</div>
        </header>
        
        <main>
            <h1>Dom Casmurro</h1>
            
            <div class="product-info">
                <div class="author">
                    <h2>Autor</h2>
                    <p>ASSIS, MACHADO DE</p>
                </div>
                
                <div class="details">
                    <h2>Detalhes do Produto</h2>
                    <ul>
                        <li><strong>Número de Páginas:</strong> 400</li>
                        <li><strong>Editora:</strong> PENGUIN COMPANHIA</li>
                        <li><strong>ISBN:</strong> 9788582850350</li>
                        <li><strong>Ano de Publicação:</strong> 2019</li>
                    </ul>
                </div>
                
                <div class="price">
                    <h2>Preço</h2>
                    <p class="current-price">R$ 69,69</p>
                    <p class="old-price">R$ 79,90</p>
                </div>
            </div>
            
            <div class="description">
                <h2>Descrição</h2>
                <p>
                    Publicado em 1899, Dom Casmurro é um dos romances mais conhecidos de Machado de Assis.
                    A obra narra a história de Bentinho, que, após se tornar advogado, casa-se com Capitu,
                    sua namorada de infância. O ciúme excessivo do protagonista o leva a suspeitar de uma
                    traição entre sua esposa e seu melhor amigo, Escobar.
                </p>
            </div>
        </main>
        
        <aside>
            <div class="ads">Anúncio Lateral</div>
            <div class="related-products">
                <h3>Produtos Relacionados</h3>
                <ul>
                    <li>Memórias Póstumas de Brás Cubas</li>
                    <li>Quincas Borba</li>
                    <li>O Alienista</li>
                </ul>
            </div>
        </aside>
        
        <footer>
            <div class="copyright">© 2025 Livraria Exemplo</div>
            <div class="ads">Anúncio de Rodapé</div>
        </footer>
    </body>
    </html>
    """

def process_url(url, fields, model_provider, use_mock=False,
                image_path=None, api_key=None):
    """
    Processa uma URL ou imagem e extrai campos específicos.

    Args:
        url (str): URL da página web (opcional)
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM
        use_mock (bool): Se True, usa dados de exemplo em vez de acessar a URL
        image_path (str): Caminho para a imagem a ser processada (opcional)
        api_key (str): Chave da API informada na interface (usada pelo Gemini)

    Returns:
        tuple: (dados_extraídos, texto_processado, contagem_resultados)
    """
    # Verificar se temos URL ou imagem
    if not url and not image_path and not use_mock:
        logger.error("Nem URL nem imagem fornecida para processamento")
        return [{"Erro": "URL ou imagem não fornecida"}], "URL ou imagem não fornecida", 0
    
    # Processar URL ou usar dados de exemplo
    if url or use_mock:
        # Obter conteúdo HTML
        if use_mock:
            logger.info("Usando dados de exemplo para teste")
            html_content = create_mock_html()
        else:
            logger.info(f"Acessando URL: {url}")
            html_content = scrape_webpage_with_selenium(url)
            
            if not html_content:
                logger.error("Falha ao obter conteúdo HTML da página")
                return [{"Erro": "Falha ao obter conteúdo HTML da página"}], "Falha ao obter conteúdo HTML da página", 0
        
        # Limpar e processar o texto
        logger.info("Limpando e processando o texto")
        text = clean_text(html_content)
    else:
        # Se estamos usando apenas imagem, não temos texto para processar
        text = None
    
    # Extrair campos com LLM
    logger.info(f"Extraindo campos com modelo LLM: {model_provider}")
    extracted_data = extract_fields_with_llm(text, fields, model_provider,
                                             image_path, api_key)
    
    # Verificar se a extração foi bem-sucedida
    if not extracted_data:
        logger.error("Falha ao extrair dados com o modelo LLM")
        return [{"Erro": "Falha ao extrair dados com o modelo LLM"}], text, 0
    
    # Contar resultados
    result_count = len(extracted_data) if isinstance(extracted_data, list) else 1
    
    return extracted_data, text, result_count

def process_task(task_id, url=None, fields=None, model_provider="openai",
                 use_mock=False, image_path=None, api_key=None):
    """
    Processa uma tarefa de extração de informações.

    Args:
        task_id (str): ID da tarefa
        url (str): URL da página web a ser processada (opcional)
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM
        use_mock (bool): Se True, usa dados de exemplo em vez de acessar a URL
        image_path (str): Caminho para a imagem a ser processada (opcional)
        api_key (str): Chave da API informada na interface (usada pelo Gemini)
    """
    try:
        # Atualizar status da tarefa
        tasks[task_id]['status'] = 'processing'

        # Processar URL ou imagem
        extracted_data, text, result_count = process_url(url, fields, model_provider,
                                                         use_mock, image_path, api_key)
        
        # Salvar texto processado
        text_file = os.path.join(RESULTS_FOLDER, f"{task_id}_text.txt")
        with open(text_file, 'w', encoding='utf-8-sig') as f:
            f.write(text if text else "Processamento baseado em imagem, sem texto disponível.")
        
        # Gerar CSV
        csv_file = os.path.join(RESULTS_FOLDER, f"{task_id}_data.csv")
        generate_csv(extracted_data, csv_file)
        
        # Gerar JSON
        json_file = os.path.join(RESULTS_FOLDER, f"{task_id}_data.json")
        generate_json(extracted_data, json_file)
        
        # Atualizar status da tarefa
        tasks[task_id]['status'] = 'completed'
        tasks[task_id]['extracted_data'] = extracted_data
        tasks[task_id]['text_file'] = text_file
        tasks[task_id]['csv_file'] = csv_file
        tasks[task_id]['json_file'] = json_file
        tasks[task_id]['result_count'] = result_count
        
        logger.info(f"Tarefa {task_id} concluída com sucesso. {result_count} resultados encontrados.")
    
    except Exception as e:
        logger.error(f"Erro ao processar tarefa {task_id}: {e}")
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['message'] = str(e)

@app.route('/')
def index():
    # Usar o HTML atualizado que informa sobre o resumo
    return render_template('index.html') # Assume que index.html será substituído pelo atualizado

@app.route('/api/test-llm', methods=['GET', 'POST'])
def test_llm():
    try:
        # POST é o caminho preferido: permite enviar a chave de API no corpo da
        # requisição em vez da query string. GET é mantido por compatibilidade.
        origem = request.form if request.method == 'POST' else request.args
        model_provider = origem.get('model_provider', "openai")
        api_key = origem.get('api_key', None)

        # Verificar se o modelo é do Google Gemini
        if is_gemini_model(model_provider):
            if not get_gemini_api_key(api_key):
                return jsonify({
                    'status': 'error',
                    'message': 'Chave da API do Gemini não informada. '
                               'Preencha o campo correspondente.'
                }), 500

            # Orçamento folgado mesmo para uma resposta de uma palavra: os
            # tokens de raciocínio saem deste mesmo limite, e um "responda OK"
            # já consome cerca de 120 deles.
            resultado = call_gemini_api(
                prompt="Responda apenas com a palavra OK.",
                model_provider=model_provider,
                api_key=api_key,
                max_tokens=2048,
            )

            if resultado.startswith("Erro"):
                return jsonify({'status': 'error', 'message': resultado}), 500

            return jsonify({
                'status': 'success',
                'message': f'Conexão com o Gemini ({model_provider}) estabelecida com sucesso'
            })

        # Verificar se o modelo é um modelo OpenAI
        if model_provider in ["openai", "openai-vision"]:
            try:
                # Verificar se a chave de API está definida
                ###import os
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    return jsonify({'status': 'error', 'message': 'Chave de API da OpenAI não encontrada. Defina a variável de ambiente OPENAI_API_KEY.'}), 500
                
                # Testar a conexão com a OpenAI
                from openai import Client
                client = Client(api_key=api_key)
                
                # Usar o modelo apropriado
                model = "gpt-4o" if model_provider == "openai-vision" else "gpt-4o-mini"
                
                # Testar a conexão
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Olá, você está funcionando?"}],
                    ###temperature=0.0,
                    max_tokens=10
                )
                
                return jsonify({'status': 'success', 'message': 'Conexão com OpenAI estabelecida com sucesso'})
            
            except Exception as e:
                logger.error(f"Erro ao testar conexão com OpenAI: {e}")
                return jsonify({'status': 'error', 'message': f'Erro ao conectar com OpenAI: {str(e)}'}), 500
        
        else:
            return jsonify({'status': 'error', 'message': f'Provedor de modelo não suportado: {model_provider}'}), 400
    
    except Exception as e:
        logger.error(f"Erro ao testar conexão com LLM: {e}")
        return jsonify({'status': 'error', 'message': f'Erro ao conectar com LLM: {str(e)}'}), 500

@app.route('/api/scrape', methods=['POST'])
def scrape():
    try:
        # Obter parâmetros do formulário
        url = request.form.get('url', '')
        fields_str = request.form.get('fields', '')
        model_provider = request.form.get('model_provider', 'openai')
        use_mock = request.form.get('use_mock', 'false').lower() == 'true'
        # Chave enviada no corpo do formulário (nunca na URL, para não acabar
        # registrada em logs de acesso ou no histórico do navegador)
        api_key = request.form.get('api_key', None)
        
        # Processar campos
        fields = [field.strip() for field in fields_str.split(',') if field.strip()]
        
        if not fields:
            return jsonify({'error': 'Nenhum campo especificado para extração'}), 400
        
        # Verificar se há uma imagem
        image_path = None
        if 'page_image' in request.files:
            file = request.files['page_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(image_path)
                logger.info(f"Imagem salva em: {image_path}")
        
        # Verificar se temos URL ou imagem
        if not url and not image_path and not use_mock:
            return jsonify({'error': 'Nem URL nem imagem fornecidas para processamento'}), 400
        
        # Criar ID da tarefa
        task_id = str(uuid.uuid4())
        
        # Inicializar tarefa (a chave de API não é armazenada aqui: fica apenas
        # no argumento da thread, pelo tempo de vida da requisição)
        tasks[task_id] = {
            'id': task_id,
            'status': 'pending',
            'url': url,
            'image_path': image_path,
            'fields': fields,
            'model_provider': model_provider,
            'use_mock': use_mock,
            'created_at': time.time()
        }

        # Iniciar processamento em thread separada
        thread = threading.Thread(
            target=process_task,
            args=(task_id, url, fields, model_provider, use_mock,
                  image_path, api_key)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'task_id': task_id})
    
    except Exception as e:
        logger.error(f"Erro ao iniciar scraping: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Tarefa não encontrada'}), 404
    
    task = tasks[task_id]
    
    response = {
        'status': task['status'],
        'created_at': task['created_at']
    }
    
    if task['status'] == 'completed':
        response['extracted_data'] = task['extracted_data']
        response['result_count'] = task['result_count']
    
    if task['status'] == 'error' and 'message' in task:
        response['message'] = task['message']
    
    return jsonify(response)

@app.route('/api/download/<task_id>/<file_type>', methods=['GET'])
def download_file(task_id, file_type):
    if task_id not in tasks:
        return jsonify({'error': 'Tarefa não encontrada'}), 404
    
    task = tasks[task_id]
    
    if task['status'] != 'completed':
        return jsonify({'error': 'Tarefa ainda não foi concluída'}), 400
    
    if file_type == 'csv':
        return send_file(task['csv_file'], as_attachment=True, download_name='extracted_data.csv')
    elif file_type == 'json':
        return send_file(task['json_file'], as_attachment=True, download_name='extracted_data.json')
    elif file_type == 'text':
        return send_file(task['text_file'], as_attachment=True, download_name='processed_text.txt')
    else:
        return jsonify({'error': 'Tipo de arquivo inválido'}), 400

if __name__ == '__main__':
    # Criar diretório templates se não existir
    if not os.path.exists('templates'):
        os.makedirs('templates')
    # Criar diretório static se não existir
    if not os.path.exists('static/css'):
        os.makedirs('static/css')
    if not os.path.exists('static/js'):
        os.makedirs('static/js')
        
    # Copiar/Renomear arquivos HTML, CSS, JS para os locais corretos se necessário
    # (Assumindo que os arquivos corretos já estão nos locais esperados ou serão colocados lá)
    # Exemplo: os.rename('/home/ubuntu/updated_index_with_summary_note.html', 'templates/index.html')
    # Exemplo: os.rename('/home/ubuntu/fixed_main.js', 'static/js/main.js')
    # Exemplo: os.rename('/home/ubuntu/updated_style.css', 'static/css/style.css')
    
    # Verificar se o arquivo index.html existe no diretório templates
    if not os.path.exists('templates/index.html'):
        logger.warning("Arquivo templates/index.html não encontrado. A aplicação pode não funcionar corretamente.")
        # Opcional: Copiar o arquivo HTML atualizado para o local correto
        try:
            import shutil
            shutil.copyfile('/home/ubuntu/updated_index_with_summary_note.html', 'templates/index.html')
            logger.info("Arquivo index.html copiado para templates/")
        except Exception as e:
            logger.error(f"Falha ao copiar index.html: {e}")
            
    # Verificar se os arquivos CSS e JS existem
    if not os.path.exists('static/js/main.js'):
         logger.warning("Arquivo static/js/main.js não encontrado.")
         try:
            import shutil
            shutil.copyfile('/home/ubuntu/fixed_main.js', 'static/js/main.js')
            logger.info("Arquivo main.js copiado para static/js/")
         except Exception as e:
            logger.error(f"Falha ao copiar main.js: {e}")
            
    if not os.path.exists('static/css/style.css'):
         logger.warning("Arquivo static/css/style.css não encontrado.")
         try:
            import shutil
            # Assumindo que o style.css correto está em /home/ubuntu/updated_style.css
            shutil.copyfile('/home/ubuntu/updated_style.css', 'static/css/style.css') 
            logger.info("Arquivo style.css copiado para static/css/")
         except Exception as e:
            logger.error(f"Falha ao copiar style.css: {e}")

    app.run(host='0.0.0.0', port=5000, debug=True)
