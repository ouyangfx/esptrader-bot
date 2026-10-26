//+------------------------------------------------------------------+
//|                                         Replica_Master_VIP.mq5   |
//|                             Trader 4 Less - VIP Algorithm System |
//|                                         https://tradingsnr.info  |
//+------------------------------------------------------------------+
#property copyright "Trader 4 Less VIP"
#property link      "https://tradingsnr.info"
#property version   "1.00"
#property description "Indicador de Réplicas M30 proyectadas en velas de M1"
#property description "Encajona el patrón histórico coincidente y emite señales de compra/venta"

#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

//--- Estilo de Plots (Flechas de Compra y Venta)
#property indicator_label1  "Compra (CALL)"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrSpringGreen
#property indicator_width1  3

#property indicator_label2  "Venta (PUT)"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrCrimson
#property indicator_width2  3

//--- Entradas de Configuración
input group "=== LICENCIA VIP ==="
input string   InpServerUrl       = "https://tradingsnr.info"; // Servidor VPS
input string   InpLicenseKey      = "VIP-MASTER-2026-KEY";     // Clave de Licencia VIP

input group "=== CONFIGURACIÓN DE RÉPLICAS ==="
input int      InpLookbackM30     = 50;           // Velas M30 a analizar en historial
input double   InpMinSimilarity   = 82.0;         // Mínimo % de Similitud (80-95%)
input color    InpColorBoxPast    = clrDodgerBlue;// Color Caja Réplica Pasado
input color    InpColorBoxCurrent = clrSpringGreen;// Color Caja Réplica Actual
input bool     InpShow50Level     = true;         // Mostrar Línea 50% de Equilibrio
input bool     InpAlertSound      = true;         // Alerta Sonora en Señal
input bool     InpPushNotification = false;       // Notificación Push a Móvil

//--- Buffers del Indicador
double BufferBuy[];
double BufferSell[];

//--- Variables Globales de Estado
bool     g_license_valid  = false;
string   g_client_name    = "";
datetime g_last_check     = 0;
datetime g_last_signal_time = 0;
double   g_last_similarity= 0.0;
string   g_last_direction = "BUSCANDO";

//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
int OnInit()
{
   // Mapeo de Buffers
   SetIndexBuffer(0, BufferBuy, INDICATOR_DATA);
   SetIndexBuffer(1, BufferSell, INDICATOR_DATA);

   PlotIndexSetInteger(0, PLOT_ARROW, 233); // Código flecha arriba
   PlotIndexSetInteger(1, PLOT_ARROW, 234); // Código flecha abajo

   ArraySetAsSeries(BufferBuy, true);
   ArraySetAsSeries(BufferSell, true);

   // Validar Licencia
   if(!ValidateLicense())
   {
      Print("Replica Master VIP: Esperando autenticación del EA OTC_Feed_Bridge...");
      DrawHUD("⚠️ ESPERANDO EA BRIDGE", clrYellow, 0.0, "Inicia OTC_Feed_Bridge");
      return(INIT_SUCCEEDED);
   }

   DrawHUD("🟢 LICENCIA VIP ACTIVA", clrSpringGreen, 0.0, "Buscando Réplicas M30...");
   Print("Indicador Replica Master VIP iniciado con éxito. Licencia para: ", g_client_name);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, "REP_");
   Print("Indicador Replica Master VIP removido.");
}

