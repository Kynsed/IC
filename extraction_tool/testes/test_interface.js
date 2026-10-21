// DOM mínimo, sem navegador ou dependências: executa o fluxo real de renderização.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor(tagName = 'DIV') {
        this.tagName = tagName;
        this.value = '';
        this.files = [];
        this.children = [];
        this.listeners = {};
        this.style = {};
        this.classList = {add() {}, remove() {}};
        this.parentElement = this;
        this.disabled = false;
        this.checked = false;
    }
    set innerHTML(value) { this.html = value; this.children = []; }
    get innerHTML() { return this.html || ''; }
    appendChild(element) { this.children.push(element); }
    replaceChildren(...elements) { this.children = elements; }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    querySelectorAll() { return []; }
    closest() { return this; }
}

async function main() {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    element('result-headers').tagName = 'TR';
    element('model-provider').value = 'gemini-3.8-flash';
    element('fields').value = 'zero, falso, ausente, vazio, aninhado';
    element('use-mock').checked = true;
    const calls = [];
    const responses = [
        {task_id: 'test-id'},
        {status: 'completed', result_count: 1, artifacts: ['manifest', 'source', 'raw'],
         extracted_data: [{zero: 0, falso: false, ausente: null, vazio: '', aninhado: {idade: 30}}]}
    ];
    const context = {
        document: {
            getElementById: element,
            createElement: tag => new Element(tag.toUpperCase()),
            addEventListener: (_name, callback) => callback()
        },
        console,
        window: {location: {}},
        FormData: class {append() {}},
        alert: message => { throw new Error(message); },
        confirm: () => false,
        setInterval: () => 1,
        clearInterval() {},
        fetch: async url => {
            calls.push(url);
            assert.ok(responses.length, 'fetch inesperado');
            return {ok: true, status: 200, json: async () => responses.shift()};
        }
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8'), context);
    element('scraper-form').listeners.submit({preventDefault() {}});
    await new Promise(resolve => setImmediate(resolve));
    element('check-status-btn').listeners.click();
    await new Promise(resolve => setImmediate(resolve));
    const values = element('result-body').children[0].children.map(cell => cell.textContent);
    assert.deepEqual(values, ['0', 'false', 'Não disponível', '', '{"idade":30}']);
    assert.equal(element('download-text-btn').disabled, true, 'imagem não deve oferecer texto fictício');
    assert.equal(element('fields').disabled, false);
    assert.equal(element('audit-downloads').children.length, 3);
    assert.deepEqual(calls, ['/api/scrape', '/api/status/test-id']);
    console.log('OK: interface preserva zero, falso, null, strings e objetos; downloads correspondem aos artefatos.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
