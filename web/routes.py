"""
Rutas Web y API con FastAPI
Incluye Portal Linktree, Autenticación de Admin, Panel de Control,
Prueba de Conexión IQ Option, Selección Multi-Par y WebSocket en vivo.
"""

from fastapi import APIRouter, Request, Response, Form, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
import os
import asyncio
import secrets
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Sesiones en memoria activas
active_sessions = set()

def save_env_vars(updates: dict):
    """Guarda variables de entorno en .env preservando el resto de líneas."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    updated_keys = set()
    new_lines = []
    for line in lines:
        matched = False
        for k, v in updates.items():
            if line.startswith(f"{k}="):
                new_lines.append(f"{k}={v}\n")
                updated_keys.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)
            
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

class IqTestModel(BaseModel):
    email: str
    password: str
    account_type: str = "PRACTICE"

class IqSaveModel(BaseModel):
    email: str
    password: str
    account_type: str = "PRACTICE"

class PairsSaveModel(BaseModel):
    pairs: List[str]

class ParamsSaveModel(BaseModel):
    timeframe: int = 300
    amount: float = 2.0
    martingale: int = 0
    martingale_multiplier: float = 1.0
    stop_loss: Optional[float] = 20.0
    take_profit: Optional[float] = 50.0
    account_type: Optional[str] = "PRACTICE"

class PairsUpdateModel(BaseModel):
    pairs: List[str]

class SetFocusPairModel(BaseModel):
    pair: str

class ConfigUpdateModel(BaseModel):
    pairs: Optional[List[str]] = None
    pair: Optional[str] = "EURUSD"
    timeframe: int
    amount: float
    martingale: int
    account_type: str
    iq_email: Optional[str] = None
    iq_pass: Optional[str] = None

def is_authenticated(request: Request) -> bool:
    token = request.cookies.get("admin_session")
    return token in active_sessions

@router.get("/", response_class=HTMLResponse)
@router.get("/signals", response_class=HTMLResponse)
@router.get("/senales", response_class=HTMLResponse)
async def signals_page(request: Request):
    """Portada principal con Gráfico TradingView en Vivo, Señales VIP y niveles de Fibonacci"""
    engine = request.app.state.engine
    return templates.TemplateResponse(
        request=request,
        name="signals.html",
        context={"engine": engine}
    )

@router.get("/embed", response_class=HTMLResponse)
@router.get("/widget", response_class=HTMLResponse)
async def embed_widget_page(request: Request):
    """Widget incrustable en cualquier página web o archivo PHP."""
    engine = request.app.state.engine
    return templates.TemplateResponse(
        request=request,
        name="embed.html",
        context={"engine": engine}
    )

@router.get("/portal", response_class=HTMLResponse)
@router.get("/links", response_class=HTMLResponse)
async def portal_page(request: Request):
    """Portal Linktree secundario"""
    return templates.TemplateResponse(request=request, name="index.html")

@router.get("/api/signals/live")
async def api_signals_live(request: Request):
    """Retorna el estado de la señal activa y estadísticas para consumo público"""
    engine = request.app.state.engine
    return {
        "is_running": engine.is_running,
        "engine_mode": engine.engine_mode,
        "locked_pair": engine.locked_pair,
        "pending_signal": engine.pending_signal,
        "current_trade": engine.current_trade,
        "last_signal_event": engine.last_signal_event,
        "live_signals_feed": engine.live_signals_feed[-10:],
        "stats": engine.session_stats,
        "history": engine.trade_history[-10:]
    }

@router.get("/api/candles")
async def api_get_candles(request: Request, pair: str = "EURUSD-OTC", timeframe: int = 300, count: int = 150):
    """
    Retorna el historial de velas M5 actualizadas del último día y los marcadores de señales calculados para TradingView Lightweight Charts
    """
    engine = request.app.state.engine
    candles = await asyncio.to_thread(engine.iq.get_candles, pair, timeframe, count)
    if not candles:
        return {"pair": pair, "timeframe": timeframe, "candles": [], "markers": [], "fibo": None}

    formatted_candles = []
    markers = []
    indicator = engine.indicator

    seen_times = set()
    for i in range(len(candles)):
        c = candles[i]
        c_time = int(c.get('from', 0))
        if c_time in seen_times:
            continue
        seen_times.add(c_time)

        formatted_candles.append({
            "time": c_time,
            "open": float(c['open']),
            "high": float(c.get('max', c.get('high', c['close']))),
            "low": float(c.get('min', c.get('low', c['close']))),
            "close": float(c['close']),
            "volume": int(c.get('volume', 0))
        })

        # Marcadores de señales del indicador sobre velas históricas
        if i >= 35:
            sub = candles[:i]
            res = indicator.analyze_candles(sub)
            sig = res.get('signal')
            if sig == "CALL":
                markers.append({
                    "time": c_time,
                    "position": "belowBar",
                    "color": "#00f59b",
                    "shape": "arrowUp",
                    "text": "CALL 5M"
                })
            elif sig == "PUT":
                markers.append({
                    "time": c_time,
                    "position": "aboveBar",
                    "color": "#ff4757",
                    "shape": "arrowDown",
                    "text": "PUT 5M"
                })

    # Datos de Fibonacci activos si aplican a este par
    fibo_data = None
    if engine.current_trade and engine.current_trade.get("pair") == pair:
        fibo_data = {
            "fibo_50": engine.current_trade.get("fibo_50"),
            "fibo_618": engine.current_trade.get("fibo_618"),
            "direction": engine.current_trade.get("direction"),
            "entry_price": engine.current_trade.get("entry_price"),
            "state": "IN_TRADE"
        }
    elif engine.pending_signal and engine.pending_signal.get("pair") == pair:
        fibo_data = {
            "fibo_50": engine.pending_signal.get("fibo_50"),
            "fibo_618": engine.pending_signal.get("fibo_618"),
            "direction": engine.pending_signal.get("direction"),
            "entry_price": float(candles[-1]['close']) if candles else 0.0,
            "state": "CONFIRMING"
        }
    elif engine.last_signal_event and engine.last_signal_event.get("pair") == pair:
        fibo_data = {
            "fibo_50": engine.last_signal_event.get("fibo_50"),
            "fibo_618": engine.last_signal_event.get("fibo_618"),
            "direction": engine.last_signal_event.get("direction"),
            "entry_price": engine.last_signal_event.get("entry_price"),
            "state": engine.last_signal_event.get("status")
        }
    else:
        for sig in reversed(engine.live_signals_feed):
            if sig.get("pair") == pair and sig.get("fibo_50"):
                fibo_data = {
                    "fibo_50": sig.get("fibo_50"),
                    "fibo_618": sig.get("fibo_618"),
                    "direction": sig.get("direction"),
                    "entry_price": sig.get("entry_price"),
                    "state": sig.get("status")
                }
                break

    p_st = engine.pairs_state.get(pair, {})
    curr_tick = p_st.get("tick_price") if p_st and p_st.get("tick_price", 0) > 0 else (formatted_candles[-1]['close'] if formatted_candles else 0.0)

    return {
        "pair": pair,
        "timeframe": timeframe,
        "candles": formatted_candles,
        "markers": markers,
        "fibo": fibo_data,
        "current_tick": curr_tick
    }

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@router.post("/login")
async def login_action(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...)
):
    config = request.app.state.config
    if username == config.ADMIN_USER and password == config.ADMIN_PASS:
        session_token = secrets.token_hex(24)
        active_sessions.add(session_token)
        resp = RedirectResponse(url="/admin", status_code=302)
        resp.set_cookie(key="admin_session", value=session_token, httponly=True, max_age=86400 * 7)
        return resp
    else:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Credenciales inválidas. Revisa usuario y contraseña."},
            status_code=401
        )

@router.get("/logout")
async def logout_action():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("admin_session")
    return resp

@router.get("/admin", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    
    engine = request.app.state.engine
    config = request.app.state.config
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "config": config,
            "engine": engine
        }
    )

# =========================================================
# ENDPOINTS API DEL BOT
# =========================================================

@router.post("/api/bot/start")
async def api_start_bot(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    success, msg = engine.start()
    if success:
        asyncio.create_task(engine.broadcast_status())
    return {"success": success, "message": msg, "is_running": engine.is_running}

@router.post("/api/bot/stop")
async def api_stop_bot(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    success, msg = engine.stop()
    if success:
        asyncio.create_task(engine.broadcast_status())
    return {"success": success, "message": msg, "is_running": engine.is_running}

@router.post("/api/iq/test-connection")
async def api_test_iq_connection(data: IqTestModel, request: Request):
    """Prueba la conexión a IQ Option con las credenciales ingresadas."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    result = engine.iq.test_connection(data.email, data.password, data.account_type)
    return result

