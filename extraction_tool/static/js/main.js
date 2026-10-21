// main.js - Script para o Web Scraper com Integração LLM (Apenas Gemini)

document.addEventListener('DOMContentLoaded', function() {
    const scraperForm = document.getElementById('scraper-form');
    const urlInput = document.getElementById('url');
    const pageImageInput = document.getElementById('page-image');
    const fieldsInput = document.getElementById('fields');
    const schemaInput = document.getElementById('schema-json');
    const auditDownloads = document.getElementById('audit-downloads');
    const modelProviderSelect = document.getElementById('model-provider');
    const thinkingLevelSelect = document.getElementById('thinking-level');
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
    let resultHeaders = document.getElementById('result-headers');
    const resultBody = document.getElementById('result-body');
    const downloadCSVBtn = document.getElementById('download-csv-btn');
    const downloadJSONBtn = document.getElementById('download-json-btn');
    const downloadTextBtn = document.getElementById('download-text-btn');
    const newExtractionBtn = document.getElementById('new-extraction-btn');

    const SUPPORTED_GEMINI_MODELS = new Set([
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.6-flash'
    ]);

    let currentTaskId = null;
    let pollingInterval = null;
    let extractedData = null;

    function isGeminiModel() {
        return SUPPORTED_GEMINI_MODELS.has(modelProviderSelect.value);
    }

    function updateProviderFields() {
        if (geminiKeyContainer) {
            geminiKeyContainer.style.display = isGeminiModel()
                ? 'block'
                : 'none';
        }
        updateThinkingLevels();
    }

    function updateThinkingLevels() {
        const selected = thinkingLevelSelect.value;
        const levels = [
            ['default', 'Padrão do modelo'],
            ['minimal', 'Minimal'],
            ['low', 'Low'],
            ['medium', 'Medium'],
            ['high', 'High']
        ].filter(([value]) => value !== 'minimal' || modelProviderSelect.value === 'gemini-3.6-flash');

        thinkingLevelSelect.replaceChildren();
        levels.forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            thinkingLevelSelect.appendChild(option);
        });
        thinkingLevelSelect.value = levels.some(([value]) => value === selected) ? selected : 'default';
    }

    function validateForm() {
        if (!isGeminiModel()) {
            alert(
                'Modelo não suportado. ' +
                'Selecione Gemini 3.8 Flash, Gemini 3.7 Flash ou Gemini 3.6 Flash.'
            );
            return false;
        }

        if (
            !useMockCheckbox.checked &&
            !urlInput.value &&
            !pageImageInput.files.length
        ) {
            alert(
                'Por favor, forneça uma URL ou uma imagem da página web ' +
                '(ou marque "Usar dados de exemplo").'
            );
            return false;
        }

        if (schemaInput.value.trim()) {
            try {
                JSON.parse(schemaInput.value);
            } catch (_) {
                alert('O schema precisa ser um JSON válido.');
                return false;
            }
        }

        if (
            !fieldsInput.value.trim() &&
            !schemaInput.value.trim()
        ) {
            alert(
                'Por favor, especifique os campos que deseja extrair.'
            );
            return false;
        }

        return true;
    }

    function disableFormFields() {
        urlInput.disabled = true;
        pageImageInput.disabled = true;
        fieldsInput.disabled = true;
        schemaInput.disabled = true;
        modelProviderSelect.disabled = true;
        thinkingLevelSelect.disabled = true;

        if (geminiKeyInput) {
            geminiKeyInput.disabled = true;
        }

        useMockCheckbox.disabled = true;
        submitBtn.disabled = true;
        testLLMBtn.disabled = true;

        const card = scraperForm.closest('.card');

        if (card) {
            card.classList.add('form-readonly');
        }

        submitBtn.innerHTML =
            '<i class="bi bi-hourglass-split me-2"></i>Processando...';
    }

    function resetProcessingState() {
        urlInput.disabled = false;
        pageImageInput.disabled = false;
        fieldsInput.disabled = false;
        schemaInput.disabled = false;
        modelProviderSelect.disabled = false;
        thinkingLevelSelect.disabled = false;

        if (geminiKeyInput) {
            geminiKeyInput.disabled = false;
        }

        useMockCheckbox.disabled = false;
        submitBtn.disabled = false;
        testLLMBtn.disabled = false;

        const card = scraperForm.closest('.card');

        if (card) {
            card.classList.remove('form-readonly');
        }

        submitBtn.innerHTML =
            '<i class="bi bi-search me-2"></i>Iniciar Extração';
    }

    function startExtraction(event) {
        event.preventDefault();

        if (!validateForm()) {
            return;
        }

        const formData = new FormData();

        formData.append(
            'fields',
            fieldsInput.value
        );

        if (schemaInput.value.trim()) {
            formData.append(
                'schema_json',
                schemaInput.value
            );
        }

        formData.append(
            'model_provider',
            modelProviderSelect.value
        );
        formData.append('thinking_level', thinkingLevelSelect.value);

        formData.append(
            'use_mock',
            useMockCheckbox.checked
        );

        if (urlInput.value) {
            formData.append(
                'url',
                urlInput.value
            );
        }

        if (pageImageInput.files.length > 0) {
            formData.append(
                'page_image',
                pageImageInput.files[0]
            );
        }

        if (
            isGeminiModel() &&
            geminiKeyInput &&
            geminiKeyInput.value
        ) {
            formData.append(
                'api_key',
                geminiKeyInput.value
            );
        }

        disableFormFields();

        statusContainer.style.display = 'block';
        resultContainer.style.display = 'none';

        auditDownloads.replaceChildren();

        statusBadge.textContent = 'Iniciando';
        statusBadge.className =
            'badge bg-info status-badge';

        progressBar.style.width = '10%';

        statusMessage.textContent =
            'Iniciando o processamento...';

        fetch('/api/scrape', {
            method: 'POST',
            body: formData
        })
        .then(async response => {
            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error ||
                    `Erro HTTP ${response.status}`
                );
            }

            return data;
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }

            currentTaskId = data.task_id;

            statusBadge.textContent =
                'Em Processamento';

            statusBadge.className =
                'badge bg-warning status-badge';

            progressBar.style.width =
                '25%';

            statusMessage.textContent =
                'Processando a página...';

            startPolling();
        })
        .catch(error => {
            console.error(
                'Erro ao iniciar extração:',
                error
            );

            statusBadge.textContent =
                'Erro';

            statusBadge.className =
                'badge bg-danger status-badge';

            progressBar.style.width =
                '100%';

            statusMessage.textContent =
                `Erro ao iniciar extração: ${error.message}`;

            resetProcessingState();
        });
    }

    function startPolling() {
        if (pollingInterval) {
            clearInterval(
                pollingInterval
            );
        }

        pollingInterval = setInterval(
            checkTaskStatus,
            2000
        );
    }

    function checkTaskStatus() {
        if (!currentTaskId) {
            return;
        }

        fetch(
            `/api/status/${currentTaskId}`
        )
        .then(async response => {
            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error ||
                    `Erro HTTP ${response.status}`
                );
            }

            return data;
        })
        .then(data => {
            if (data.error) {
                throw new Error(
                    data.error
                );
            }

            auditDownloads.replaceChildren();

            const artifactLabels = {
                manifest: 'Manifesto',
                source: 'Fonte original',
                raw: 'Resposta bruta',
                text: 'Entrada processada'
            };

            (
                data.artifacts || []
            ).forEach(kind => {
                const link =
                    document.createElement('a');

                link.className =
                    'btn btn-sm btn-outline-secondary';

                link.href =
                    `/api/download/${currentTaskId}/${kind}`;

                link.textContent =
                    artifactLabels[kind] || kind;

                auditDownloads.appendChild(
                    link
                );
            });

            downloadTextBtn.disabled =
                !(data.artifacts || []).includes(
                    'text'
                );

            switch (data.status) {
                case 'pending':
                    statusBadge.textContent =
                        'Pendente';

                    statusBadge.className =
                        'badge bg-info status-badge';

                    progressBar.style.width =
                        '25%';

                    statusMessage.textContent =
                        'Aguardando processamento...';

                    break;

                case 'processing':
                    statusBadge.textContent =
                        'Processando';

                    statusBadge.className =
                        'badge bg-warning status-badge';

                    progressBar.style.width =
                        '50%';

                    statusMessage.textContent =
                        'Processando a página...';

                    break;

                case 'completed':
                    if (pollingInterval) {
                        clearInterval(
                            pollingInterval
                        );

                        pollingInterval = null;
                    }

                    statusBadge.textContent =
                        'Concluído';

                    statusBadge.className =
                        'badge bg-success status-badge';

                    progressBar.style.width =
                        '100%';

                    if (
                        data.result_count &&
                        data.result_count > 0
                    ) {
                        statusMessage.textContent =
                            'Processamento concluído com sucesso! ' +
                            `${data.result_count} resultados encontrados.`;
                    } else {
                        statusMessage.textContent =
                            'Processamento concluído com sucesso!';
                    }

                    extractedData =
                        data.extracted_data;

                    showResults();

                    break;

                case 'error':
                    if (pollingInterval) {
                        clearInterval(
                            pollingInterval
                        );

                        pollingInterval = null;
                    }

                    statusBadge.textContent =
                        'Erro';

                    statusBadge.className =
                        'badge bg-danger status-badge';

                    progressBar.style.width =
                        '100%';

                    statusMessage.textContent =
                        'Erro durante o processamento: ' +
                        (
                            data.message ||
                            'Erro desconhecido.'
                        );

                    resetProcessingState();

                    break;

                default:
                    console.warn(
                        'Status desconhecido recebido do servidor:',
                        data.status
                    );

                    break;
            }
        })
        .catch(error => {
            console.error(
                'Erro ao verificar status:',
                error
            );

            statusBadge.textContent =
                'Erro';

            statusBadge.className =
                'badge bg-danger status-badge';

            progressBar.style.width =
                '100%';

            statusMessage.textContent =
                `Erro ao verificar status: ${error.message}`;

            if (pollingInterval) {
                clearInterval(
                    pollingInterval
                );

                pollingInterval = null;
            }

            resetProcessingState();
        });
    }

    function showResults() {
        resetProcessingState();

        resultHeaders.innerHTML = '';
        resultBody.innerHTML = '';

        if (
            !extractedData ||
            extractedData.length === 0
        ) {
            resultContainer.style.display =
                'block';

            resultBody.innerHTML =
                '<tr>' +
                '<td colspan="100%" class="text-center">' +
                'Nenhum resultado encontrado.' +
                '</td>' +
                '</tr>';

            return;
        }

        const allKeys =
            new Set();

        extractedData.forEach(
            item => {
                Object.keys(item).forEach(
                    key => allKeys.add(key)
                );
            }
        );

        const keys =
            Array.from(allKeys);

        if (
            resultHeaders.tagName !== 'TR'
        ) {
            let headerRow =
                resultHeaders.querySelector(
                    'tr'
                );

            if (!headerRow) {
                headerRow =
                    document.createElement(
                        'tr'
                    );

                resultHeaders.appendChild(
                    headerRow
                );
            }

            resultHeaders =
                headerRow;
        }

        keys.forEach(key => {
            const th =
                document.createElement('th');

            th.textContent =
                key;

            resultHeaders.appendChild(
                th
            );
        });

        extractedData.forEach(
            item => {
                const row =
                    document.createElement(
                        'tr'
                    );

                keys.forEach(
                    key => {
                        const td =
                            document.createElement(
                                'td'
                            );

                        const value =
                            item[key];

                        if (value == null) {
                            td.textContent =
                                'Não disponível';
                        } else if (
                            typeof value ===
                            'object'
                        ) {
                            td.textContent =
                                JSON.stringify(
                                    value
                                );
                        } else {
                            td.textContent =
                                String(value);
                        }

                        row.appendChild(
                            td
                        );
                    }
                );

                resultBody.appendChild(
                    row
                );
            }
        );

        resultContainer.style.display =
            'block';
    }

    function downloadCSV() {
        if (
            currentTaskId
        ) {
            window.location.href =
                `/api/download/${currentTaskId}/csv`;
        }
    }

    function downloadJSON() {
        if (
            currentTaskId
        ) {
            window.location.href =
                `/api/download/${currentTaskId}/json`;
        }
    }

    function downloadText() {
        if (
            currentTaskId
        ) {
            window.location.href =
                `/api/download/${currentTaskId}/text`;
        }
    }

    function startNewExtraction() {
        scraperForm.reset();

        fieldsInput.required = true;

        auditDownloads.replaceChildren();

        updateProviderFields();

        statusContainer.style.display =
            'none';

        resultContainer.style.display =
            'none';

        currentTaskId = null;
        extractedData = null;

        if (pollingInterval) {
            clearInterval(
                pollingInterval
            );

            pollingInterval = null;
        }

        resetProcessingState();
    }

    function testLLMConnection() {
        if (!isGeminiModel()) {
            alert(
                'Modelo não suportado. ' +
                'Selecione Gemini 3.8 Flash, Gemini 3.7 Flash ou Gemini 3.6 Flash.'
            );

            return;
        }

        const testData =
            new FormData();

        testData.append(
            'model_provider',
            modelProviderSelect.value
        );
        testData.append('thinking_level', thinkingLevelSelect.value);

        if (
            geminiKeyInput &&
            geminiKeyInput.value
        ) {
            testData.append(
                'api_key',
                geminiKeyInput.value
            );
        }

        testLLMBtn.disabled =
            true;

        testLLMBtn.innerHTML =
            '<i class="bi bi-hourglass-split me-2"></i>Testando...';

        fetch(
            '/api/test-llm',
            {
                method: 'POST',
                body: testData
            }
        )
        .then(async response => {
            const data =
                await response.json();

            if (!response.ok) {
                throw new Error(
                    data.message ||
                    data.error ||
                    `Erro HTTP ${response.status}`
                );
            }

            return data;
        })
        .then(data => {
            if (
                data.status ===
                'success'
            ) {
                alert(
                    `Teste bem-sucedido: ${data.message}`
                );
            } else {
                alert(
                    `Erro no teste: ${data.message}`
                );
            }
        })
        .catch(error => {
            console.error(
                'Erro ao testar conexão:',
                error
            );

            alert(
                `Erro ao testar conexão: ${error.message}`
            );
        })
        .finally(() => {
            testLLMBtn.disabled =
                false;

            testLLMBtn.innerHTML =
                '<i class="bi bi-check-circle me-2"></i>' +
                'Testar Conexão com LLM';
        });
    }

    schemaInput.addEventListener(
        'input',
        () => {
            fieldsInput.required =
                !schemaInput.value.trim();
        }
    );

    fieldsInput.required =
        !schemaInput.value.trim();

    modelProviderSelect.addEventListener(
        'change',
        updateProviderFields
    );

    scraperForm.addEventListener(
        'submit',
        startExtraction
    );

    testLLMBtn.addEventListener(
        'click',
        testLLMConnection
    );

    checkStatusBtn.addEventListener(
        'click',
        checkTaskStatus
    );

    downloadCSVBtn.addEventListener(
        'click',
        downloadCSV
    );

    downloadJSONBtn.addEventListener(
        'click',
        downloadJSON
    );

    downloadTextBtn.addEventListener(
        'click',
        downloadText
    );

    newExtractionBtn.addEventListener(
        'click',
        startNewExtraction
    );

    updateProviderFields();
});