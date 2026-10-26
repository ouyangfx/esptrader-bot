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

class Mt5ValidateModel(BaseModel):
    license_key: str
    account: Optional[str] = ""
    terminal: Optional[str] = ""

class CreateLicenseModel(BaseModel):
    client_name: str
    account_mt5: Optional[str] = ""
    days_valid: Optional[int] = 30
    notes: Optional[str] = ""

class LicenseActionModel(BaseModel):
    id: int
    days: Optional[int] = 30

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
# ENDPOINTS MT5 OTC FEED & LICENCIAS
# =========================================================

OTC_SYMBOLS_MAP = {
    "EURUSD-OTC": "EURUSD_OTC",
    "GBPUSD-OTC": "GBPUSD_OTC",
    "USDJPY-OTC": "USDJPY_OTC",
    "EURJPY-OTC": "EURJPY_OTC",
    "AUDUSD-OTC": "AUDUSD_OTC",
    "USDCAD-OTC": "USDCAD_OTC",
    "USDCHF-OTC": "USDCHF_OTC",
    "NZDUSD-OTC": "NZDUSD_OTC",
    "EURGBP-OTC": "EURGBP_OTC",
    "GBPJPY-OTC": "GBPJPY_OTC"
}

@router.post("/api/mt5/license/validate")
@router.get("/api/mt5/license/validate")
async def api_mt5_validate_license(request: Request, license_key: Optional[str] = None, account: Optional[str] = ""):
    """Valida la clave de licencia enviada desde MT5."""
    key = license_key
    acc = account
    if request.method == "POST":
        try:
            body = await request.json()
            key = body.get("license_key", key)
            acc = body.get("account", acc)
        except Exception:
            pass
    
    if not key:
        raise HTTPException(status_code=400, detail="Falta el parámetro 'license_key'.")

    lic_mgr = request.app.state.license_manager
    client_ip = request.client.host if request.client else ""
    valid, msg, lic_data = lic_mgr.validate_license(key, acc or "", client_ip)

    if not valid:
        return JSONResponse(
            status_code=403,
            content={
                "success": False,
                "valid": False,
                "message": msg
            }
        )

    return {
        "success": True,
        "valid": True,
        "message": msg,
        "client_name": lic_data.get("client_name", ""),
        "account_mt5": lic_data.get("account_mt5", ""),
        "expires_at": lic_data.get("expires_at", ""),
        "otc_symbols": list(OTC_SYMBOLS_MAP.values())
    }

@router.get("/api/mt5/feed/otc")
async def api_mt5_otc_feed(request: Request, license_key: str, symbol: Optional[str] = None, include_candles: Optional[bool] = False):
    """
    Entrega data en tiempo real de alta velocidad y velas M1/M30 para MetaTrader 5 de los 10 pares OTC.
    Requiere licencia activa y no expirada.
    """
    lic_mgr = request.app.state.license_manager
    client_ip = request.client.host if request.client else ""
    valid, msg, lic_data = lic_mgr.validate_license(license_key, "", client_ip)

    if not valid:
        return JSONResponse(status_code=403, content={"success": False, "error": msg})

    engine = request.app.state.engine
    iq = request.app.state.iq_client
    server_ts = iq.get_server_timestamp()

    inv_map = {v: k for k, v in OTC_SYMBOLS_MAP.items()}
    if symbol and symbol.upper() in inv_map:
        targets = [inv_map[symbol.upper()]]
    else:
        targets = list(OTC_SYMBOLS_MAP.keys())

    feed_data = {}
    for iq_pair in targets:
        mt5_sym = OTC_SYMBOLS_MAP.get(iq_pair, iq_pair)
        price = iq.get_realtime_price(iq_pair, 60)
        spread = 0.02 if "JPY" in iq_pair else 0.0001
        
        pair_dict = {
            "symbol": mt5_sym,
            "bid": round(price, 5 if "JPY" not in iq_pair else 3),
            "ask": round(price + spread, 5 if "JPY" not in iq_pair else 3),
            "last": round(price, 5 if "JPY" not in iq_pair else 3),
            "time": server_ts
        }

        # Solo incluir velas completas si se solicita explícitamente (ej. carga inicial)
        if include_candles:
            m1_raw = iq.get_candles(iq_pair, 60, 20)
            pair_dict["m1_candles"] = [{
                "time": int(c["from"]),
                "open": float(c["open"]),
                "high": float(c["max"]),
                "low": float(c["min"]),
                "close": float(c["close"]),
                "vol": int(c.get("volume", 10))
            } for c in m1_raw]

            m30_raw = iq.get_candles(iq_pair, 1800, 15)
            pair_dict["m30_candles"] = [{
                "time": int(c["from"]),
                "open": float(c["open"]),
                "high": float(c["max"]),
                "low": float(c["min"]),
                "close": float(c["close"]),
                "vol": int(c.get("volume", 50))
            } for c in m30_raw]

        feed_data[mt5_sym] = pair_dict

    return {
        "success": True,
        "timestamp": server_ts,
        "client": lic_data.get("client_name", ""),
        "pairs_count": len(feed_data),
        "data": feed_data
    }

# =========================================================
# ADMINISTRACIÓN DE LICENCIAS (PANEL WEB ADMIN)
# =========================================================

@router.get("/api/licenses")
async def api_list_licenses(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    lic_mgr = request.app.state.license_manager
    return {"success": True, "licenses": lic_mgr.list_licenses()}

@router.post("/api/licenses/create")
async def api_create_license(data: CreateLicenseModel, request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    lic_mgr = request.app.state.license_manager
    new_lic = lic_mgr.create_license(
        client_name=data.client_name,
        account_mt5=data.account_mt5 or "",
        days_valid=data.days_valid or 30,
        notes=data.notes or ""
    )
    return {"success": True, "license": new_lic}

@router.post("/api/licenses/toggle")
async def api_toggle_license(data: LicenseActionModel, request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    lic_mgr = request.app.state.license_manager
    ok, new_status = lic_mgr.toggle_status(data.id)
    return {"success": ok, "status": new_status}

@router.post("/api/licenses/delete")
async def api_delete_license(data: LicenseActionModel, request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    lic_mgr = request.app.state.license_manager
    ok = lic_mgr.delete_license(data.id)
    return {"success": ok}

@router.post("/api/licenses/extend")
async def api_extend_license(data: LicenseActionModel, request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="No autorizado")
    lic_mgr = request.app.state.license_manager
    ok, new_exp = lic_mgr.extend_license(data.id, data.days or 30)
    return {"success": ok, "expires_at": new_exp}

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
