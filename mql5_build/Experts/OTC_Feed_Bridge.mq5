//+------------------------------------------------------------------+
//|                                             OTC_Feed_Bridge.mq5  |
//|                             Trader 4 Less - VIP Algorithm System |
//|                                         https://tradingsnr.info  |
//+------------------------------------------------------------------+
#property copyright "Trader 4 Less VIP"
#property link      "https://tradingsnr.info"
#property version   "1.00"
#property description "Puente de Datos IQ Option OTC hacia MetaTrader 5"
#property description "Crea y actualiza los 10 pares OTC en tiempo real"

#include <Trade\Trade.mqh>

//--- Entradas de Configuración
input group "=== CREDENCIALES & LICENCIA ==="
input string   InpServerUrl    = "https://tradingsnr.info"; // Servidor VPS
input string   InpLicenseKey   = "VIP-MASTER-2026-KEY";     // Clave de Licencia VIP
input int      InpTimerMs      = 500;                       // Intervalo Actualización (ms)

//--- Lista de los 10 Pares OTC Oficiales
const string OTC_PAIRS[10] = {
   "EURUSD_OTC", "GBPUSD_OTC", "USDJPY_OTC", "EURJPY_OTC", "AUDUSD_OTC",
   "USDCAD_OTC", "USDCHF_OTC", "NZDUSD_OTC", "EURGBP_OTC", "GBPJPY_OTC"
};

//--- Variables Globales de Estado
bool   g_license_valid = false;
string g_client_name   = "";
string g_expires_at    = "";
datetime g_last_check  = 0;
ulong  g_ticks_count   = 0;

//+------------------------------------------------------------------+
//| Inicialización del Expert Advisor                                |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== Iniciando OTC Feed Bridge para MetaTrader 5 ===");
   
   // 1. Validar Licencia con el Servidor VPS
   if(!ValidateLicense())
   {
      DrawHUD("❌ LICENCIA DENEGADA", clrRed, "Contacta al Administrador");
      return(INIT_FAILED);
   }

   // 2. Crear los 10 Símbolos Personalizados OTC si no existen
   CreateCustomOTCSymbols();

   // 3. Inicializar Timer de alta frecuencia
   EventSetMillisecondTimer(InpTimerMs);

   // 4. Dibujar Panel Informativo
   DrawHUD("🟢 CONECTADO AL VPS", clrSpringGreen, "10 Pares OTC en Streaming");

   Print("OTC Feed Bridge iniciado con éxito. Licencia activa para: ", g_client_name);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Desinicialización                                                |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, "OTC_HUD_");
   Print("OTC Feed Bridge detenido.");
}

//+------------------------------------------------------------------+
//| Evento Timer de Alta Frecuencia (Streaming de Ticks & Velas)     |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Reverificar licencia cada 20 minutos
   if(TimeCurrent() - g_last_check > 1200)
   {
      if(!ValidateLicense())
      {
         EventKillTimer();
         Alert("⚠️ Tu licencia ha expirado o fue revocada.");
         DrawHUD("❌ LICENCIA EXPIRADA", clrRed, "Acceso bloqueado");
         return;
      }
      g_last_check = TimeCurrent();
   }

   // Solicitar datos OTC al VPS
   FetchAndFeedOTCData();
}

