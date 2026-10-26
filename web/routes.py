"""
Rutas Web y API con FastAPI
Incluye Portal Linktree, Autenticación de Admin, Panel de Control y WebSocket en vivo.
"""

from fastapi import APIRouter, Request, Response, Form, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import secrets

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Sesiones en memoria activas
active_sessions = set()

class ConfigUpdateModel(BaseModel):
    pair: str
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
    
    engine.update_config(
        pair=data.pair,
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