@router.post("/api/iq/save")
async def api_save_iq(data: IqSaveModel, request: Request):
    """Guarda las credenciales de IQ Option en .env y actualiza el cliente activo."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    
    email = data.email.strip()
    password = data.password.strip()
    account_type = data.account_type.upper()
    
    if not email or not password:
        return {"success": False, "message": "Debes ingresar correo y contraseña válidos."}
        
    save_env_vars({
        "IQ_EMAIL": email,
        "IQ_PASSWORD": password,
        "IQ_ACCOUNT_TYPE": account_type
    })
    
    engine.iq.email = email
    engine.iq.password = password
    engine.iq.change_balance(account_type)
    
    # Probar conexión al guardar
    test_res = engine.iq.test_connection(email, password, account_type)
    if test_res.get("success"):
        engine.iq.connect()
        return {
            "success": True, 
            "message": f"Credenciales guardadas y conexión exitosa ({account_type}). Saldo: ${test_res.get('balance', 0):.2f}",
            "balance": test_res.get("balance", 0.0),
            "account_type": account_type
        }
    else:
        return {
            "success": True, 
            "message": f"Credenciales guardadas en .env. (Aviso de conexión: {test_res.get('message')})",
            "balance": 0.0,
            "account_type": account_type
        }

@router.post("/api/pairs/save")
async def api_save_pairs(data: PairsSaveModel, request: Request):
    """Guarda los pares seleccionados (4 Normales y 4 OTC) en .env y en el motor."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    config = request.app.state.config
    
    allowed = set(config.ALL_AVAILABLE_PAIRS)
    cleaned = [p.strip().upper() for p in data.pairs if p.strip() and p.strip().upper() in allowed]
    
    if not cleaned:
        return {"success": False, "message": "Debes seleccionar al menos un par principal válido (Normal o OTC)."}
        
    success, msg = engine.set_selected_pairs(cleaned)
    if success:
        save_env_vars({
            "TRADING_PAIRS": ",".join(cleaned)
        })
    return {"success": success, "message": msg, "selected_pairs": engine.selected_pairs}

