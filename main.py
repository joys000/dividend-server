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
        # 네이버 금융 자동완성 API
        url = f"https://ac.finance.naver.com/ac?q={q}&st=11&r_format=json&r_enc=utf-8&n__={datetime.now().timestamp()}"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        # 데이터 구조 파싱
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
        print(f"한국 주식 검색 에러: {e}")
        # 🚨 [수정] 중복되었던 return문을 정리했습니다.
        return {"status": "error", "message": str(e)}
