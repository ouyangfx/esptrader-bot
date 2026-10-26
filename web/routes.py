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
import secrets
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Sesiones en memoria activas
active_sessions = set()

class IqTestModel(BaseModel):
    email: str
    password: str
    account_type: str = "PRACTICE"

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
async def index_page(request: Request):
    """Página de inicio tipo Linktree con logo oficial de Trader 4 Less"""
    return templates.TemplateResponse(request=request, name="index.html")

@router.get("/signals", response_class=HTMLResponse)
@router.get("/senales", response_class=HTMLResponse)
async def signals_page(request: Request):
    """Sala de señales VIP pública en tiempo real con WebSocket"""
    engine = request.app.state.engine
    return templates.TemplateResponse(
        request=request,
        name="signals.html",
        context={"engine": engine}
    )

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
        "stats": engine.session_stats,
        "history": engine.trade_history[-20:]
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
    return {"success": success, "message": msg}

@router.post("/api/bot/stop")
async def api_stop_bot(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    success, msg = engine.stop()
    return {"success": success, "message": msg}

@router.post("/api/iq/test-connection")
async def api_test_iq_connection(data: IqTestModel, request: Request):
    """Prueba la conexión a IQ Option con las credenciales ingresadas."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    engine = request.app.state.engine
    result = engine.iq.test_connection(data.email, data.password, data.account_type)
    return result

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
