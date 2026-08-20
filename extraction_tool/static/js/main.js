// main.js - Script para o Web Scraper com Integração LLM

document.addEventListener('DOMContentLoaded', function() {
    // Elementos do DOM
    const scraperForm = document.getElementById('scraper-form');
    const urlInput = document.getElementById('url');
    const pageImageInput = document.getElementById('page-image');
    const fieldsInput = document.getElementById('fields');
    const modelProviderSelect = document.getElementById('model-provider');
    const geminiKeyInput = document.getElementById('gemini-api-key');
    const geminiKeyContainer = document.getElementById('gemini-key-container');
    const useMockCheckbox = document.getElementById('use-mock');
    const submitBtn = document.getElementById('submit-btn');
    const testLLMBtn = document.getElementById('test-llm-btn');
    
    const statusContainer = document.getElementById('status-container');
    const statusBadge = document.getElementById('status-badge');
    const progressBar = document.getElementById('progress-bar');
    const statusMessage = document.getElementById('status-message');
    const checkStatusBtn = document.getElementById('check-status-btn');
    
    const resultContainer = document.getElementById('result-container');
    const resultTable = document.getElementById('result-table');
    const resultHeaders = document.getElementById('result-headers');
    const resultBody = document.getElementById('result-body');
    const downloadCSVBtn = document.getElementById('download-csv-btn');
    const downloadJSONBtn = document.getElementById('download-json-btn');
    const downloadTextBtn = document.getElementById('download-text-btn');
    const newExtractionBtn = document.getElementById('new-extraction-btn');
    
    // Variáveis globais
    let currentTaskId = null;
    let pollingInterval = null;
    let extractedData = null;
    
    // Verificar se o modelo selecionado exige uma imagem para funcionar.
    // Os modelos Gemini não entram aqui: são multimodais e aceitam texto puro,
    // passando a analisar a imagem apenas quando uma é enviada.
    function isVisionModel() {
        return modelProviderSelect.value === 'openai-vision';
    }
    
    // Verificar se o modelo selecionado é do Google Gemini
    function isGeminiModel() {
        return modelProviderSelect.value.toLowerCase().startsWith('gemini');
    }

    
    // Mostrar o campo da chave apenas quando um modelo Gemini está selecionado
    function updateProviderFields() {
        if (geminiKeyContainer) {
            geminiKeyContainer.style.display = isGeminiModel() ? 'block' : 'none';
        }
    }
    
    // Validar entradas do formulário
    function validateForm() {
        // Verificar se pelo menos URL ou imagem foi fornecida (a menos que use-mock esteja marcado)
        if (!useMockCheckbox.checked && !urlInput.value && !pageImageInput.files.length) {
            alert('Por favor, forneça uma URL ou uma imagem da página web (ou marque "Usar dados de exemplo").');
            return false;
        }
        
        // Se um modelo de visão for selecionado, verificar se uma imagem foi fornecida
        if (isVisionModel() && !pageImageInput.files.length && !useMockCheckbox.checked) {
            alert('O modelo de visão requer uma imagem. Por favor, carregue uma imagem ou selecione outro modelo.');
            return false;
        }
        
        // Verificar se os campos para extração foram especificados
        if (!fieldsInput.value) {
            alert('Por favor, especifique os campos que deseja extrair.');
            return false;
        }
        
        return true;
    }
    
    // Desabilitar campos do formulário durante o processamento
    function disableFormFields() {
        urlInput.disabled = true;
        pageImageInput.disabled = true;
        fieldsInput.disabled = true;
        modelProviderSelect.disabled = true;
        if (geminiKeyInput) geminiKeyInput.disabled = true;
        useMockCheckbox.disabled = true;
        submitBtn.disabled = true;
        testLLMBtn.disabled = true;
        
        // Adicionar classe visual para indicar que o formulário está em modo somente leitura
        scraperForm.closest('.card').classList.add('form-readonly');
        
        // Atualizar texto do botão
        submitBtn.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Processando...';
    }
    
    // Resetar estado de processamento
    function resetProcessingState() {
        urlInput.disabled = false;
        pageImageInput.disabled = false;
        fieldsInput.disabled = false;
        modelProviderSelect.disabled = false;
        if (geminiKeyInput) geminiKeyInput.disabled = false;
        useMockCheckbox.disabled = false;
        submitBtn.disabled = false;
        testLLMBtn.disabled = false;
        
        // Remover classe visual de somente leitura
        scraperForm.closest('.card').classList.remove('form-readonly');
        
        // Resetar texto do botão
        submitBtn.innerHTML = '<i class="bi bi-search me-2"></i>Iniciar Extração';
    }
    
    // Iniciar extração
    function startExtraction(event) {
        event.preventDefault();
        
        if (!validateForm()) {
            return;
        }
        
        // Preparar dados do formulário
        const formData = new FormData();
        formData.append('fields', fieldsInput.value);
        formData.append('model_provider', modelProviderSelect.value);
        formData.append('use_mock', useMockCheckbox.checked);
        
        // Adicionar URL se fornecida
        if (urlInput.value) {
            formData.append('url', urlInput.value);
        }
        
        // Adicionar imagem se fornecida
        if (pageImageInput.files.length > 0) {
            formData.append('page_image', pageImageInput.files[0]);
        }
        
        // Adicionar a chave do Gemini (vai no corpo do formulário, nunca na URL)
        if (isGeminiModel() && geminiKeyInput && geminiKeyInput.value) {
            formData.append('api_key', geminiKeyInput.value);
        }
        
        // Desabilitar campos do formulário
        disableFormFields();
        
        // Mostrar container de status
        statusContainer.style.display = 'block';
        resultContainer.style.display = 'none';
        
        // Atualizar status
        statusBadge.textContent = 'Iniciando';
        statusBadge.className = 'badge bg-info status-badge';
        progressBar.style.width = '10%';
        statusMessage.textContent = 'Iniciando o processamento...';
        
        // Enviar requisição para iniciar a extração
        fetch('/api/scrape', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            currentTaskId = data.task_id;
            
            // Atualizar status
            statusBadge.textContent = 'Em Processamento';
            statusBadge.className = 'badge bg-warning status-badge';
            progressBar.style.width = '25%';
            statusMessage.textContent = 'Processando a página...';
            
            // Iniciar polling para verificar o status
            startPolling();
        })
        .catch(error => {
            console.error('Erro ao iniciar extração:', error);
            
            // Atualizar status
            statusBadge.textContent = 'Erro';
            statusBadge.className = 'badge bg-danger status-badge';
            progressBar.style.width = '100%';
            statusMessage.textContent = `Erro ao iniciar extração: ${error.message}`;
            
            // Resetar estado de processamento
            resetProcessingState();
        });
    }
    
    // Iniciar polling para verificar o status da tarefa
    function startPolling() {
        // Limpar intervalo anterior se existir
        if (pollingInterval) {
            clearInterval(pollingInterval);
        }
        
        // Definir intervalo de polling (a cada 2 segundos)
        pollingInterval = setInterval(checkTaskStatus, 2000);
    }
    
    // Verificar o status da tarefa
    function checkTaskStatus() {
        if (!currentTaskId) {
            return;
        }
        
        fetch(`/api/status/${currentTaskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Atualizar status com base no status da tarefa
            switch (data.status) {
                case 'pending':
                    statusBadge.textContent = 'Pendente';
                    statusBadge.className = 'badge bg-info status-badge';
                    progressBar.style.width = '25%';
                    statusMessage.textContent = 'Aguardando processamento...';
                    break;
                    
                case 'processing':
                    statusBadge.textContent = 'Processando';
                    statusBadge.className = 'badge bg-warning status-badge';
                    progressBar.style.width = '50%';
                    statusMessage.textContent = 'Processando a página...';
                    break;
                    
                case 'completed':
                    // Limpar intervalo de polling
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    
                    // Atualizar status
                    statusBadge.textContent = 'Concluído';
                    statusBadge.className = 'badge bg-success status-badge';
                    progressBar.style.width = '100%';
                    
                    // Verificar se há resultados
                    if (data.result_count && data.result_count > 0) {
                        statusMessage.textContent = `Processamento concluído com sucesso! ${data.result_count} resultados encontrados.`;
                    } else {
                        statusMessage.textContent = 'Processamento concluído com sucesso!';
                    }
                    
                    // Armazenar dados extraídos
                    extractedData = data.extracted_data;
                    
                    // Mostrar resultados
                    showResults();
                    break;
                    
                case 'error':
                    // Limpar intervalo de polling
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    
                    // Atualizar status
                    statusBadge.textContent = 'Erro';
                    statusBadge.className = 'badge bg-danger status-badge';
                    progressBar.style.width = '100%';
                    statusMessage.textContent = `Erro durante o processamento: ${data.message}`;
                    
                    // Resetar estado de processamento
                    resetProcessingState();
                    break;
            }
        })
        .catch(error => {
            console.error('Erro ao verificar status:', error);
            
            // Atualizar status
            statusBadge.textContent = 'Erro';
            statusBadge.className = 'badge bg-danger status-badge';
            progressBar.style.width = '100%';
            statusMessage.textContent = `Erro ao verificar status: ${error.message}`;
            
            // Limpar intervalo de polling
            clearInterval(pollingInterval);
            pollingInterval = null;
            
            // Resetar estado de processamento
            resetProcessingState();
        });
    }
    
    // Mostrar resultados
    function showResults() {
        // Resetar estado de processamento
        resetProcessingState();
        
        // Limpar tabela de resultados
        resultHeaders.innerHTML = '';
        resultBody.innerHTML = '';
        
        // Verificar se há dados extraídos
        if (!extractedData || extractedData.length === 0) {
            resultContainer.style.display = 'block';
            resultBody.innerHTML = '<tr><td colspan="100%" class="text-center">Nenhum resultado encontrado.</td></tr>';
            return;
        }
        
        // Obter todas as chaves únicas de todos os resultados
        const allKeys = new Set();
        extractedData.forEach(item => {
            Object.keys(item).forEach(key => allKeys.add(key));
        });
        const keys = Array.from(allKeys);
        
        // Verificar se a tabela tem a estrutura correta
        if (!resultTable || !resultHeaders || !resultBody) {
            console.error('Estrutura da tabela não encontrada ou incompleta');
            return;
        }
        
        // Verificar se resultHeaders é um elemento tr
        if (resultHeaders.tagName !== 'TR') {
            console.error('resultHeaders não é um elemento TR');
            // Tentar encontrar ou criar o elemento tr correto
            let headerRow = resultHeaders.querySelector('tr');
            if (!headerRow) {
                headerRow = document.createElement('tr');
                resultHeaders.appendChild(headerRow);
            }
            // Usar o headerRow em vez do resultHeaders
            resultHeaders = headerRow;
        }
        
        // Adicionar cabeçalhos diretamente ao elemento thead
        keys.forEach(key => {
            const th = document.createElement('th');
            th.textContent = key;
            resultHeaders.appendChild(th);
        });
        
        // Adicionar linhas de dados
        extractedData.forEach(item => {
            const row = document.createElement('tr');
            
            keys.forEach(key => {
                const td = document.createElement('td');
                td.textContent = item[key] || 'N/A';
                row.appendChild(td);
            });
            
            resultBody.appendChild(row);
        });
        
        // Mostrar container de resultados
        resultContainer.style.display = 'block';
    }
    
    // Baixar CSV
    function downloadCSV() {
        if (!currentTaskId) {
            return;
        }
        
        window.location.href = `/api/download/${currentTaskId}/csv`;
    }
    
    // Baixar JSON
    function downloadJSON() {
        if (!currentTaskId) {
            return;
        }
        
        window.location.href = `/api/download/${currentTaskId}/json`;
    }
    
    // Baixar texto processado
    function downloadText() {
        if (!currentTaskId) {
            return;
        }
        
        window.location.href = `/api/download/${currentTaskId}/text`;
    }
    
    // Iniciar nova extração
    function startNewExtraction() {
        // Resetar formulário
        scraperForm.reset();
        
        // Mostrar/ocultar os campos específicos do provedor
        updateProviderFields();
        
        // Esconder containers de status e resultados
        statusContainer.style.display = 'none';
        resultContainer.style.display = 'none';
        
        // Resetar variáveis globais
        currentTaskId = null;
        extractedData = null;
        
        // Limpar intervalo de polling se existir
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }
    
    // Testar conexão com LLM
    function testLLMConnection() {
        // Enviado por POST para que a chave de API viaje no corpo da requisição,
        // e não na query string (onde acabaria em log de acesso e no histórico)
        const testData = new FormData();
        testData.append('model_provider', modelProviderSelect.value);

        if (isGeminiModel() && geminiKeyInput && geminiKeyInput.value) {
            testData.append('api_key', geminiKeyInput.value);
        }

        // Desabilitar botão de teste
        testLLMBtn.disabled = true;
        testLLMBtn.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Testando...';

        // Enviar requisição para testar conexão
        fetch('/api/test-llm', { method: 'POST', body: testData })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(`Teste bem-sucedido: ${data.message}`);
            } else {
                alert(`Erro no teste: ${data.message}`);
            }
        })
        .catch(error => {
            console.error('Erro ao testar conexão:', error);
            alert(`Erro ao testar conexão: ${error.message}`);
        })
        .finally(() => {
            // Reabilitar botão de teste
            testLLMBtn.disabled = false;
            testLLMBtn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Testar Conexão com LLM';
        });
    }
    
    // Verificar estrutura da tabela e corrigir se necessário
    function checkTableStructure() {
        // Verificar se a tabela tem a estrutura correta
        if (!resultTable || !resultHeaders || !resultBody) {
            console.error('Estrutura da tabela não encontrada ou incompleta');
            return;
        }
        
        // Verificar se há múltiplos elementos tbody
        const tbodies = resultTable.querySelectorAll('tbody');
        if (tbodies.length > 1) {
            console.warn('Múltiplos elementos tbody encontrados, corrigindo estrutura');
            // Manter apenas o primeiro tbody
            for (let i = 1; i < tbodies.length; i++) {
                tbodies[i].remove();
            }
        }
        
        // Verificar se resultHeaders é um elemento tr
        if (resultHeaders.tagName !== 'TR') {
            console.warn('resultHeaders não é um elemento TR, corrigindo estrutura');
            // Tentar encontrar ou criar o elemento tr correto
            let headerRow = resultHeaders.querySelector('tr');
            if (!headerRow) {
                headerRow = document.createElement('tr');
                resultHeaders.appendChild(headerRow);
            }
            // Atualizar a referência para o elemento tr correto
            resultHeaders = headerRow;
        }
    }
    
    // Sugerir modelo de visão quando uma imagem é carregada
    function suggestVisionModel() {
        // Os modelos Gemini são multimodais: já processam a imagem enviada,
        // então não faz sentido sugerir a troca por outro modelo
        if (isGeminiModel()) {
            return;
        }
        if (pageImageInput.files.length > 0 && !isVisionModel()) {
            const useVision = confirm('Você carregou uma imagem. Deseja usar um modelo com capacidade de visão para melhor processamento?');
            if (useVision) {
                modelProviderSelect.value = 'openai-vision';
                updateProviderFields();
            }
        }
    }
    
    // Atualizar interface com base no modelo selecionado
    function updateInterfaceForModel() {
        // Se um modelo de visão for selecionado, destacar o campo de upload de imagem
        const imageInputContainer = pageImageInput.parentElement;
        if (isVisionModel()) {
            imageInputContainer.classList.add('vision-model-active');
            urlInput.parentElement.classList.add('vision-model-secondary');
        } else {
            imageInputContainer.classList.remove('vision-model-active');
            urlInput.parentElement.classList.remove('vision-model-secondary');
        }
        
        // Mostrar/ocultar os campos específicos do provedor
        updateProviderFields();
    }
    
    // Registrar event listeners
    modelProviderSelect.addEventListener('change', updateInterfaceForModel);
    pageImageInput.addEventListener('change', suggestVisionModel);
    scraperForm.addEventListener('submit', startExtraction);
    testLLMBtn.addEventListener('click', testLLMConnection);
    checkStatusBtn.addEventListener('click', checkTaskStatus);
    downloadCSVBtn.addEventListener('click', downloadCSV);
    downloadJSONBtn.addEventListener('click', downloadJSON);
    downloadTextBtn.addEventListener('click', downloadText);
    newExtractionBtn.addEventListener('click', startNewExtraction);
    
    // Inicialização
    updateInterfaceForModel();
    checkTableStructure();
});
