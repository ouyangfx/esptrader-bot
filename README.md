# 🚀 ESPTRADER VIP - Bot de Trading Algorítmico IQ Option

Sistema cuantitativo automatizado para **IQ Option** basado en el script institucional **"SCRIPT VIP"**, con análisis dinámico en **1M y 5M**, operaciones binarias a **1 minuto de expiración**, confirmación de vela a favor, monitoreo de ticks segundo a segundo, panel de administración con login y página principal estilo **Linktree** con branding de **Trader 4 Less**.

---

## 📌 Características Principales

- **Algoritmo SCRIPT VIP (Traducción Lua a Python)**:
  - Oscilador con $SMA(1)$ y $SMA(34)$ (`buffer1`).
  - Media móvil ponderada $WMA(5)$ como señal (`buffer2`).
  - Cruces cuantitativos para señales de **COMPRA (CALL)** y **VENTA (PUT)**.
  - Detección de fractales de 5 velas (High/Low) y niveles de soporte/resistencia dinámicos ($HH10, LL10 \dots HH200, LL200$).
- **Filtro de Confirmación Inteligente (Solicitado por el Trader)**:
  1. **Detección de Señal**: Cuando el oscilador cruza, se emite la alerta preliminar en el cierre de la vela.
  2. **Vela Confirmatoria**: El bot espera y evalúa la vela siguiente. La vela debe cerrar obligatoriamente a favor de la dirección (verde para CALL, roja para PUT).
  3. **Entrada al Segundo 00**: Si confirma, ejecuta la orden en el segundo exacto `00` de apertura de la siguiente vela a expiración de **1 minuto**. Si no confirma, cancela la operación protegiendo el capital.
- **Monitoreo Segundo a Segundo**:
  - Sincronización en tiempo real con el servidor de IQ Option.
  - Cuenta regresiva de vela y ticks de precio en directo mediante WebSockets.
- **Canal de Telegram Oficial**:
  - Alertas automáticas con hora exacta de entrada, precio, importe, expiración, resultado (ITM / OTM) y hora exacta de cierre.
  - Conectado a **[@traderfxapp](https://t.me/traderfxapp)** | Admin: **[@ouyangfx](https://t.me/ouyangfx)**.
- **Panel Web de Administración (/admin)**:
  - Autenticación segura con usuario y contraseña.
  - Interruptor maestro para **Encender / Apagar el Bot** con 1 clic.
  - Radar en tiempo real segundo a segundo.
  - Selector de divisas (EURUSD, GBPUSD, USDJPY, EURJPY, etc.), Timeframe (1M / 5M), Gestión de Martingala y Saldo (Practice / Real).
  - Historial de operaciones en vivo y consola de logs.
- **Página de Inicio Estilo Linktree (/)**:
  - Diseño responsive y glassmorphism premium con el logotipo SVG extraído de **[trader4less.com](https://trader4less.com)**.
  - Accesos directos a Telegram, soporte, broker IQ Option y panel de control.

---

## 📁 Estructura del Repositorio

```text
ESPTRADER/
├── .env.example              # Plantilla de variables de entorno
├── .env                      # Configuración y credenciales locales
├── .gitignore                # Archivos ignorados por Git (seguridad)
├── requirements.txt          # Dependencias de Python
├── main.py                   # Punto de entrada principal (FastAPI + Uvicorn)
├── config.py                 # Gestor centralizado de configuración
├── core/
│   ├── indicator.py          # Algoritmo Script VIP (Lua a Python)
│   ├── iq_client.py          # Conector IQ Option con fallback seguro
│   ├── telegram_bot.py       # Notificaciones Telegram automáticas
│   └── trading_engine.py     # Motor de trading y ciclo segundo a segundo
├── web/
│   └── routes.py             # Rutas web, autenticación y WebSocket
├── templates/
│   ├── index.html            # Portal Linktree oficial
│   ├── login.html            # Acceso de administrador
│   └── dashboard.html        # Panel de control en vivo
└── static/
    ├── css/style.css         # Estilos dark-theme institucional
    ├── js/dashboard.js       # Cliente WebSocket en tiempo real
    └── assets/images/        # Logo y favicon de Trader 4 Less
```

---

## ⚙️ Configuración e Instalación

### 1. Requisitos Previos
- Python 3.10 o superior instalado.
- Cuenta en IQ Option.

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno (`.env`)
Edita el archivo `.env` o copia desde `.env.example`:

```ini
# IQ OPTION CREDENTIALS
IQ_EMAIL=tu_correo_iqoption@gmail.com
IQ_PASSWORD=tu_password_iqoption
IQ_ACCOUNT_TYPE=PRACTICE # o REAL

# CONFIGURACIÓN DE OPERACIÓN
TRADING_PAIRS=EURUSD,GBPUSD,USDJPY,EURJPY
TIMEFRAME=60             # 60 para 1M, 300 para 5M
EXPIRATION_TIME=1       # 1 minuto
TRADE_AMOUNT=2.0        # Importe base en USD
MARTINGALE_STEPS=1      # 0 desactivado, 1 o 2 pasos
MARTINGALE_MULTIPLIER=2.2

# TELEGRAM
TELEGRAM_BOT_TOKEN=8548283354:AAEn6xmBRFOn-pwRxT3pSYClbVQerzrKqAM
TELEGRAM_CHAT_ID=@traderfxapp
TELEGRAM_ADMIN_USER=ouyangfx

# PANEL WEB ADMIN
ADMIN_USER=admin
ADMIN_PASS=TraderVIP2026!
PORT=8000
```

---

## 🚀 Ejecución del Sistema

Para iniciar el servidor y el bot:
```bash
python main.py
```
*(O en Windows usando `py main.py`)*

### Accesos Disponibles:
- **Portal Linktree**: [http://localhost:8000/](http://localhost:8000/)
- **Panel de Control**: [http://localhost:8000/admin](http://localhost:8000/admin)
  - **Usuario por defecto**: `admin`
  - **Contraseña por defecto**: `TraderVIP2026!`

---

## 🔄 Conexión con GitHub

Para subir este proyecto a un nuevo repositorio de GitHub:

1. Iniciar git en la carpeta:
```bash
git init
git add .
git commit -m "feat: initial commit - ESPTrader VIP Bot with IQOption and Telegram"
```

2. Vincular el repositorio remoto:
```bash
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

---

## 🛡 Descargo de Responsabilidad (Disclaimer)
El trading en opciones binarias y Forex conlleva un alto nivel de riesgo. Este software es una herramienta cuantitativa para automatización y análisis. El usuario es responsable de la gestión de capital y el uso de su cuenta.
