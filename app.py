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

【核心推演與分析規範】：
1. 第一項：前日定性
   - 僅能輸出：前日上漲、前日下跌、震盪收縮日、漲動能過激日、跌動能過激日。
   - ★嚴格禁令：絕對刪除且不可出現「陽線」或「陰線」！
2. 第二項：前一日波幅
   - 僅需顯示圖表右上角儀表板中的「昨日波幅」數值（例如 4268），不需顯示五日均值。
3. 第三項：PDH 價位、PDL 價位
   - 明確辨識圖表上的「昨日最高價 (PDH)」與「昨日最低價 (PDL)」具體數值。
4. 第四項：今日策略
   - 依據系統五步驟核心邏輯（回調點 7 大取消情境、PDH/PDL 5 大無效取代、8 大觀望有效判定、4 大特殊情形）推導今日策略。
   - ★極致核心鐵律★：全篇策略內容「嚴禁出現任何 FIBO 的比例數字（絕對不能出現 0.786、0.214、0.9、0.1、1.05、-0.05、0.618、0.5、0.3、0.7 等）」！
   - 所有轉折區、領域未破區、假突破區等位置，請一律換算為圖表上的「實際具體價位」（例如：「回調至 2654.20 附近配合 TL 突破進多」、「突破 2685.10 假突破且反轉收回時重畫領域逆勢操作」）。只要價位，不要 FIBO 數字！
5. 第五項：重要經濟數據 (台灣時間)
   - 列出當日（或最新交易日）對黃金有重大影響的美國經濟數據（如 CPI、PPI、非農 NFP、初請失業金、FOMC 利率決議、PMI、GDP 等）及其對應的「台灣時間（UTC+8，24小時制）」。
   - 若當日無一級重大數據，請標註「今日無重大美國一級經濟數據公布 (常規關注美股開盤 21:30 動能)」。

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
  "daily_strategy": {
    "date": "2026-XX-XX",
    "item1_quality": "前日上漲 / 前日下跌 / 震盪收縮日 / 漲動能過激日 / 跌動能過激日",
    "item2_yesterday_range": "XXXX",
    "item3_pdh": "XXXX.XX",
    "item3_pdl": "XXXX.XX",
    "item4_strategy": "今日採取之具體作戰策略（全篇無任何 FIBO 數字，皆以實際具體價位呈現）",
    "item5_economic_data": [
      "20:30 美國 9 月 CPI 年率及核心 CPI 月率 (重大)",
      "22:00 美國 10 月密西根大學消費者信心指數"
    ]
  },
  "alerts_to_set": [
    {
      "name": "轉折深水區多單提醒 (具體價位)",
      "price": "XXXX.XX",
      "condition": "價格向下穿越",
      "action_reminder": "配合 M15 TL 突破進場，首探 H1 不破出手"
    }
  ],
  "master_analysis_summary": "交易大師對當前局勢的專業剖析與操作叮嚀（同樣嚴禁出現 FIBO 數字，皆以實際價位說明）"
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

            model_name = data.get("model", "gemini-3.8-flash")
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

            # 呼叫 Gemini REST API (支援候選模型自動容錯降級)
            candidate_models = [model_name, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.8-flash"]
            seen = set()
            unique_models = [m for m in candidate_models if not (m in seen or seen.add(m))]

            last_err = None
            for m in unique_models:
                try:
                    gemini_result = self.call_gemini_vision(api_key, m, image_b64, mime_type)
                    self.respond_json(200, gemini_result)
                    return
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if any(k in err_str for k in ["503", "high demand", "spikes in demand", "overloaded", "404", "no longer available", "not found", "429", "resource_exhausted", "quota"]):
                        continue
                    raise e
            if last_err:
                raise last_err

        except Exception as e:
            self.respond_json(500, {"error": f"伺服器錯誤: {str(e)}"})

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
