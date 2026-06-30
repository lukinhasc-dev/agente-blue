// ============================================
//  Agente Blue — script.js
//  SSE + fetch — puro JavaScript, sem dependências
// ============================================

const ETAPAS = ['downloads', 'wallpaper', 'rede', 'smb', 'usuarios', 'impressora', 'otimizacao', 'integridade'];
let _eventSource = null;
let _swTotal = 7;   // AnyDesk + Chrome + Adobe + Office + WinRAR + Google Drive + Slack
let _swDone  = 0;

// Mapeia nome do software → id CSS (espaços → hífens)
function swId(nome) {
  return nome.replace(/\s+/g, '-');
}

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
  // Remove placeholder na primeira mensagem real
  const ph = box.querySelector('.log-placeholder');
  if (ph) ph.remove();
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

// ── Progresso individual de software ────────

function updateSwProgress(nome, estado, pct) {
  const id     = swId(nome);
  const bar    = document.getElementById('sw-bar-' + id);
  const status = document.getElementById('sw-status-' + id);
  const item   = document.getElementById('sw-' + id);
  if (!bar || !status || !item) return;

  switch (estado) {
    case 'baixando':
      bar.style.width = pct + '%';
      bar.className   = 'sw-bar downloading';
      status.textContent = `Baixando… ${pct}%`;
      status.className   = 'sw-status downloading';
      item.className     = 'sw-item active';
      break;
    case 'instalando':
      bar.style.width = '92%';
      bar.className   = 'sw-bar installing';
      status.textContent = 'Instalando…';
      status.className   = 'sw-status installing';
      break;
    case 'ok':
      bar.style.width = '100%';
      bar.className   = 'sw-bar done';
      status.textContent = '✔ Concluído';
      status.className   = 'sw-status done';
      item.className     = 'sw-item finished';
      _swDone++;
      if (_swDone >= _swTotal) {
        document.getElementById('swDoneBanner').style.display = 'flex';
      }
      break;
    case 'erro':
      bar.style.width = '100%';
      bar.className   = 'sw-bar error';
      status.textContent = '✕ Erro';
      status.className   = 'sw-status error';
      item.className     = 'sw-item sw-error';
      _swDone++;  // conta mesmo com erro para não travar o banner
      break;
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
      setStepState(e.etapa, 'running', 'Executando…');
      setProgress(e.pct, 'Etapa: ' + e.etapa + '  (' + e.pct + '%)');
      break;

    case 'etapa_fim':
      setStepState(e.etapa, e.sucesso ? 'done' : 'error',
                   e.sucesso ? 'Concluído ✓' : 'Erro ✕');
      setProgress(e.pct, e.pct + '%');
      break;

    case 'sw_progress':
      updateSwProgress(e.nome, e.estado, e.pct || 0);
      break;

    case 'setup_fim':
      _onSetupFim(e.sucesso);
      break;
  }
}

function _onSetupFim(sucesso) {
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
  document.getElementById('logBox').innerHTML =
    '<span class="log-placeholder">Os logs de execução aparecerão aqui.</span>';
  const bar = document.getElementById('progressBar');
  bar.style.width = '0%';
  bar.className   = 'progress-bar';
  btn.disabled    = true;
  btn.classList.remove('success');
  btn.textContent = 'EXECUTANDO…';

  // Coleta softwares selecionados
  const selectedSW = Array.from(document.querySelectorAll('.sw-checkbox:checked'))
                          .map(cb => cb.getAttribute('data-sw'));
  _swTotal = selectedSW.length;
  _swDone  = 0;

  document.getElementById('progressLabel').textContent = '0%';
  document.getElementById('progressLabel').style.color = '';
  document.getElementById('swDoneBanner').style.display = 'none';

  // Oculta itens não selecionados para focar no que importa
  document.querySelectorAll('.sw-item').forEach(item => {
    const cb = item.querySelector('.sw-checkbox');
    if (cb && !cb.checked) {
      item.style.display = 'none';
    } else {
      item.style.display = 'block';
    }
  });

  // Reset etapas
  ETAPAS.forEach(e => setStepState(e, '', 'Pendente'));

  // Reset barras de software
  _swDone = 0;
  ['AnyDesk', 'Google-Chrome', 'Adobe-Acrobat-Reader', 'Microsoft-365', 'WinRAR', 'Google-Drive', 'Slack'].forEach(id => {
    const bar    = document.getElementById('sw-bar-' + id);
    const status = document.getElementById('sw-status-' + id);
    const item   = document.getElementById('sw-' + id);
    if (bar)    { bar.style.width = '0%'; bar.className = 'sw-bar'; }
    if (status) { status.textContent = 'Aguardando'; status.className = 'sw-status'; }
    if (item)   { item.className = 'sw-item'; }
  });

  appendLog('[*] Iniciando Agente Blue…', 'info');
  setProgress(2, 'Iniciando…');

  if (window.location.protocol === 'http:') {
    if (_eventSource) _eventSource.close();
    _eventSource = new EventSource('/api/stream');
    _eventSource.onmessage = handleEvent;
    _eventSource.onerror   = () => {
      appendLog('[!] Conexão com servidor perdida.', 'warn');
    };
    fetch('/api/execute', { 
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        instalar_softwares: document.getElementById('chkSoftwares').checked,
        softwares_selecionados: selectedSW,
        otimizacao: document.getElementById('chkOtimizacao').checked,
        instalar_impressora: document.getElementById('chkImpressora').checked,
        verificar_integridade: document.getElementById('chkIntegridade').checked
      })
    })
      .catch(() => appendLog('[!] Falha ao contactar o servidor Python.', 'err'));
    return;
  }

  // Demo mode
  _demoMode();
}

