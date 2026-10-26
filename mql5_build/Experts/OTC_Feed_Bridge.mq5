//+------------------------------------------------------------------+
//|                                             OTC_Feed_Bridge.mq5  |
//|                             Trader 4 Less - VIP Algorithm System |
//|                                              Puente Local PC MT5 |
//+------------------------------------------------------------------+
#property copyright "Trader 4 Less VIP"
#property link      "https://tradingsnr.info"
#property version   "2.00"
#property description "Puente Local de Datos IQ Option OTC para MetaTrader 5"
#property description "Lee el flujo local de alta frecuencia con latencia 0 ms"

#include <Trade\Trade.mqh>

//--- Entradas de Configuración
input group "=== CONFIGURACIÓN LOCAL ==="
input int InpTimerMs = 100; // Intervalo de Actualización Local (ms)

//--- Lista de los 10 Pares OTC Oficiales
const string OTC_PAIRS[10] = {
   "EURUSD_OTC", "GBPUSD_OTC", "USDJPY_OTC", "EURJPY_OTC", "AUDUSD_OTC",
   "USDCAD_OTC", "USDCHF_OTC", "NZDUSD_OTC", "EURGBP_OTC", "GBPJPY_OTC"
};

//--- Variables Globales de Estado
ulong    g_ticks_count   = 0;
long     g_last_tick_msc[10];
datetime g_bar_time[10];
double   g_bar_open[10];
double   g_bar_high[10];
double   g_bar_low[10];
double   g_bar_close[10];
long     g_bar_vol[10];
bool     g_pair_seeded[10];

int GetPairIndex(string sym)
{
   for(int i = 0; i < 10; i++)
   {
      if(OTC_PAIRS[i] == sym) return i;
   }
   return -1;
}

//+------------------------------------------------------------------+
//| Inicialización del Expert Advisor                                |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== Iniciando Puente Local OTC para MetaTrader 5 ===");

   // 1. Crear los 10 Símbolos Personalizados OTC si no existen
   CreateCustomOTCSymbols();

   // 2. Inicializar estados en memoria
   for(int i = 0; i < 10; i++)
   {
      g_last_tick_msc[i] = 0;
      g_bar_time[i] = 0;
      g_bar_open[i] = 0.0;
      g_bar_high[i] = 0.0;
      g_bar_low[i] = 0.0;
      g_bar_close[i] = 0.0;
      g_bar_vol[i] = 0;
      g_pair_seeded[i] = false;

      // Cargar historial de velas M1 desde el archivo local
      SeedHistoryFromLocalFile(OTC_PAIRS[i]);
   }

   // 3. Configurar gráfico activo para velas japonesas
   ChartSetInteger(0, CHART_MODE, CHART_CANDLES);
   ChartSetInteger(0, CHART_AUTOSCROLL, true);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, C'0, 230, 118');
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, C'255, 23, 68');
   ChartSetInteger(0, CHART_COLOR_CHART_UP, C'0, 230, 118');
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN, C'255, 23, 68');
   ChartNavigate(0, CHART_END, 0);
   ChartRedraw(0);

   // 4. Iniciar Timer de alta velocidad (100 ms)
   EventSetMillisecondTimer(InpTimerMs);

   // 5. Dibujar Panel Informativo
   DrawHUD("🟢 PUENTE LOCAL ACTIVO", clrSpringGreen, "Streaming local 0 ms");

   Print("Puente Local iniciado con éxito. Esperando ticks de Local_OTC_Bridge.py...");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Desinicialización                                                |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, "OTC_HUD_");
   Print("Puente Local detenido.");
}

//+------------------------------------------------------------------+
//| Evento Timer de Alta Frecuencia (Lee archivo local en FILE_COMMON)|
//+------------------------------------------------------------------+
void OnTimer()
{
   ReadLocalLiveTicks();
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
      SymbolSelect(sym, true);
   }
}

//+------------------------------------------------------------------+
//| Carga historial de velas M1 desde el archivo local en FILE_COMMON|
//+------------------------------------------------------------------+
void SeedHistoryFromLocalFile(string sym)
{
   string filename = "otc_history_" + sym + ".json";
   int handle = FileOpen(filename, FILE_READ | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE)
   {
      return;
   }

   string json = "";
   while(!FileIsEnding(handle))
   {
      json += FileReadString(handle);
   }
   FileClose(handle);

   int cPos = StringFind(json, "\"candles\":[");
   if(cPos < 0) return;

   int endArr = StringFind(json, "]", cPos);
   if(endArr < 0) return;

   string arrStr = StringSubstr(json, cPos, endArr - cPos + 1);

   MqlRates rates[];
   ArrayResize(rates, 1000);
   int ratesCount = 0;
   int curIdx = 0;

   while(ratesCount < 1000)
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
         rates[ratesCount].tick_volume = (c_vol > 0) ? c_vol : 20;
         rates[ratesCount].spread = 10;
         rates[ratesCount].real_volume = 0;
         ratesCount++;
      }
      curIdx = objEnd + 1;
   }

   if(ratesCount > 0)
   {
      ArrayResize(rates, ratesCount);
      int updated = CustomRatesUpdate(sym, rates, ratesCount);
      Print("✅ ", sym, ": ", updated, " velas históricas M1 inyectadas desde archivo local.");
      int idx = GetPairIndex(sym);
      if(idx >= 0) g_pair_seeded[idx] = true;
   }
}

