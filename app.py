import os
import sys
import json
import base64
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
import webbrowser
import threading

PORT = 8728
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# 交易系統大師級 System Prompt
SYSTEM_PROMPT = """
你是一位頂級 XAUUSD (黃金) 專業機構交易大師，負責執行嚴格的【XAUUSD 專屬頂級交易系統】。
使用者會上傳一張「畫好 FIBO 擴展指標且僅包含前一日完整 K 棒與右上角波幅資訊」的 TradingView 圖表截圖。

【嚴格截圖驗證】：
- 截圖必須「只能是前一日搭配指標的截圖（不能有額外多日雜訊或無指標圖表）」。
- 如果截圖不符合規範（例如跨越多個交易日、缺少 FIBO 指標、缺少右上角昨日/5日平均波幅），請在分析報告最上方給予明確警示，但仍盡可能分析所見到的資訊。

【五大步驟標準分析流程】：
1. 步驟一：前日定性
   - 判斷前一日是「前日上漲」還是「前日下跌」。
   - 若前一日未破前天 PDH 和 PDL，標註「震盪收縮日(需搭配TL並觀望)」。
   - 若前一日為極端急漲 / 急跌，標註「漲動能過激日」或「跌動能過激日」。

2. 步驟二：FIBO 擴展與波幅數據辨識
   - 辨識圖表右上角儀表板數值：
     * 昨日波幅 (Yesterday Range)
     * 前五日平均波幅 (ADR 5-Day Average)
   - 辨識 10 條 FIBO 線的實際價位：
     * 1.05 (假突破區)
     * 1.00 (PDH 或 PDL)
     * 0.90 (領域未破區)
     * 0.786 (轉折區深水位)
     * 0.70 (觀望區邊界)
     * 0.30 (觀望區邊界)
     * 0.214 (轉折區深水位)
     * 0.10 (領域未破區)
     * 0.00 (PDL 或 PDH)
     * -0.05 (假突破區)

3. 步驟三：回調點有效性檢驗 (檢核 7 大取消情境)
   - 檢核是否存在回調點，並逐一審查回調取消 7 大無效情境：
     1. 若回調點是前一日的 H1 倒數三根 K 棒則取消
     2. 回調在領域內
     3. PDH 或當日出現反轉空或開盤下跳則取消回調低（易下破）
     4. PDL 或當日出現反轉多或開盤上跳則取消回調高（易上破）
     5. 前一日急跌則取消回調低（易下破）
     6. 前一日急漲則取消回調高（易上破）
     7. 前一日未破前天的 PDH 和 PDL
   - 鐵律提醒：「使用回調點進場前需觀望且配合 TL 或盤勢轉換」。

4. 步驟四：PDH / PDL 狀態與有效性判定
   - 檢核無效與取代：
     * 提早休市 (前日 H1 < 23根) 或來回三段 (掃盤) ➔ 取代防守為前天 PDH/PDL 或當日亞盤 END 收盤高低點。
     * 跳價需等回補後再操作同向單 (未回補前無當日回調點)。
     * H1 關盤淺回至 0.9~1 或關盤剛好是 PDH/PDL ➔ 注意假突破區或當日回調。
     * H1 關盤在 0.3~0.7 ➔ 嚴格觀望至亞盤 END 後搭配 TL。
   - 檢核 8 大觀望或有效判定：
     ① 前一天下跌 + H1 關盤在 0.1~0.3 (0.214) 且 PDL 為反轉 (上跳取消或等亞盤 END)
     ② 前一天上漲 + H1 關盤在 0.1~0.3 (0.214) 且 PDH 為反轉 (下跳取消或等亞盤 END)
     ③ 前一天下跌 + H1 關盤在 0.7~0.9 (0.786) 且 PDL 為反轉 (下跳取消或等亞盤 END)
     ④ 前一天上漲 + H1 關盤在 0.7~0.9 (0.786) 且 PDH 為反轉 (上跳取消或等亞盤 END)
     ⑤ 前一天急跌則 PDL 觀望
     ⑥ 前一天急漲則 PDH 觀望
     ⑦ 前一天下跌 + H1 關盤在 0~0.1 則領域失效 (等亞盤 END)
     ⑧ 前一天上漲 + H1 關盤在 0~0.1 則領域失效 (等亞盤 END)
   - 檢核 4 大特殊情形：
     ① 破 PDH/PDL 後出反轉 K 或收回領域內 ➔ 重畫領域 (逆勢注意保本)
     ② 破 PDH/PDL 後收回轉折區內 ➔ 可等回調領域 (逆勢注意保本)
     ③ 不破 PDH/PDL (非反轉 K) 先回調再破 ➔ 可用當日回調 (若破後出反轉 K 或收回領域內則取消)
     ④ 強趨勢破 PDH/PDL (回調點不使用) ➔ 可搭配 TL

5. 步驟五：產出當日對應策略與作戰日誌

【回測風控三大鐵律】：
1. 拒絕在同一個盤勢裡多次試單。
2. 獲利為止損兩倍時可平倉一半，是否做保本看進場位置是否容易被掃掉。
3. 若止損要更多，則手數需更加保守。

【必須輸出的 JSON 格式】：
請一律以繁體中文（台灣）輸出，並遵循以下 JSON 結構：
```json
{
  "is_valid_screenshot": true,
  "validation_note": "截圖符合規範：包含前一日完整K棒與指標數值",
  "daily_journal": {
    "date": "自動辨識或當前日期",
    "step1_quality": "前日上漲 / 前日下跌 / 震盪收縮日 / 漲跌動能過激日",
    "step2_range": {
      "yesterday_range": "4268",
      "adr5": "7470"
    },
    "step3_pullback": {
      "has_pullback": "是 / 否",
      "close_region": "例如：0.7~0.9 (0.786附近) 或 0.3~0.7 等",
      "is_gap": "正常無跳價 / 開盤上跳 / 開盤下跳",
      "use_prev_two_days_pdh_pdl": "是 / 否"
    },
    "step4_pdh_pdl_validity": "有效 / 觀望 / SL要多抓 / 領域失效(等亞盤END) / 重畫領域",
    "step5_strategy": "寫出今日用此系統採取什麼策略"
  },
  "fib_levels": {
    "p_105": "數值",
    "p_100_pdh_pdl": "數值",
    "p_090": "數值",
    "p_0786": "數值",
    "p_070": "數值",
    "p_030": "數值",
    "p_0214": "數值",
    "p_010": "數值",
    "p_000_pdl_pdh": "數值",
    "p_n005": "數值"
  },
  "alerts_to_set": [
    {
      "name": "提醒名稱 (例如：0.786 黃金轉折提醒)",
      "price": "具體價格 (如 4005.46)",
      "condition": "價格向下穿越 / 向上觸碰",
      "action_reminder": "配合 M15/M5 TL 突破進場，首探 H1 不破出手"
    }
  ],
  "master_analysis_summary": "交易大師對當前局勢的專業剖析與操作叮嚀"
}
```
"""

class TradingSystemHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_POST(self):
        if self.path == "/api/analyze":
            self.handle_analyze()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_analyze(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)

            api_key = data.get("api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "")
            if not api_key:
                self.respond_json(400, {"error": "請提供 Gemini API Key！可在介面輸入或設定 GEMINI_API_KEY 環境變數。"})
                return

            model_name = data.get("model", "gemini-2.5-flash")
            image_b64 = data.get("image_base64", "")
            if not image_b64:
                self.respond_json(400, {"error": "未提供圖片資料！"})
                return

            # 清理 base64 前綴
            if "," in image_b64:
                header, image_b64 = image_b64.split(",", 1)
                mime_type = "image/png"
                if "image/jpeg" in header or "image/jpg" in header:
                    mime_type = "image/jpeg"
                elif "image/webp" in header:
                    mime_type = "image/webp"
            else:
                mime_type = "image/png"

            # 呼叫 Gemini REST API
            gemini_result = self.call_gemini_vision(api_key, model_name, image_b64, mime_type)
            self.respond_json(200, gemini_result)

        except Exception as e:
            self.respond_json(500, {"error": f"伺服器內部錯誤: {str(e)}"})

    def call_gemini_vision(self, api_key, model_name, image_b64, mime_type):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": SYSTEM_PROMPT + "\n\n請仔細檢視這張 XAUUSD 圖表截圖，嚴格依據系統手冊規範進行判斷，並輸出合規的 JSON。"},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_b64
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                resp_text = response.read().decode("utf-8")
                resp_json = json.loads(resp_text)
                
                # 提取模型生成的文本
                candidates = resp_json.get("candidates", [])
                if not candidates:
                    raise ValueError("Gemini 未返回有效候選結果")
                
                parts = candidates[0].get("content", {}).get("parts", [])
                raw_text = parts[0].get("text", "")
                
                # 解析內部 JSON
                try:
                    result_json = json.loads(raw_text)
                except Exception:
                    # 容錯處理：若是被 markdown codeblock 包裹
                    clean = raw_text.strip()
                    if clean.startswith("```json"):
                        clean = clean[7:]
                    if clean.endswith("```"):
                        clean = clean[:-3]
                    result_json = json.loads(clean.strip())

                return result_json

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            raise RuntimeError(f"Gemini API 請求失敗 ({e.code}): {err_msg}")
        except Exception as e:
            raise RuntimeError(f"連線或解析失敗: {str(e)}")

    def respond_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

def run_server():
    os.makedirs(WEB_DIR, exist_ok=True)
    server_address = ("127.0.0.1", PORT)
    httpd = HTTPServer(server_address, TradingSystemHandler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"==================================================")
    print(f"  XAUUSD 專屬頂級交易系統 - 截圖AI戰術終端已啟動！")
    print(f"  本地存取網址: {url}")
    print(f"==================================================")
    
    # 延遲 1 秒自動開啟瀏覽器
    def open_browser():
        webbrowser.open(url)
    
    threading.Timer(1.0, open_browser).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已安全停止。")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
