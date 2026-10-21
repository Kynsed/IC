// DOM mínimo com semântica de select; nenhuma requisição real é realizada.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor(tagName = 'DIV') {
        this.tagName = tagName;
        this._value = '';
        this.children = [];
        this.files = [];
        this.listeners = {};
        this.style = {};
        this.classList = {add() {}, remove() {}};
        this.parentElement = this;
        this.disabled = false;
        this.checked = false;
    }
    get value() { return this._value; }
    set value(value) {
        this._value = this.tagName !== 'SELECT' || this.children.some(option => option.value === value)
            ? value : '';
    }
    get options() { return this.children; }
    set innerHTML(value) { this.html = value; this.replaceChildren(); }
    get innerHTML() { return this.html || ''; }
    appendChild(child) {
        this.children.push(child);
        if (this.tagName === 'SELECT' && (this.children.length === 1 || child.selected)) {
            this._value = child.value;
        }
        return child;
    }
    replaceChildren(...children) {
        this.children = [];
        if (this.tagName === 'SELECT') this._value = '';
        children.forEach(child => this.appendChild(child));
    }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    querySelectorAll() { return []; }
    closest() { return this; }
}

const expectedLevels = {
    'gemini-3.8-flash': ['default', 'low', 'medium', 'high'],
    'gemini-3.7-flash': ['default', 'low', 'medium', 'high'],
    'gemini-3.6-flash': ['default', 'minimal', 'low', 'medium', 'high']
};

async function main() {
    const html = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    const selectFromTemplate = id => {
        const match = html.match(new RegExp(`<select\\b[^>]*\\bid="${id}"[^>]*>([\\s\\S]*?)</select>`));
        assert.ok(match, `Seletor ${id} ausente no template`);
        const select = new Element('SELECT');
        for (const optionMatch of match[1].matchAll(/<option\b([^>]*)>([^<]*)<\/option>/g)) {
            const option = new Element('OPTION');
            option.value = optionMatch[1].match(/\bvalue="([^"]*)"/)[1];
            option.textContent = optionMatch[2];
            option.selected = /\bselected\b/.test(optionMatch[1]);
            select.appendChild(option);
        }
        elements.set(id, select);
        return select;
    };
    const model = selectFromTemplate('model-provider');
    const thinking = selectFromTemplate('thinking-level');
    assert.deepEqual(model.options.map(option => [option.value, option.textContent]), [
        ['gemini-3.8-flash', 'Gemini 3.8 Flash'],
        ['gemini-3.7-flash', 'Gemini 3.7 Flash'],
        ['gemini-3.6-flash', 'Gemini 3.6 Flash']
    ]);
    assert.equal(model.value, 'gemini-3.8-flash');
    assert.equal(thinking.value, 'default');
    assert.match(html, /<label\b[^>]*for="thinking-level"[^>]*>Nível de raciocínio<\/label>/);
    element('fields').value = 'nome';
    element('use-mock').checked = true;
    element('gemini-api-key').value = 'TEST_KEY';
    element('scraper-form').reset = () => {
        model.value = 'gemini-3.8-flash';
        thinking.value = 'default';
    };
    const calls = [];
    const alerts = [];
    const context = {
        document: {
            getElementById: element,
            createElement: tag => new Element(tag.toUpperCase()),
            addEventListener: (_name, handler) => handler()
        },
        window: {location: {}},
        console,
        FormData: class {
            constructor() { this.values = new Map(); }
            append(name, value) { this.values.set(name, value); }
            get(name) { return this.values.get(name); }
        },
        fetch: async (url, options) => {
            calls.push({url, options});
            assert.ok(['/api/scrape', '/api/test-llm'].includes(url), `Fetch inesperado: ${url}`);
            return {ok: true, json: async () => url === '/api/scrape'
                ? {task_id: 'test-id'} : {status: 'success', message: 'OK'}};
        },
        alert: message => alerts.push(message),
        confirm: () => false,
        setInterval: () => 1,
        clearInterval() {}
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8'), context);
    const changeModel = value => {
        model.value = value;
        model.listeners.change();
    };
    const options = () => thinking.options.map(option => option.value);
    const tick = () => new Promise(resolve => setImmediate(resolve));

    assert.deepEqual(options(), expectedLevels['gemini-3.8-flash']);
    assert.deepEqual(thinking.options.map(option => option.textContent),
        ['Padrão do modelo', 'Low', 'Medium', 'High']);
    for (const selectedModel of Object.keys(expectedLevels)) {
        changeModel(selectedModel);
        assert.deepEqual(options(), expectedLevels[selectedModel]);
        for (const selectedLevel of expectedLevels[selectedModel]) {
            thinking.value = selectedLevel;
            element('test-llm-btn').listeners.click();
            await tick();
            let call = calls.at(-1);
            assert.equal(call.url, '/api/test-llm');
            assert.equal(call.options.method, 'POST');
            assert.equal(call.options.body.get('model_provider'), selectedModel);
            assert.equal(call.options.body.get('thinking_level'), selectedLevel);
            assert.equal(call.options.body.get('api_key'), 'TEST_KEY');

            element('scraper-form').listeners.submit({preventDefault() {}});
            await tick();
            call = calls.at(-1);
            assert.equal(call.url, '/api/scrape');
            assert.equal(call.options.method, 'POST');
            assert.equal(call.options.body.get('model_provider'), selectedModel);
            assert.equal(call.options.body.get('thinking_level'), selectedLevel);
            assert.equal(call.options.body.get('api_key'), 'TEST_KEY');
            assert.equal(thinking.disabled, true);
            element('new-extraction-btn').listeners.click();
            assert.equal(thinking.disabled, false);
            assert.equal(thinking.value, 'default');
            changeModel(selectedModel);
        }
    }

    for (const nextModel of ['gemini-3.7-flash', 'gemini-3.8-flash']) {
        changeModel('gemini-3.6-flash');
        thinking.value = 'minimal';
        assert.equal(thinking.value, 'minimal');
        changeModel(nextModel);
        assert.equal(thinking.value, 'default');
        assert.ok(!options().includes('minimal'));
    }
    for (const level of ['low', 'medium', 'high']) {
        changeModel('gemini-3.6-flash');
        thinking.value = level;
        changeModel('gemini-3.7-flash');
        assert.equal(thinking.value, level);
        changeModel('gemini-3.8-flash');
        assert.equal(thinking.value, level);
    }
    changeModel('gemini-3.6-flash');
    assert.equal(thinking.options.find(option => option.value === 'minimal').textContent, 'Minimal');
    assert.equal(calls.length, 26);
    assert.equal(alerts.length, 13);
    assert.ok(alerts.every(message => message.startsWith('Teste bem-sucedido:')));
    console.log('OK: 3 modelos, 13 combinações, opções dinâmicas, fallback para default e envio nas duas rotas.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
