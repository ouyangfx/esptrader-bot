// Dashboard JavaScript con WebSocket, Monitoreo Multi-Par y Test de Conexión IQ Option

document.addEventListener('DOMContentLoaded', () => {
  // Elementos DOM
  const clockEl = document.getElementById('server-clock');
  const accountModeEl = document.getElementById('account-mode-text');
  const accountBalanceEl = document.getElementById('account-balance-text');
  
  const heroCard = document.querySelector('.bot-control-hero');
  const statusTitleEl = document.getElementById('status-title');
  const statusDescEl = document.getElementById('status-desc');
  const btnToggle = document.getElementById('btn-toggle-bot');
  
  // IQ Test
  const testEmail = document.getElementById('test-iq-email');
  const testPass = document.getElementById('test-iq-pass');
  const testAccount = document.getElementById('test-iq-account');
  const btnTestIq = document.getElementById('btn-test-iq');
  const btnTestIqText = document.getElementById('btn-test-iq-text');
  const iqStatusBadge = document.getElementById('iq-status-badge');
  const iqTestResult = document.getElementById('iq-test-result');

  // Multi-Pair Checkboxes
  const chkPairs = document.querySelectorAll('.chk-pair');
  const selectedCountEl = document.getElementById('selected-count');
  const btnSelectNormal = document.getElementById('btn-select-normal');
  const btnSelectOtc = document.getElementById('btn-select-otc');
  const btnSelectAll = document.getElementById('btn-select-all');
  const btnDeselectAll = document.getElementById('btn-deselect-all');
  const multiPairsGrid = document.getElementById('multi-pairs-grid');

  // Radar Principal
  const radarPairEl = document.getElementById('radar-pair-tag');
  const radarPriceEl = document.getElementById('radar-price');
  const radarCountdownEl = document.getElementById('radar-countdown');
  const countdownProgressEl = document.getElementById('countdown-progress');
  const cycleMsgEl = document.getElementById('cycle-msg');
  
  const stepSearch = document.getElementById('step-search');
  const stepConfirm = document.getElementById('step-confirm');
  const stepTrade = document.getElementById('step-trade');
  
  // Métricas
  const metricWinrate = document.getElementById('metric-winrate');
  const metricProfit = document.getElementById('metric-profit');
  const metricWins = document.getElementById('metric-wins');
  const metricLosses = document.getElementById('metric-losses');
  
  // Historial & Terminal
  const tradesBody = document.getElementById('trades-body');
  const tableCount = document.getElementById('table-count');
  const terminalLogs = document.getElementById('terminal-logs');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  
  // Parámetros
  const configForm = document.getElementById('form-config');
  const cfgTimeframe = document.getElementById('cfg-timeframe');
  const cfgAmount = document.getElementById('cfg-amount');
  const cfgMartingale = document.getElementById('cfg-martingale');
  const cfgAccount = document.getElementById('cfg-account');

  let isBotRunning = false;
  let ws = null;

  // Actualizar reloj local
  setInterval(() => {
    const now = new Date();
    clockEl.textContent = now.toTimeString().split(' ')[0];
  }, 1000);

  function logToTerminal(message, type = 'info') {
    const line = document.createElement('div');
    line.className = `term-line ${type}`;
    const time = new Date().toTimeString().split(' ')[0];
    line.textContent = `[${time}] ${message}`;
    terminalLogs.appendChild(line);
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
  }

  btnClearLogs.addEventListener('click', () => {
    terminalLogs.innerHTML = '';
  });

  // ==========================================
  // GESTIÓN DE PARES (CHECKBOXES & ACCIONES RÁPIDAS)
  // ==========================================
  function updateCheckboxUI() {
    let count = 0;
    chkPairs.forEach(chk => {
      const card = chk.closest('.pair-checkbox-card');
      if (chk.checked) {
        card.classList.add('checked');
        count++;
      } else {
        card.classList.remove('checked');
      }
    });
    selectedCountEl.textContent = count;
    return count;
  }

  async function syncSelectedPairs() {
    const selected = [];
    chkPairs.forEach(chk => {
      if (chk.checked) selected.push(chk.value);
    });

    try {
      const res = await fetch('/api/pairs/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pairs: selected })
      });
      const data = await res.json();
      if (data.success) {
        logToTerminal(data.message, 'info');
      } else {
        logToTerminal(data.message, 'warn');
      }
    } catch (e) {
      console.error("Error sincronizando pares:", e);
    }
  }

  // Inicializar UI de checkboxes
  updateCheckboxUI();

  chkPairs.forEach(chk => {
    chk.addEventListener('change', () => {
      updateCheckboxUI();
      syncSelectedPairs();
    });
  });

  btnSelectNormal.addEventListener('click', () => {
    chkPairs.forEach(chk => {
      if (!chk.value.includes('-OTC')) {
        chk.checked = true;
      }
    });
    updateCheckboxUI();
    syncSelectedPairs();
  });

  btnSelectOtc.addEventListener('click', () => {
    chkPairs.forEach(chk => {
      if (chk.value.includes('-OTC')) {
        chk.checked = true;
      }
    });
    updateCheckboxUI();
    syncSelectedPairs();
  });

  btnSelectAll.addEventListener('click', () => {
    chkPairs.forEach(chk => chk.checked = true);
    updateCheckboxUI();
    syncSelectedPairs();
  });

  btnDeselectAll.addEventListener('click', () => {
    chkPairs.forEach(chk => chk.checked = false);
    updateCheckboxUI();
    syncSelectedPairs();
  });

  // ==========================================
  // PRUEBA DE CONEXIÓN IQ OPTION
  // ==========================================
  btnTestIq.addEventListener('click', async () => {
    const email = testEmail.value.trim();
    const pass = testPass.value.trim();
    const accountType = testAccount.value;

    if (!email || !pass) {
      iqTestResult.className = 'iq-test-result error';
      iqTestResult.textContent = 'Ingresa el correo y la contraseña de IQ Option para realizar la prueba.';
      iqTestResult.style.display = 'block';
      return;
    }

    btnTestIq.disabled = true;
    btnTestIqText.textContent = 'Probando conexión...';
    iqStatusBadge.className = 'status-badge-iq';
    iqStatusBadge.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Conectando con IQ Option...';

    iqTestResult.style.display = 'none';

    try {
      const resp = await fetch('/api/iq/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email, password: pass, account_type: accountType })
      });
      const data = await resp.json();

      if (data.success) {
        iqStatusBadge.className = 'status-badge-iq connected';
        iqStatusBadge.innerHTML = `<i class="fa-solid fa-circle-check"></i> Conectado (${data.account_type})`;

        iqTestResult.className = 'iq-test-result success';
        iqTestResult.textContent = `✅ ${data.message}`;
        iqTestResult.style.display = 'block';

        accountModeEl.textContent = data.account_type;
        accountBalanceEl.textContent = `$${data.balance.toFixed(2)}`;

        logToTerminal(`IQ Option conectado: Saldo $${data.balance.toFixed(2)} (${data.account_type})`, 'success');
      } else {
        iqStatusBadge.className = 'status-badge-iq error';
        iqStatusBadge.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Error de Credenciales';

        iqTestResult.className = 'iq-test-result error';
        iqTestResult.textContent = `❌ ${data.message}`;
        iqTestResult.style.display = 'block';

        logToTerminal(`Error en login IQ Option: ${data.message}`, 'error');
      }
    } catch (err) {
      iqStatusBadge.className = 'status-badge-iq error';
      iqStatusBadge.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Error Servidor';
      iqTestResult.className = 'iq-test-result error';
      iqTestResult.textContent = `Error de comunicación: ${err.message}`;
      iqTestResult.style.display = 'block';
    } finally {
      btnTestIq.disabled = false;
      btnTestIqText.textContent = 'Probar Conexión';
    }
  });

  // ==========================================
  // WEBSOCKET REALTIME CONNECTION
  // ==========================================
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      logToTerminal("Conexión WebSocket establecida con el motor del bot.", "success");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        updateDashboard(data);
      } catch (err) {
        console.error("Error al procesar mensaje WebSocket:", err);
      }
    };

    ws.onclose = () => {
      logToTerminal("WebSocket desconectado. Reconectando en 3 segundos...", "warn");
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (err) => {
      console.error("Error en WebSocket:", err);
    };
  }

  // ==========================================
  // ACTUALIZACIÓN DEL DASHBOARD EN VIVO
  // ==========================================
  function updateDashboard(data) {
    isBotRunning = data.is_running;

    // Estado del botón y Hero
    if (isBotRunning) {
      heroCard.classList.add('bot-running');
      btnToggle.className = 'btn-power btn-stop';
      btnToggle.innerHTML = '<i class="fa-solid fa-stop"></i> <span id="btn-power-text">DETENER BOT</span>';
      statusTitleEl.textContent = "BOT ACTIVO & ESCANEANDO";
      statusTitleEl.style.color = "#00f59b";
      statusDescEl.textContent = data.status_message || "Escaneo en vivo segundo a segundo activo.";
    } else {
      heroCard.classList.remove('bot-running');
      btnToggle.className = 'btn-power btn-start glow-button';
      btnToggle.innerHTML = '<i class="fa-solid fa-play"></i> <span id="btn-power-text">ENCENDER BOT</span>';
      statusTitleEl.textContent = "BOT EN ESPERA";
      statusTitleEl.style.color = "#8e9bb0";
      statusDescEl.textContent = "Selecciona los pares a analizar y enciende el bot para iniciar el escaneo.";
    }

    // Cuenta y Saldo
    accountModeEl.textContent = data.account_type || "PRACTICE";
    if (data.is_simulation) {
      accountModeEl.textContent += " (DEMO)";
    }
    accountBalanceEl.textContent = `$${(data.balance || 0).toFixed(2)}`;

    // Radar Principal
    const tfLabel = data.timeframe === 60 ? "1M" : `${Math.floor(data.timeframe / 60)}M`;
    radarPairEl.textContent = `${data.pair} • ${tfLabel}`;
    radarPriceEl.textContent = (data.tick_price || 0).toFixed(5);
    
    // Cuenta regresiva
    const sec = data.seconds_left || 0;
    radarCountdownEl.textContent = `${sec}s`;
    const tf = data.timeframe || 60;
    const pct = Math.max(0, Math.min(100, (sec / tf) * 100));
    countdownProgressEl.style.width = `${pct}%`;

    // Pasos del ciclo
    stepSearch.classList.remove('active');
    stepConfirm.classList.remove('active');
    stepTrade.classList.remove('active');

    if (data.state === 'SEARCHING') {
      stepSearch.classList.add('active');
      cycleMsgEl.textContent = "Buscando cruce del Oscilador VIP en pares seleccionados...";
      cycleMsgEl.style.color = "#8e9bb0";
    } else if (data.state === 'CONFIRMING') {
      stepConfirm.classList.add('active');
      const sig = data.pending_signal ? data.pending_signal.direction : '';
      cycleMsgEl.textContent = `¡SEÑAL ${sig} EN ${data.pair}! Evaluando vela de confirmación...`;
      cycleMsgEl.style.color = sig === 'CALL' ? '#00f59b' : '#ff4757';
    } else if (data.state === 'IN_TRADE') {
      stepTrade.classList.add('active');
      const tr = data.current_trade ? `${data.current_trade.direction} $${data.current_trade.amount}` : '';
      cycleMsgEl.textContent = `Operación abierta a 1m en ${data.pair}: ${tr}`;
      cycleMsgEl.style.color = '#00d2ff';
    }

    // Renderizar Monitor Multi-Par
    if (data.pairs_overview && data.pairs_overview.length > 0) {
      renderMultiPairsGrid(data.pairs_overview, sec);
    }

    // Métricas de Sesión
    if (data.stats) {
      metricWinrate.textContent = `${data.stats.winrate}%`;
      const prof = data.stats.net_profit || 0;
      metricProfit.textContent = `${prof >= 0 ? '+' : ''}$${prof.toFixed(2)}`;
      metricProfit.style.color = prof >= 0 ? '#00f59b' : '#ff4757';
      metricWins.textContent = data.stats.wins || 0;
      metricLosses.textContent = data.stats.losses || 0;
    }

    // Tabla de Historial
    if (data.history && data.history.length > 0) {
      tableCount.textContent = `${data.history.length} operaciones`;
      let rowsHtml = '';
      data.history.slice().reverse().forEach(t => {
        const isWin = t.result === 'WIN';
        const isLoss = t.result === 'LOSS';
        const resClass = isWin ? 'pill-itm' : (isLoss ? 'pill-otm' : '');
        const resText = isWin ? 'ITM ✅' : (isLoss ? 'OTM ❌' : 'EMPATE');
        const dirClass = t.direction === 'CALL' ? 'pill-call' : 'pill-put';
        const profitSign = t.profit >= 0 ? '+' : '';

        rowsHtml += `
          <tr>
            <td>${t.entry_time}</td>
            <td><strong>${t.pair}</strong></td>
            <td><span class="pill-direction ${dirClass}">${t.direction}</span></td>
            <td>$${t.amount.toFixed(2)}</td>
            <td>${t.entry_price.toFixed(5)}</td>
            <td>${t.close_price.toFixed(5)}</td>
            <td class="${resClass}">${resText}</td>
            <td class="${resClass}">${profitSign}$${t.profit.toFixed(2)}</td>
          </tr>
        `;
      });
      tradesBody.innerHTML = rowsHtml;
    }
  }

  // ==========================================
  // RENDER CUADRÍCULA MULTI-PAR EN PARALELO
  // ==========================================
  function renderMultiPairsGrid(overviewList, secondsLeft) {
    let cardsHtml = '';
    overviewList.forEach(item => {
      let cardClass = 'multi-pair-card';
      let stateBadgeClass = 'mp-badge-searching';
      let stateText = 'Buscando';

      if (item.is_active) {
        cardClass += ' is-active-focused';
      }

      if (item.state === 'CONFIRMING') {
        cardClass += ' state-confirming';
        stateBadgeClass = 'mp-badge-confirming';
        stateText = 'Confirmando';
      } else if (item.state === 'IN_TRADE') {
        cardClass += ' state-in-trade';
        stateBadgeClass = 'mp-badge-trade';
        stateText = 'Operación 1M';
      }

      const signalBadge = item.signal ? 
        `<span class="mp-signal-tag mp-signal-${item.signal.toLowerCase()}">${item.signal}</span>` : '';

      cardsHtml += `
        <div class="${cardClass}" onclick="focusPair('${item.pair}')">
          <div class="mp-card-top">
            <span class="mp-symbol">${item.pair}</span>
            <span class="mp-badge-state ${stateBadgeClass}">${stateText}</span>
          </div>
          <div class="mp-price">${(item.tick_price || 0).toFixed(5)}</div>
          <div class="mp-card-bottom">
            <span>${signalBadge} ${item.status_msg || ''}</span>
            <span>${secondsLeft}s</span>
          </div>
        </div>
      `;
    });
    multiPairsGrid.innerHTML = cardsHtml;
  }

  // Enfocar par al hacer clic en su tarjeta
  window.focusPair = async function(pair) {
    try {
      await fetch('/api/pairs/focus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pair: pair })
      });
      logToTerminal(`Radar principal enfocado en: ${pair}`, 'info');
    } catch (e) {
      console.error(e);
    }
  };

  // ==========================================
  // BOT POWER SWITCH TOGGLE
  // ==========================================
  btnToggle.addEventListener('click', async () => {
    // Si se va a encender el bot, validar que al menos 1 par esté seleccionado
    if (!isBotRunning) {
      const count = updateCheckboxUI();
      if (count === 0) {
        alert("⚠️ ATENCIÓN: Debes seleccionar al menos un par con el check antes de encender el bot.");
        return;
      }
    }

    btnToggle.disabled = true;
    const endpoint = isBotRunning ? '/api/bot/stop' : '/api/bot/start';
    try {
      const resp = await fetch(endpoint, { method: 'POST' });
      const result = await resp.json();
      logToTerminal(result.message, result.success ? 'success' : 'error');
    } catch (e) {
      logToTerminal(`Error al cambiar estado del bot: ${e}`, 'error');
    } finally {
      btnToggle.disabled = false;
    }
  });

  // ==========================================
  // GUARDAR CONFIGURACIÓN DE PARÁMETROS
  // ==========================================
  configForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const selected = [];
    chkPairs.forEach(chk => {
      if (chk.checked) selected.push(chk.value);
    });

    const payload = {
      pairs: selected,
      timeframe: parseInt(cfgTimeframe.value),
      amount: parseFloat(cfgAmount.value),
      martingale: parseInt(cfgMartingale.value),
      account_type: cfgAccount.value,
      iq_email: testEmail.value.trim(),
      iq_pass: testPass.value.trim()
    };

    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      logToTerminal(data.message, data.success ? 'success' : 'warn');
    } catch (err) {
      logToTerminal(`Error guardando parámetros: ${err}`, 'error');
    }
  });

  // Iniciar WebSocket
  connectWebSocket();
});
