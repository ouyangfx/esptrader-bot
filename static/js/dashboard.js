// Dashboard JavaScript con WebSocket y control segundo a segundo

document.addEventListener('DOMContentLoaded', () => {
  // Elementos DOM
  const clockEl = document.getElementById('server-clock');
  const accountModeEl = document.getElementById('account-mode-text');
  const accountBalanceEl = document.getElementById('account-balance-text');
  
  const heroCard = document.querySelector('.bot-control-hero');
  const statusTitleEl = document.getElementById('status-title');
  const statusDescEl = document.getElementById('status-desc');
  const btnToggle = document.getElementById('btn-toggle-bot');
  const btnToggleText = document.getElementById('btn-power-text');
  
  const radarPairEl = document.getElementById('radar-pair-tag');
  const radarPriceEl = document.getElementById('radar-price');
  const radarCountdownEl = document.getElementById('radar-countdown');
  const countdownProgressEl = document.getElementById('countdown-progress');
  const cycleMsgEl = document.getElementById('cycle-msg');
  
  const stepSearch = document.getElementById('step-search');
  const stepConfirm = document.getElementById('step-confirm');
  const stepTrade = document.getElementById('step-trade');
  
  const metricWinrate = document.getElementById('metric-winrate');
  const metricProfit = document.getElementById('metric-profit');
  const metricWins = document.getElementById('metric-wins');
  const metricLosses = document.getElementById('metric-losses');
  
  const tradesBody = document.getElementById('trades-body');
  const tableCount = document.getElementById('table-count');
  const terminalLogs = document.getElementById('terminal-logs');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  
  const configForm = document.getElementById('form-config');
  const cfgPair = document.getElementById('cfg-pair');
  const cfgTimeframe = document.getElementById('cfg-timeframe');
  const cfgAmount = document.getElementById('cfg-amount');
  const cfgMartingale = document.getElementById('cfg-martingale');
  const cfgAccount = document.getElementById('cfg-account');
  const cfgEmail = document.getElementById('cfg-email');
  const cfgPass = document.getElementById('cfg-pass');

  let isBotRunning = false;
  let ws = null;

  // Actualizar reloj local cada segundo en caso de desconexión
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
      statusTitleEl.textContent = "BOT ACTIVO & MONITOREANDO";
      statusTitleEl.style.color = "#00f59b";
      statusDescEl.textContent = data.status_message || "Escaneo en vivo segundo a segundo activo.";
    } else {
      heroCard.classList.remove('bot-running');
      btnToggle.className = 'btn-power btn-start glow-button';
      btnToggle.innerHTML = '<i class="fa-solid fa-play"></i> <span id="btn-power-text">ENCENDER BOT</span>';
      statusTitleEl.textContent = "BOT DETENIDO";
      statusTitleEl.style.color = "#8e9bb0";
      statusDescEl.textContent = "Haz clic en Encender Bot para iniciar las operaciones.";
    }

    // Cuenta y Saldo
    accountModeEl.textContent = data.account_type || "PRACTICE";
    if (data.is_simulation) {
      accountModeEl.textContent += " (DEMO)";
    }
    accountBalanceEl.textContent = `$${(data.balance || 0).toFixed(2)}`;

    // Radar en Vivo
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
      cycleMsgEl.textContent = "Buscando cruce del Oscilador VIP...";
    } else if (data.state === 'CONFIRMING') {
      stepConfirm.classList.add('active');
      const sig = data.pending_signal ? data.pending_signal.direction : '';
      cycleMsgEl.textContent = `¡SEÑAL ${sig} DETECTADA! Evaluando si la vela actual confirma...`;
      cycleMsgEl.style.color = sig === 'CALL' ? '#00f59b' : '#ff4757';
    } else if (data.state === 'IN_TRADE') {
      stepTrade.classList.add('active');
      const tr = data.current_trade ? `${data.current_trade.direction} $${data.current_trade.amount}` : '';
      cycleMsgEl.textContent = `Operación abierta a 1m: ${tr}`;
      cycleMsgEl.style.color = '#00d2ff';
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
  // BOT POWER SWITCH TOGGLE
  // ==========================================
  btnToggle.addEventListener('click', async () => {
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
  // GUARDAR CONFIGURACIÓN
  // ==========================================
  configForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      pair: cfgPair.value,
      timeframe: parseInt(cfgTimeframe.value),
      amount: parseFloat(cfgAmount.value),
      martingale: parseInt(cfgMartingale.value),
      account_type: cfgAccount.value,
      iq_email: cfgEmail.value,
      iq_pass: cfgPass.value
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
      logToTerminal(`Error guardando configuración: ${err}`, 'error');
    }
  });

  // Iniciar WebSocket
  connectWebSocket();
});