//+------------------------------------------------------------------+
//| Custom indicator iteration function                              |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < 50) return(0);

   // Verificar licencia periódicamente o si aún no estaba validada
   if(!g_license_valid || (TimeCurrent() - g_last_check > 300))
   {
      if(!ValidateLicense())
      {
         DrawHUD("⚠️ ESPERANDO EA BRIDGE", clrYellow, 0.0, "Inicia OTC_Feed_Bridge");
         return(0);
      }
      g_last_check = TimeCurrent();
      DrawHUD("🟢 LICENCIA VIP ACTIVA", clrSpringGreen, 0.0, "Buscando Réplicas M30...");
   }

   // 1. Obtener Velas de M30 para el análisis fractal
   MqlRates ratesM30[];
   ArraySetAsSeries(ratesM30, true);
   int copiedM30 = CopyRates(_Symbol, PERIOD_M30, 0, InpLookbackM30, ratesM30);
   if(copiedM30 < 4) return(rates_total);

   // 2. Extraer propiedades de la vela M30 actual (Índice 0 o 1)
   MqlRates currentM30 = ratesM30[0];
   MqlRates prevM30    = ratesM30[1];

   double curBody = MathAbs(currentM30.close - currentM30.open);
   double curRange = currentM30.high - currentM30.low;
   if(curRange == 0) curRange = 0.00001;

   double bestSimilarity = 0.0;
   int bestPastIndex = -1;
   int expectedResolution = 0; // +1 = CALL, -1 = PUT

   // 3. Escanear Historial de M30 buscando la Réplica más parecida
   for(int i = 2; i < copiedM30 - 1; i++)
   {
      MqlRates pastCandle = ratesM30[i];
      MqlRates pastPrev   = ratesM30[i + 1];
      MqlRates pastNext   = ratesM30[i - 1]; // Lo que ocurrió después (resolución)

      double pastBody = MathAbs(pastCandle.close - pastCandle.open);
      double pastRange = pastCandle.high - pastCandle.low;
      if(pastRange == 0) pastRange = 0.00001;

      // Comparación de simetría: cuerpos, mechas y dirección
      bool dirMatch = ((currentM30.close >= currentM30.open) == (pastCandle.close >= pastCandle.open));
      bool prevDirMatch = ((prevM30.close >= prevM30.open) == (pastPrev.close >= pastPrev.open));

      double bodyRatioDiff = MathAbs((curBody / curRange) - (pastBody / pastRange));
      double simScore = (1.0 - bodyRatioDiff) * 70.0;
      if(dirMatch) simScore += 20.0;
      if(prevDirMatch) simScore += 10.0;

      if(simScore > bestSimilarity)
      {
         bestSimilarity = simScore;
         bestPastIndex = i;
         expectedResolution = (pastNext.close > pastNext.open) ? 1 : ((pastNext.close < pastNext.open) ? -1 : 0);
      }
   }

   g_last_similarity = bestSimilarity;

   // 4. Si encontramos una Réplica de alta similitud, ENCAJONAR ambas zonas
   if(bestSimilarity >= InpMinSimilarity && bestPastIndex > 0)
   {
      MqlRates pastBoxMatch = ratesM30[bestPastIndex];

      // A) ENCAJONAR CAJA DEL PASADO (La referencia clonada)
      datetime pastStart = pastBoxMatch.time;
      datetime pastEnd   = pastStart + 1800; // 30 minutos
      double   pastHigh  = pastBoxMatch.high;
      double   pastLow   = pastBoxMatch.low;

      DrawBox("REP_BOX_PAST", pastStart, pastHigh, pastEnd, pastLow, InpColorBoxPast, "RÉPLICA HISTÓRICA [" + DoubleToString(bestSimilarity, 1) + "%]");

      // B) ENCAJONAR CAJA ACTUAL (La formación en curso)
      datetime curStart = currentM30.time;
      datetime curEnd   = curStart + 1800;
      double   curHigh  = currentM30.high;
      double   curLow   = currentM30.low;

      DrawBox("REP_BOX_CURR", curStart, curHigh, curEnd, curLow, InpColorBoxCurrent, "RÉPLICA ACTUAL EN FORMACIÓN");

      // C) DIBUJAR LÍNEA DEL 50% DE EQUILIBRIO
      if(InpShow50Level)
      {
         double level50 = (curHigh + curLow) / 2.0;
         DrawLine50("REP_LINE_50", curStart, curEnd, level50, clrGold);
      }

      // D) GENERAR SEÑAL DE COMPRA / VENTA EN M1
      if(expectedResolution != 0)
      {
         g_last_direction = (expectedResolution == 1) ? "COMPRA (CALL)" : "VENTA (PUT)";

         // Verificar si es una vela nueva para no repetir alertas
         datetime curCandleTime = time[0];
         if(curCandleTime != g_last_signal_time)
         {
            g_last_signal_time = curCandleTime;

            if(expectedResolution == 1)
            {
               BufferBuy[0] = low[0] - (10 * _Point);
               BufferSell[0] = 0.0;
               TriggerAlert("COMPRA (CALL)", _Symbol, bestSimilarity);
            }
            else
            {
               BufferSell[0] = high[0] + (10 * _Point);
               BufferBuy[0] = 0.0;
               TriggerAlert("VENTA (PUT)", _Symbol, bestSimilarity);
            }
         }
      }
   }
   else
   {
      g_last_direction = "ESCANEANDO...";
   }

   // 5. Actualizar Panel HUD en Pantalla
   DrawHUD("🟢 SISTEMA CONECTADO", clrSpringGreen, g_last_similarity, g_last_direction);

   return(rates_total);
}