//+------------------------------------------------------------------+
//| Valida la Licencia mediante WebRequest con reintentos            |
//+------------------------------------------------------------------+
bool ValidateLicense()
{
   string url = InpServerUrl + "/api/mt5/license/validate?license_key=" + InpLicenseKey + "&account=" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   char post_data[];
   char result[];
   string result_headers;
   string headers = "User-Agent: MT5-Bridge/2026\r\nContent-Type: application/json\r\n";

   int max_retries = 3;
   int last_err = 0;
   int http_code = 0;

   for(int attempt = 1; attempt <= max_retries; attempt++)
   {
      ResetLastError();
      http_code = WebRequest("GET", url, headers, 12000, post_data, result, result_headers);
      last_err = GetLastError();

      if(http_code == 200)
         break;

      if(attempt < max_retries)
      {
         PrintFormat("Intento %d de validación falló (HTTP: %d, Err: %d). Reintentando en 1.5s...", attempt, http_code, last_err);
         Sleep(1500);
      }
   }

   if(http_code == -1)
   {
      Print("Error en WebRequest: ", last_err);
      if(last_err == 4060)
      {
         Alert("⚠️ ERROR MT5 (Código 4060): La URL '" + InpServerUrl + "' no está permitida para WebRequest.\nPor favor ve en MT5 a: Herramientas -> Opciones -> Asesores Expertos y agrega '" + InpServerUrl + "' a la lista.");
      }
      else
      {
         Alert("⚠️ Error de conexión con el VPS (Código " + IntegerToString(last_err) + "). Verifica tu conexión a internet o el estado del VPS.");
      }
      return false;
   }

   string response = CharArrayToString(result);
   if(http_code == 200 && (StringFind(response, "\"valid\":true") >= 0 || StringFind(response, "\"success\":true") >= 0))
   {
      g_license_valid = true;
      // Extraer nombre de cliente si existe
      int namePos = StringFind(response, "\"client_name\":\"");
      if(namePos >= 0)
      {
         int endPos = StringFind(response, "\"", namePos + 15);
         if(endPos > namePos)
            g_client_name = StringSubstr(response, namePos + 15, endPos - (namePos + 15));
      }
      
      // Registrar variables globales para que los indicadores las lean al instante
      long my_acc = AccountInfoInteger(ACCOUNT_LOGIN);
      GlobalVariableSet("OTC_VIP_LICENSE_ACTIVE", 1.0);
      GlobalVariableSet("OTC_VIP_LICENSE_ACCOUNT", (double)my_acc);
      GlobalVariableSet("OTC_VIP_LICENSE_TS", (double)TimeCurrent());

      // Guardar token en archivo compartido FILE_COMMON
      int f = FileOpen("otc_vip_license.txt", FILE_WRITE | FILE_TXT | FILE_COMMON);
      if(f != INVALID_HANDLE)
      {
         FileWriteString(f, IntegerToString(my_acc) + "|" + InpLicenseKey + "|" + g_client_name + "|" + IntegerToString((long)(TimeCurrent() + 86400 * 30)));
         FileClose(f);
      }

      Print("Licencia validada exitosamente para: ", g_client_name, " (Cuenta MT5: ", my_acc, ")");
      return true;
   }

   g_license_valid = false;
   Alert("❌ LICENCIA INVÁLIDA O EXPIRADA. La clave '" + InpLicenseKey + "' no está autorizada para la cuenta " + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ".\nContacta al Administrador @ouyangfx.");
   return false;
}

//+------------------------------------------------------------------+
//| Crea los 10 pares OTC como Custom Symbols en MT5                 |
//+------------------------------------------------------------------+
void CreateCustomOTCSymbols()
{
   for(int i = 0; i < 10; i++)
   {
      string sym = OTC_PAIRS[i];
      ResetLastError();

      // Verificar si ya existe
      if(!SymbolInfoInteger(sym, SYMBOL_CUSTOM))
      {
         if(CustomSymbolCreate(sym, "IQ_OTC", "Trader 4 Less OTC Market"))
         {
            int digits = (StringFind(sym, "JPY") >= 0) ? 3 : 5;
            double point = (digits == 3) ? 0.001 : 0.00001;

            CustomSymbolSetInteger(sym, SYMBOL_DIGITS, digits);
            CustomSymbolSetDouble(sym, SYMBOL_POINT, point);
            CustomSymbolSetInteger(sym, SYMBOL_TRADE_MODE, SYMBOL_TRADE_MODE_FULL);
            CustomSymbolSetInteger(sym, SYMBOL_SPREAD, 10);
            CustomSymbolSetString(sym, SYMBOL_CURRENCY_BASE, StringSubstr(sym, 0, 3));
            CustomSymbolSetString(sym, SYMBOL_CURRENCY_PROFIT, StringSubstr(sym, 3, 3));
            Print("Símbolo personalizado creado con éxito: ", sym);
         }
      }

      // Asegurar que esté visible en Observación de Mercado
      SymbolSelect(sym, true);
   }
}

//+------------------------------------------------------------------+
//| Obtiene los Ticks y Velas desde el VPS e inyecta en MT5          |
//+------------------------------------------------------------------+
void FetchAndFeedOTCData()
{
   string url = InpServerUrl + "/api/mt5/feed/otc?license_key=" + InpLicenseKey;
   char post_data[];
   char result[];
   string result_headers;

   int res = WebRequest("GET", url, "", 3000, post_data, result, result_headers);
   if(res != 200) return;

   string response = CharArrayToString(result);
   
   // Inyectar datos en cada uno de los 10 pares OTC
   for(int i = 0; i < 10; i++)
   {
      string sym = OTC_PAIRS[i];
      int symPos = StringFind(response, "\"" + sym + "\"");
      if(symPos < 0) continue;

      // Extraer bid y ask
      double bid = ExtractDoubleValue(response, symPos, "\"bid\":");
      double ask = ExtractDoubleValue(response, symPos, "\"ask\":");
      double last = ExtractDoubleValue(response, symPos, "\"last\":");

      if(bid > 0)
      {
         MqlTick ticks[1];
         ticks[0].time = TimeCurrent();
         ticks[0].bid = bid;
         ticks[0].ask = ask > 0 ? ask : bid;
         ticks[0].last = last > 0 ? last : bid;
         ticks[0].volume = 1;
         ticks[0].flags = TICK_FLAG_BID | TICK_FLAG_ASK | TICK_FLAG_LAST;

         CustomTicksAdd(sym, ticks, 1);
         g_ticks_count++;
      }

      // Inyectar velas M1 si están en el payload
      InjectCandlesFromJSON(response, symPos, sym);
   }

   // Actualizar HUD cada 50 ticks
   if(g_ticks_count % 30 == 0)
   {
      DrawHUD("🟢 EN STREAMING ACTIVO", clrSpringGreen, "Ticks recibidos: " + IntegerToString(g_ticks_count));
   }
}

