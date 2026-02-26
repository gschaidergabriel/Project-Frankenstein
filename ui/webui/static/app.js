/* ══════════════════════════════════════════════════════════
   F.R.A.N.K. Web UI — Main Application Logic
   ══════════════════════════════════════════════════════════ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── State ────────────────────────────────────────────────
let ws = null;
let wsReconnectTimer = null;
let isStreaming = false;
let streamBuffer = '';
let currentStreamEl = null;
let auraTimer = null;
let statusTimer = null;

// ── DOM refs ─────────────────────────────────────────────
const chatMessages = $('#chatMessages');
const chatInput = $('#chatInput');
const sendBtn = $('#sendBtn');
const connDot = $('#connDot');
const connText = $('#connText');
const logMessages = $('#logMessages');

// ── Category icons ───────────────────────────────────────
const CAT_ICONS = {
    consciousness: '\u{1F9E0}',
    dream: '\u{1F4AD}',
    entity: '\u{1F464}',
    therapist: '\u{1F49A}',
    mirror: '\u2694\uFE0F',
    atlas: '\u{1F9ED}',
    muse: '\u{1F3A8}',
};

const CAT_SHORT = {
    consciousness: 'CSCN',
    dream: 'DREM',
    entity: 'ENTY',
    therapist: 'THRP',
    mirror: 'MIRR',
    atlas: 'ATLS',
    muse: 'MUSE',
};

// ── WebSocket ────────────────────────────────────────────
function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/live`);

    ws.onopen = () => {
        connDot.classList.add('online');
        connText.textContent = 'CONNECTED';
        if (wsReconnectTimer) {
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = null;
        }
    };

    ws.onclose = () => {
        connDot.classList.remove('online');
        connText.textContent = 'DISCONNECTED';
        wsReconnectTimer = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        } catch (e) {
            console.warn('WS parse error:', e);
        }
    };
}

function handleWsMessage(msg) {
    switch (msg.type) {
        case 'chat_token':
            handleChatToken(msg.content);
            break;

        case 'chat_done':
            handleChatDone(msg.text);
            break;

        case 'chat_sync':
            // Real-time message from overlay — show if not currently streaming
            if (!isStreaming) {
                addChatMessage(
                    msg.sender || (msg.is_user ? 'Du' : 'Frank'),
                    msg.text || '',
                    !!msg.is_user
                );
            }
            break;

        case 'notification':
            addLogEntry(msg);
            break;

        case 'status':
            updateStatus(msg);
            break;
    }
}

// ── AURA Polling (HTTP — too large for WebSocket) ─────────
let auraPollBusy = false;

async function pollAura() {
    if (!window.auraRenderer || auraPollBusy) return;
    auraPollBusy = true;
    try {
        const resp = await fetch('/api/aura/grid');
        if (resp.ok) {
            const data = await resp.json();
            window.auraRenderer.update(data);
        }
    } catch (e) {
        // Silent — AURA service might be down
    } finally {
        auraPollBusy = false;
    }
}

function startAuraPolling() {
    if (auraTimer) return;
    pollAura();
    auraTimer = setInterval(pollAura, 200);
}

// ── Status Polling (HTTP fallback) ────────────────────────
async function pollStatus() {
    try {
        const [healthResp, sysResp, gpuResp] = await Promise.all([
            fetch('/api/health').catch(() => null),
            fetch('/api/system').catch(() => null),
            fetch('/api/gpu').catch(() => null),
        ]);

        const status = {};
        if (healthResp && healthResp.ok) {
            const h = await healthResp.json();
            status.core = h.core;
            status.llm = h.llm;
            status.tools = h.toolbox;
            status.aura = h.aura;
        }

        if (sysResp && sysResp.ok) {
            const d = await sysResp.json();
            // CPU temp: find k10temp (Tctl = actual CPU package temp)
            if (d.temps) {
                let cpuTemp = 0;
                const sensors = d.temps.sensors || [];
                for (const s of sensors) {
                    if (s.chip === 'k10temp') { cpuTemp = Math.round(s.temp_c || 0); break; }
                }
                status.cpu_temp = cpuTemp || Math.round(d.temps.max_c || 0);
            }
            if (d.mem && d.mem.mem_kb) {
                const total = d.mem.mem_kb.total || 1;
                const used = d.mem.mem_kb.used || 0;
                status.ram_pct = Math.round((used / Math.max(total, 1)) * 100);
            }
            if (d.cpu) {
                const cpuCores = d.cpu.cores || 16;
                status.cpu_pct = Math.round((parseFloat(d.cpu.load_1m) || 0) * 100 / cpuCores);
            }
        }

        if (gpuResp && gpuResp.ok) {
            const g = await gpuResp.json();
            if (g.gpu_pct !== undefined) status.gpu_pct = g.gpu_pct;
            if (g.gpu_temp !== undefined) status.gpu_temp = g.gpu_temp;
        }

        updateStatus(status);
    } catch (e) {
        // Silent
    }
}

function startStatusPolling() {
    if (statusTimer) return;
    pollStatus();
    statusTimer = setInterval(pollStatus, 10000);
}

// ── Chat ─────────────────────────────────────────────────
function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isStreaming) return;

    // Add user message
    addChatMessage('Du', text, true);
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Start streaming
    isStreaming = true;
    streamBuffer = '';
    sendBtn.disabled = true;

    // Show typing indicator then send via WS
    showTypingIndicator();

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'chat', text }));
    } else {
        // Fallback: REST
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        }).catch(() => {
            handleChatDone('[Error: connection lost]');
        });
    }
}

function handleChatToken(content) {
    if (!currentStreamEl) {
        removeTypingIndicator();
        currentStreamEl = addChatMessage('Frank', '', false, true);
    }
    streamBuffer += content;
    const textEl = currentStreamEl.querySelector('.msg-text');
    if (textEl) {
        textEl.textContent = streamBuffer;
    }
    scrollChat();
}

function handleChatDone(fullText) {
    removeTypingIndicator();
    if (currentStreamEl) {
        const textEl = currentStreamEl.querySelector('.msg-text');
        if (textEl) {
            textEl.textContent = fullText || streamBuffer;
        }
    } else if (fullText) {
        addChatMessage('Frank', fullText, false);
    }
    currentStreamEl = null;
    streamBuffer = '';
    isStreaming = false;
    sendBtn.disabled = false;
    scrollChat();
}

function addChatMessage(sender, text, isUser, isStreaming = false) {
    const el = document.createElement('div');
    el.className = `msg ${isUser ? 'msg-user' : 'msg-frank'}`;

    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    el.innerHTML = `
        <div class="msg-sender">${isUser ? '\u25B6 ' : '\u25C4 '}${sender}</div>
        <div class="msg-text">${escapeHtml(text)}</div>
        <div class="msg-time">${ts}</div>
    `;

    chatMessages.appendChild(el);
    scrollChat();
    return el;
}

function showTypingIndicator() {
    removeTypingIndicator();
    const el = document.createElement('div');
    el.className = 'typing-indicator';
    el.id = 'typingIndicator';
    el.innerHTML = '<span></span><span></span><span></span>';
    chatMessages.appendChild(el);
    scrollChat();
}

function removeTypingIndicator() {
    const el = document.getElementById('typingIndicator');
    if (el) el.remove();
}

function scrollChat() {
    requestAnimationFrame(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}

// ── Chat History ─────────────────────────────────────────
async function loadChatHistory() {
    try {
        const resp = await fetch('/api/chat/history?limit=30');
        const messages = await resp.json();
        if (Array.isArray(messages)) {
            messages.forEach(m => {
                addChatMessage(
                    m.is_user ? 'Du' : 'Frank',
                    m.text || '',
                    !!m.is_user
                );
            });
        }
    } catch (e) {
        console.warn('Failed to load history:', e);
    }
}

// ── Log Panel ────────────────────────────────────────────
function addLogEntry(data) {
    const cat = data.category || 'unknown';
    const icon = CAT_ICONS[cat] || '\u{1F514}';
    const catShort = CAT_SHORT[cat] || cat.toUpperCase().slice(0, 4);
    const text = data.text || data.body || '';
    const ts = data.ts ? new Date(data.ts).toLocaleTimeString('de-DE', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    }) : new Date().toLocaleTimeString('de-DE', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    const el = document.createElement('div');
    el.className = 'log-entry';
    el.setAttribute('data-cat', cat);
    el.innerHTML = `
        <div class="log-entry-header">
            <span class="log-ts">${ts} ${icon}</span>
            <span class="log-cat">${catShort}</span>
        </div>
        <div class="log-text">${escapeHtml(text)}</div>
    `;

    logMessages.appendChild(el);

    // Separator
    const sep = document.createElement('div');
    sep.className = 'log-sep';
    logMessages.appendChild(sep);

    // Keep max 200 entries (each = 2 elements)
    while (logMessages.children.length > 400) {
        logMessages.removeChild(logMessages.firstChild);
        logMessages.removeChild(logMessages.firstChild);
    }

    // Auto-scroll
    logMessages.scrollTop = logMessages.scrollHeight;
}

async function loadNotifications() {
    try {
        const resp = await fetch('/api/notifications?limit=30');
        const entries = await resp.json();
        const LOG_CATS = new Set([
            'consciousness', 'dream', 'entity',
            'therapist', 'mirror', 'atlas', 'muse',
        ]);
        if (Array.isArray(entries)) {
            entries
                .filter(e => LOG_CATS.has(e.category))
                .slice(-30)
                .forEach(e => {
                    addLogEntry({
                        category: e.category,
                        text: e.body || e.title || '',
                        ts: e.timestamp,
                    });
                });
        }
    } catch (e) {
        console.warn('Failed to load notifications:', e);
    }
}

// ── Status Bar ───────────────────────────────────────────
function updateStatus(data) {
    const svcMap = { core: 'svcCore', llm: 'svcLlm', tools: 'svcTools', aura: 'svcAura' };
    for (const [key, id] of Object.entries(svcMap)) {
        const el = document.getElementById(id);
        if (el) {
            if (data[key]) {
                el.classList.add('online');
            } else {
                el.classList.remove('online');
            }
        }
    }

    if (data.cpu_temp !== undefined) {
        $('#metricTemp').textContent = `CPU: ${data.cpu_temp}°C`;
    }
    if (data.cpu_pct !== undefined) {
        $('#metricCpu').textContent = `CPU: ${data.cpu_pct}%`;
    }
    if (data.gpu_pct !== undefined) {
        const gpuText = data.gpu_temp !== undefined
            ? `GPU: ${data.gpu_pct}% ${data.gpu_temp}°C`
            : `GPU: ${data.gpu_pct}%`;
        $('#metricGpu').textContent = gpuText;
    }
    if (data.ram_pct !== undefined) {
        $('#metricRam').textContent = `RAM: ${data.ram_pct}%`;
    }
}

// ── Utilities ────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Input Handling ───────────────────────────────────────
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 100) + 'px';
});

sendBtn.addEventListener('click', sendMessage);

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    // Load history and notifications in parallel
    await Promise.all([
        loadChatHistory(),
        loadNotifications(),
    ]);

    // Init AURA renderer
    if (window.AuraRenderer) {
        window.auraRenderer = new AuraRenderer('auraCanvas', 'auraBloom');
    }

    // Connect WebSocket (for chat + notifications)
    connectWebSocket();

    // Start HTTP polling for AURA (too large for WebSocket) and status
    startAuraPolling();
    startStatusPolling();
});
