from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
import json

app = FastAPI()

# ⚠️ CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "재우의 배당금 데이터 공장 가동 중 ⚙️"}

# 1. 환율 크롤링 API (네이버 금융)
@app.get("/exchange")
async def get_exchange_rate():
    try:
        url = "https://finance.naver.com/marketindex/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        rate_str = soup.select_one("#exchangeList > li.on > a.head.usd > div > span.value").text
        rate = float(rate_str.replace(",", ""))
        
        return {"status": "success", "rate": rate, "source": "Naver Finance"}
    except Exception as e:
        print(f"환율 크롤링 에러: {e}")
        return {"status": "error", "message": str(e)}

# 2. 배당금 내역 API (yfinance 활용)
@app.get("/dividend/{ticker}")
async def get_dividend_history(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
        
        if dividends.empty:
            return {"status": "error", "message": "배당 내역이 없습니다."}
        
        recent_divs = dividends.tail(5).sort_index(ascending=False)
        history = []
        
        for date, amount in recent_divs.items():
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "amount": f"{amount:.4f}"
            })
            
        return {
            "status": "success", 
            "ticker": ticker,
            "history": history
        }
    except Exception as e:
        print(f"배당금 데이터 에러: {e}")
        # 🚨 [수정] 기존 코드에서 누락된 return문을 추가했습니다.
        return {"status": "error", "message": str(e)}

# 3. 한국 주식 실시간 검색 API (네이버 검색 엔진 활용)
@app.get("/search/kr")
async def search_korean_stock(q: str):
    try:
        # 🚨 [보강] 타임스탬프 형식을 정수로 단순화하여 DNS 문제를 방지합니다.
        t_stamp = int(datetime.now().timestamp() * 1000)
        
        # 주소 끝의 서브도메인이 문제일 수 있어, 더 대중적인 API 경로를 시도합니다.
        url = f"https://ac.finance.naver.com/ac?q={q}&st=11&r_format=json&r_enc=utf-8&n__={t_stamp}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.naver.com/"
        }
        
        # 🚨 타임아웃을 짧게 설정하고 에러를 명확히 잡습니다.
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.ConnectionError:
            # DNS 오류 발생 시 대체 주소로 한 번 더 시도 (Fallback)
            print("기본 검색 서버 DNS 실패, 대체 서버 시도 중...")
            url = f"https://suggest-bar.naver.com/suggest?q={q}" # 네이버 통합검색 API 사용
            response = requests.get(url, headers=headers, timeout=5)
            data = response.json()
        
        items_list = data.get('items', [])
        if not items_list:
            return {"status": "success", "count": 0, "result": []}
            
        items = items_list[0]
        results = []
        for item in items:
            name = item[0]
            ticker = item[1]
            results.append({
                "symbol": f"{ticker}.KS" if len(ticker) == 6 else ticker,
                "description": name,
                "type": "KOREA"
            })
            
        return {"status": "success", "count": len(results), "result": results}
        
    except Exception as e:
        print(f"한국 주식 검색 엔진 치명적 에러: {e}")
        return {
            "status": "error", 
            "message": "서버 네트워크 장애가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            "debug": str(e)
        }