@router.post("/api/params/save")
async def api_save_params(data: ParamsSaveModel, request: Request):
    """Guarda los parámetros de trading y gestión de riesgo en .env y en el motor."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    
    amt = float(data.amount)
    sl = float(data.stop_loss or 20.0)
    tp = float(data.take_profit or 50.0)
    acc = str(data.account_type or "PRACTICE").upper()
    
    # Velas de 5 Minutos (M5) y Sin Martingala estrictos
    save_env_vars({
        "TIMEFRAME": "300",
        "EXPIRATION_TIME": "5",
        "TRADE_AMOUNT": str(amt),
        "MARTINGALE_STEPS": "0",
        "MARTINGALE_MULTIPLIER": "1.0",
        "STOP_LOSS": str(sl),
        "TAKE_PROFIT": str(tp),
        "IQ_ACCOUNT_TYPE": acc
    })
    
    engine.timeframe = 300
    engine.expiration = 5
    engine.base_amount = amt
    engine.current_amount = amt
    engine.martingale_steps = 0
    engine.martingale_multiplier = 1.0
    if acc != engine.iq.account_type:
        engine.iq.change_balance(acc)
        
    return {"success": True, "message": f"Configuración guardada: Velas de 5 Minutos (M5), Expiración 5m, Operativa fija sin Martingala."}

@router.post("/api/pairs/update")
async def api_update_pairs(data: PairsUpdateModel, request: Request):
    """Actualiza la lista de pares que se analizarán en simultáneo."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    success, msg = engine.set_selected_pairs(data.pairs)
    return {"success": success, "message": msg, "selected_pairs": engine.selected_pairs}

@router.post("/api/pairs/focus")
async def api_focus_pair(data: SetFocusPairModel, request: Request):
    """Enfoca el radar principal en un par específico."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    engine.set_active_pair(data.pair)
    return {"success": True, "active_pair": engine.active_pair}

@router.post("/api/config")
async def api_update_config(data: ConfigUpdateModel, request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    
    engine = request.app.state.engine
    
    # Actualizar credenciales si se proveyeron
    if data.iq_email and data.iq_email.strip() and data.iq_pass and data.iq_pass.strip():
        engine.iq.email = data.iq_email.strip()
        engine.iq.password = data.iq_pass.strip()
        engine.iq.connect()
    
    pairs_list = data.pairs if data.pairs else ([data.pair] if data.pair else engine.selected_pairs)
    engine.update_config(
        pairs=pairs_list,
        timeframe=data.timeframe,
        amount=data.amount,
        martingale=data.martingale,
        account_type=data.account_type
    )
    return {"success": True, "message": "Parámetros actualizados y aplicados en tiempo real."}

# =========================================================
# WEBSOCKET STREAMING SEGUNDO A SEGUNDO
# =========================================================

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    engine = websocket.app.state.engine
    engine.websocket_listeners.add(websocket)
    try:
        while True:
            # Mantener conexión viva recibiendo cualquier ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        engine.websocket_listeners.discard(websocket)
    except Exception:
        engine.websocket_listeners.discard(websocket)