//+------------------------------------------------------------------+
//| Dibuja una caja rectangular encajonando el patrón                |
//+------------------------------------------------------------------+
void DrawBox(string name, datetime t1, double p1, datetime t2, double p2, color clr, string desc)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
   }
   else
   {
      ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
      ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   }

   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TOOLTIP, desc);
}

//+------------------------------------------------------------------+
//| Dibuja la línea media 50% de la caja                             |
//+------------------------------------------------------------------+
void DrawLine50(string name, datetime t1, datetime t2, double price, color clr)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   }
   else
   {
      ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 0, price);
      ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
      ObjectSetDouble(0, name, OBJPROP_PRICE, 1, price);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
}

//+------------------------------------------------------------------+
//| Emite Alerta Sonora y Notificación                               |
//+------------------------------------------------------------------+
void TriggerAlert(string dir, string sym, double sim)
{
   string msg = StringFormat("🔥 SEÑAL VIP: %s en %s (Similitud Réplica: %.1f%%)", dir, sym, sim);
   if(InpAlertSound)
   {
      Alert(msg);
      PlaySound("expert.wav");
   }
   if(InpPushNotification)
   {
      SendNotification(msg);
   }
}

//+------------------------------------------------------------------+
//| Valida la Licencia consultando el EA Bridge o archivo compartido |
//+------------------------------------------------------------------+
bool ValidateLicense()
{
   long my_account = AccountInfoInteger(ACCOUNT_LOGIN);

   // 1. Revisar Variable Global en memoria activada por OTC_Feed_Bridge
   if(GlobalVariableCheck("OTC_VIP_LICENSE_ACTIVE"))
   {
      double active = GlobalVariableGet("OTC_VIP_LICENSE_ACTIVE");
      double acc = GlobalVariableGet("OTC_VIP_LICENSE_ACCOUNT");
      if(active == 1.0 && (long)acc == my_account)
      {
         g_license_valid = true;
         if(g_client_name == "") g_client_name = "Trader VIP (Admin Master)";
         return true;
      }
   }

   // 2. Revisar Archivo Compartido en FILE_COMMON
   int f = FileOpen("otc_vip_license.txt", FILE_READ | FILE_TXT | FILE_COMMON);
   if(f != INVALID_HANDLE)
   {
      string line = FileReadString(f);
      FileClose(f);

      string parts[];
      int n = StringSplit(line, '|', parts);
      if(n >= 3)
      {
         long file_acc = StringToInteger(parts[0]);
         string file_key = parts[1];
         string file_client = parts[2];
         long file_exp = (n >= 4) ? StringToInteger(parts[3]) : 0;

         if(file_acc == my_account && (file_key == InpLicenseKey || file_key != "") && (file_exp == 0 || TimeCurrent() < (datetime)file_exp))
         {
            g_license_valid = true;
            g_client_name = file_client;
            return true;
         }
      }
   }

   g_license_valid = false;
   return false;
}

//+------------------------------------------------------------------+
//| Dibuja el Panel Flotante en Pantalla                             |
//+------------------------------------------------------------------+
void DrawHUD(string statusText, color statusColor, double sim, string direction)
{
   string prefix = "REP_HUD_";

   if(ObjectFind(0, prefix + "BG") < 0)
   {
      ObjectCreate(0, prefix + "BG", OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XDISTANCE, 20);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YDISTANCE, 30);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XSIZE, 310);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YSIZE, 130);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BGCOLOR, C'10,15,24');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BORDER_COLOR, C'0,245,155');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   }

   CreateOrUpdateLabel(prefix + "T1", 35, 42, "TRADER 4 LESS - RÉPLICAS M30/M1", clrWhite, 9, true);
   CreateOrUpdateLabel(prefix + "T2", 35, 62, statusText, statusColor, 10, true);
   CreateOrUpdateLabel(prefix + "T3", 35, 84, "Licencia: " + (g_client_name != "" ? g_client_name : "Activa"), clrGold, 8, false);
   
   color dirClr = (StringFind(direction, "COMPRA") >= 0) ? clrSpringGreen : ((StringFind(direction, "VENTA") >= 0) ? clrCrimson : clrDodgerBlue);
   CreateOrUpdateLabel(prefix + "T4", 35, 104, "Patrón: " + direction, dirClr, 9, true);
   CreateOrUpdateLabel(prefix + "T5", 35, 126, "Similitud Caja: " + DoubleToString(sim, 1) + "%", C'142,155,176', 8, false);

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