//+------------------------------------------------------------------+
//| Extrae un número decimal desde JSON                              |
//+------------------------------------------------------------------+
double ExtractDoubleValue(const string &json, int startPos, const string &key)
{
   int kPos = StringFind(json, key, startPos);
   if(kPos < 0) return 0.0;
   int valStart = kPos + StringLen(key);
   int valEnd = valStart;
   while(valEnd < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, valEnd);
      if(ch == ',' || ch == '}' || ch == ']') break;
      valEnd++;
   }
   string sVal = StringSubstr(json, valStart, valEnd - valStart);
   StringTrimLeft(sVal);
   StringTrimRight(sVal);
   return StringToDouble(sVal);
}

//+------------------------------------------------------------------+
//| Parsea e inyecta velas M1 en el Custom Symbol                    |
//+------------------------------------------------------------------+
void InjectCandlesFromJSON(const string &json, int startPos, const string &sym)
{
   int cPos = StringFind(json, "\"m1_candles\":[", startPos);
   if(cPos < 0) return;

   int endArr = StringFind(json, "]", cPos);
   if(endArr < 0) return;

   string arrStr = StringSubstr(json, cPos, endArr - cPos);
   int curIdx = 0;

   MqlRates rates[25];
   int ratesCount = 0;

   while(ratesCount < 25)
   {
      int objStart = StringFind(arrStr, "{", curIdx);
      if(objStart < 0) break;
      int objEnd = StringFind(arrStr, "}", objStart);
      if(objEnd < 0) break;

      string obj = StringSubstr(arrStr, objStart, objEnd - objStart + 1);

      datetime c_time = (datetime)ExtractDoubleValue(obj, 0, "\"time\":");
      double c_open   = ExtractDoubleValue(obj, 0, "\"open\":");
      double c_high   = ExtractDoubleValue(obj, 0, "\"high\":");
      double c_low    = ExtractDoubleValue(obj, 0, "\"low\":");
      double c_close  = ExtractDoubleValue(obj, 0, "\"close\":");
      long   c_vol    = (long)ExtractDoubleValue(obj, 0, "\"vol\":");

      if(c_time > 0 && c_open > 0)
      {
         rates[ratesCount].time = c_time;
         rates[ratesCount].open = c_open;
         rates[ratesCount].high = c_high;
         rates[ratesCount].low  = c_low;
         rates[ratesCount].close = c_close;
         rates[ratesCount].tick_volume = c_vol > 0 ? c_vol : 10;
         rates[ratesCount].spread = 10;
         ratesCount++;
      }
      curIdx = objEnd + 1;
   }

   if(ratesCount > 0)
   {
      CustomRatesUpdate(sym, rates, ratesCount);
   }
}

//+------------------------------------------------------------------+
//| Dibuja el Panel Flotante en Pantalla                             |
//+------------------------------------------------------------------+
void DrawHUD(string statusText, color statusColor, string subtitle)
{
   string prefix = "OTC_HUD_";

   // Caja fondo
   if(ObjectFind(0, prefix + "BG") < 0)
   {
      ObjectCreate(0, prefix + "BG", OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XDISTANCE, 20);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YDISTANCE, 30);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XSIZE, 300);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YSIZE, 120);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BGCOLOR, C'12,18,28');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BORDER_COLOR, C'0,210,255');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   }

   // Título
   CreateOrUpdateLabel(prefix + "T1", 35, 42, "TRADER 4 LESS - OTC FEED BRIDGE", clrWhite, 9, true);
   CreateOrUpdateLabel(prefix + "T2", 35, 62, statusText, statusColor, 10, true);
   CreateOrUpdateLabel(prefix + "T3", 35, 84, "Licencia: " + (g_client_name != "" ? g_client_name : "Activa"), clrGold, 8, false);
   CreateOrUpdateLabel(prefix + "T4", 35, 104, subtitle, C'142,155,176', 8, false);
   CreateOrUpdateLabel(prefix + "T5", 35, 124, "Pares: 10 OTC activos en vivo", clrDodgerBlue, 8, false);

   ChartRedraw(0);
}

void CreateOrUpdateLabel(string name, int x, int y, string text, color clr, int fontSize, bool isBold)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetString(0, name, OBJPROP_FONT, "Outfit");
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
}
//+------------------------------------------------------------------+