// ── Demo mode ────────────────────────────────

function _demoMode() {
  const roteiro = [
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'downloads', pct: 5 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'AnyDesk', estado: 'baixando', pct: 10 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'AnyDesk', estado: 'baixando', pct: 55 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'AnyDesk', estado: 'baixando', pct: 90 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'AnyDesk', estado: 'instalando', pct: 92 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'AnyDesk', estado: 'ok', pct: 100 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Google Chrome', estado: 'baixando', pct: 20 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Google Chrome', estado: 'baixando', pct: 70 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Google Chrome', estado: 'instalando', pct: 92 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Google Chrome', estado: 'ok', pct: 100 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Adobe Acrobat Reader', estado: 'baixando', pct: 30 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Adobe Acrobat Reader', estado: 'baixando', pct: 80 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Adobe Acrobat Reader', estado: 'instalando', pct: 92 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'sw_progress', nome: 'Adobe Acrobat Reader', estado: 'ok', pct: 100 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'downloads', sucesso: true, pct: 30 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'wallpaper', pct: 32 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  🖼  Wallpaper aplicado', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'wallpaper', sucesso: true, pct: 38 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'rede', pct: 42 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  Regras de firewall aplicadas', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'rede', sucesso: true, pct: 80 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'smb', pct: 82 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  ✔  SMB configurado', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'smb', sucesso: true, pct: 88 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'etapa_inicio', etapa: 'usuarios', pct: 90 }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'log', msg: '  👥  Usuários Suporte e Administrador criados', tipo: 'ok' }) }),
    () => handleEvent({ data: JSON.stringify({ type: 'etapa_fim', etapa: 'usuarios', sucesso: true, pct: 95 }) }),

    () => handleEvent({ data: JSON.stringify({ type: 'setup_fim', sucesso: true }) }),
  ];

  let i = 0;
  function next() {
    if (i >= roteiro.length) return;
    roteiro[i]();
    i++;
    setTimeout(next, 300 + Math.random() * 250);
  }
  setTimeout(next, 400);
}

// ── Eventos de Inicialização ────────────────
document.getElementById('chkSoftwares').addEventListener('change', (e) => {
  const card = document.getElementById('swCard');
  const step = document.getElementById('step-downloads');
  if (e.target.checked) {
    card.style.display = 'block';
    step.style.opacity = '1';
  } else {
    card.style.display = 'none';
    step.style.opacity = '0.4';
  }
});

document.getElementById('chkOtimizacao').addEventListener('change', (e) => {
  const step = document.getElementById('step-otimizacao');
  if (e.target.checked) {
    step.style.opacity = '1';
  } else {
    step.style.opacity = '0.4';
  }
});

document.getElementById('chkImpressora').addEventListener('change', (e) => {
  const step = document.getElementById('step-impressora');
  step.style.opacity = e.target.checked ? '1' : '0.4';
});

document.getElementById('chkIntegridade').addEventListener('change', (e) => {
  const step = document.getElementById('step-integridade');
  step.style.opacity = e.target.checked ? '1' : '0.4';
});