//+------------------------------------------------------------------+
//| Lee los ticks en tiempo real desde otc_live.json en FILE_COMMON  |
//+------------------------------------------------------------------+
void ReadLocalLiveTicks()
{
   int handle = FileOpen("otc_live.json", FILE_READ | FILE_TXT | FILE_COMMON | FILE_SHARE_READ);
   if(handle == INVALID_HANDLE)
   {
      return;
   }

   string json = "";
   while(!FileIsEnding(handle))
   {
      json += FileReadString(handle);
   }
   FileClose(handle);

   if(StringLen(json) < 20) return;

   datetime global_server_ts = (datetime)ExtractDoubleValue(json, 0, "\"timestamp\":");
   long global_msc = (long)ExtractDoubleValue(json, 0, "\"timestamp_msc\":");

   if(global_server_ts == 0) global_server_ts = TimeCurrent();
   if(global_msc == 0) global_msc = (long)global_server_ts * 1000 + (long)(GetTickCount64() % 1000);

   bool chart_updated = false;

   // Procesar los 10 pares OTC
   for(int i = 0; i < 10; i++)
   {
      string sym = OTC_PAIRS[i];
      int symPos = StringFind(json, "\"" + sym + "\"");
      if(symPos < 0) continue;

      double bid = ExtractDoubleValue(json, symPos, "\"bid\":");
      double ask = ExtractDoubleValue(json, symPos, "\"ask\":");
      double last = ExtractDoubleValue(json, symPos, "\"last\":");

      if(bid > 0)
      {
         double spread = (StringFind(sym, "JPY") >= 0) ? 0.02 : 0.0001;
         double final_ask = (ask > 0) ? ask : (bid + spread);
         double final_last = (last > 0) ? last : bid;

         // Asegurar time_msc estrictamente ascendente (regla estricta MT5)
         long tick_msc = global_msc;
         if(tick_msc <= g_last_tick_msc[i])
            tick_msc = g_last_tick_msc[i] + 1;
         g_last_tick_msc[i] = tick_msc;

         // 1. Inyectar Tick en Market Watch
         MqlTick ticks[1];
         ticks[0].time = (datetime)(tick_msc / 1000);
         ticks[0].time_msc = tick_msc;
         ticks[0].bid = bid;
         ticks[0].ask = final_ask;
         ticks[0].last = final_last;
         ticks[0].volume = 1;
         ticks[0].flags = TICK_FLAG_BID | TICK_FLAG_ASK | TICK_FLAG_LAST;

         CustomTicksAdd(sym, ticks, 1);
         g_ticks_count++;

         // 2. Actualizar o formar la vela M1 actual en vivo en el gráfico
         datetime bar_ts = (datetime)(ticks[0].time - (ticks[0].time % 60));
         MqlRates live_rate[1];
         live_rate[0].time = bar_ts;
         live_rate[0].spread = 10;
         live_rate[0].real_volume = 0;

         if(g_bar_time[i] == bar_ts && g_bar_open[i] > 0)
         {
            g_bar_high[i]  = MathMax(g_bar_high[i], final_last);
            g_bar_low[i]   = MathMin(g_bar_low[i], final_last);
            g_bar_close[i] = final_last;
            g_bar_vol[i]++;

            live_rate[0].open  = g_bar_open[i];
            live_rate[0].high  = g_bar_high[i];
            live_rate[0].low   = g_bar_low[i];
            live_rate[0].close = g_bar_close[i];
            live_rate[0].tick_volume = g_bar_vol[i];
         }
         else
         {
            // Nueva barra M1 iniciada
            g_bar_time[i]  = bar_ts;
            g_bar_open[i]  = final_last;
            g_bar_high[i]  = final_last;
            g_bar_low[i]   = final_last;
            g_bar_close[i] = final_last;
            g_bar_vol[i]   = 1;

            live_rate[0].open  = final_last;
            live_rate[0].high  = final_last;
            live_rate[0].low   = final_last;
            live_rate[0].close = final_last;
            live_rate[0].tick_volume = 1;
         }

         CustomRatesUpdate(sym, live_rate, 1);

         if(sym == _Symbol)
            chart_updated = true;
      }
   }

   if(chart_updated)
   {
      ChartRedraw(0);
   }

   if(g_ticks_count % 25 == 0)
   {
      DrawHUD("🟢 PUENTE LOCAL ACTIVO", clrSpringGreen, "Ticks locales: " + IntegerToString(g_ticks_count));
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
//| Dibuja el Panel Flotante en Pantalla                             |
//+------------------------------------------------------------------+
void DrawHUD(string statusText, color statusColor, string subtitle)
{
   string prefix = "OTC_HUD_";

   if(ObjectFind(0, prefix + "BG") < 0)
   {
      ObjectCreate(0, prefix + "BG", OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XDISTANCE, 20);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YDISTANCE, 30);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_XSIZE, 300);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_YSIZE, 110);
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BGCOLOR, C'12,18,28');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_BORDER_COLOR, C'0,210,255');
      ObjectSetInteger(0, prefix + "BG", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   }

   CreateOrUpdateLabel(prefix + "T1", 35, 42, "TRADER 4 LESS - PUENTE LOCAL MT5", clrWhite, 9, true);
   CreateOrUpdateLabel(prefix + "T2", 35, 62, statusText, statusColor, 10, true);
   CreateOrUpdateLabel(prefix + "T3", 35, 84, subtitle, C'142,155,176', 8, false);
   CreateOrUpdateLabel(prefix + "T4", 35, 104, "Pares: 10 OTC activos en vivo", clrDodgerBlue, 8, false);

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
