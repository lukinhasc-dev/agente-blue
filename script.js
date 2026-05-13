// ============================================
//  Agente Blue — script.js
//  Comunicação via SSE (Server-Sent Events) + fetch
//  Sem dependências externas — puro JavaScript
// ============================================

const ETAPAS = ['downloads', 'rede', 'smb'];
let _eventSource = null;

// ── Utilitários de UI ────────────────────────

function setProgress(pct, text, finalOk) {
  const b = document.getElementById('progressBar');
  b.style.width = pct + '%';
  b.className   = 'progress-bar' + (finalOk ? ' complete' : '');
  const l = document.getElementById('progressLabel');
  l.textContent = text;
  l.style.color = finalOk ? 'var(--green)' : '';
}

function appendLog(msg, tipo) {
  const box  = document.getElementById('logBox');
  const line = document.createElement('span');
  line.className   = 'log-line ' + (tipo || 'muted');
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function setStepState(etapa, state, badgeText) {
  const radio = document.getElementById('radio-' + etapa);
  const badge = document.getElementById('badge-' + etapa);
  if (radio) radio.className = 'custom-radio ' + state;
  if (badge) {
    badge.className   = 'step-badge ' + state;
    badge.textContent = badgeText;
  }
}

// ── Handlers de eventos SSE ──────────────────

function handleEvent(event) {
  const e = JSON.parse(event.data);

  switch (e.type) {

    case 'log':
      appendLog(e.msg, e.tipo);
      break;

    case 'etapa_inicio':
      setStepState(e.etapa, 'running', 'Executando...');
      setProgress(e.pct, 'Etapa: ' + e.etapa + '  (' + e.pct + '%)');
      break;

    case 'etapa_fim':
      if (e.sucesso) {
        setStepState(e.etapa, 'done', 'Concluído ✓');
      } else {
        setStepState(e.etapa, 'error', 'Erro ✕');
      }
      setProgress(e.pct, e.pct + '%');
      break;

    case 'setup_fim':
      _onSetupFim(e.sucesso);
      break;
  }
}

function _onSetupFim(sucesso) {
  // Fecha o stream SSE
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }

  const btn = document.getElementById('btnExecutar');
  btn.disabled = false;

  if (sucesso) {
    setProgress(100, 'Setup concluído com sucesso!', true);
    btn.textContent = '✔  CONCLUÍDO';
    btn.classList.add('success');
    appendLog('[✓] Setup finalizado com sucesso!', 'ok');
  } else {
    setProgress(100, 'Concluído com erros — verifique o log.');
    btn.textContent = '↺  EXECUTAR NOVAMENTE';
    appendLog('[!] Setup concluído com erros. Verifique os itens acima.', 'warn');
  }
}

// ── Botão Executar ───────────────────────────

function iniciarAgente() {
  const btn = document.getElementById('btnExecutar');

  // Reset visual
  document.getElementById('logBox').innerHTML = '';
  const bar = document.getElementById('progressBar');
  bar.style.width = '0%';
  bar.className   = 'progress-bar';
  btn.disabled    = true;
  btn.classList.remove('success');
  btn.textContent = 'EXECUTANDO...';
  document.getElementById('progressLabel').textContent = '0%';
  document.getElementById('progressLabel').style.color = '';

  ETAPAS.forEach(e => setStepState(e, '', 'Pendente'));
  appendLog('[*] Iniciando Agente Blue...', 'info');
  setProgress(2, 'Iniciando...');

  // Modo produção (Python HTTP server)
  if (window.location.protocol === 'http:') {
    // Abre conexão SSE para receber eventos em tempo real
    if (_eventSource) _eventSource.close();
    _eventSource = new EventSource('/api/stream');
    _eventSource.onmessage = handleEvent;
    _eventSource.onerror   = () => {
      appendLog('[!] Conexão com servidor perdida.', 'warn');
    };

    // Dispara a automação no servidor
    fetch('/api/execute', { method: 'POST' })
      .catch(() => appendLog('[!] Falha ao contactar o servidor Python.', 'err'));

    return;
  }

  // Modo demo (arquivo aberto diretamente no browser, sem servidor)
  _demoMode();
}

// ── Demo mode (preview sem servidor Python) ──

function _demoMode() {
  const roteiro = [
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'downloads', pct: 5 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  Nenhum software configurado para esta etapa.', tipo: 'muted' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'downloads', sucesso: true, pct: 33 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'rede', pct: 36 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ▶  Descoberta de Rede → Privada ATIVADO', tipo: 'info' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  Sucesso', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ▶  File and Printer Sharing → Public OFF', tipo: 'info' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  Sucesso', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'rede', sucesso: true, pct: 66 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'smb', pct: 70 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ▶  Set-SmbClientConfiguration RequireSecuritySignature=False', tipo: 'info' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  Sucesso', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ▶  Registro: EnableSecuritySignature = 0', tipo: 'info' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  Sucesso', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'smb', sucesso: true, pct: 100 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'setup_fim', sucesso: true }) }),
  ];

  let i = 0;
  function next() {
    if (i >= roteiro.length) return;
    roteiro[i]();
    i++;
    setTimeout(next, 380 + Math.random() * 320);
  }
  setTimeout(next, 500);
}
