import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime

app = FastAPI()

# ⚠️ CORS 설정: 웹사이트가 이 서버에 접근할 수 있도록 허용하는 필수 보안 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 나중에는 본인의 웹사이트 주소만 넣는 것이 가장 안전합니다.
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
        
        # 네이버 금융에 접속해서 HTML을 통째로 가져옵니다.
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # BeautifulSoup으로 HTML을 분석합니다.
        soup = BeautifulSoup(response.text, "html.parser")
        
        # CSS 선택자를 이용해 '미국 USD' 환율 값만 정확히 뽑아냅니다.
        rate_str = soup.select_one("#exchangeList > li.on > a.head.usd > div > span.value").text
        
        # 콤마(,)를 제거하고 숫자로 변환 (예: "1,350.50" -> 1350.50)
        rate = float(rate_str.replace(",", ""))
        
        return {"status": "success", "rate": rate, "source": "Naver Finance"}
    
    except Exception as e:
        print(f"환율 크롤링 에러: {e}")
        return {"status": "error", "message": str(e)}

# 2. 배당금 내역 API (yfinance 활용)
@app.get("/dividend/{ticker}")
async def get_dividend_history(ticker: str):
    try:
        # 한국 주식 티커 처리 (예: 삼성전자는 '005930.KS' 형태로 들어옴)
        stock = yf.Ticker(ticker)
        
        # 배당 내역 가져오기 (가장 최근 데이터부터)
        dividends = stock.dividends
        
        if dividends.empty:
            return {"status": "error", "message": "배당 내역이 없습니다."}
        
        # 최신 5개의 배당 내역만 추출하여 포맷팅
        recent_divs = dividends.tail(5).sort_index(ascending=False)
        history = []
        
        for date, amount in recent_divs.items():
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "amount": f"{amount:.4f}"  # 소수점 4자리까지 표시
            })
            
        return {
            "status": "success", 
            "ticker": ticker,
            "history": history
        }
        
    except Exception as e:
        print(f"배당금 데이터 에러: {e}")
@app.get("/search/kr")
async def search_korean_stock(q: str):
    try:
        # 네이버 금융의 실시간 자동완성 API를 활용 (로컬 DB 필요 없음)
        # st=11 (국내주식), r_format=json (JSON 형식)
        url = f"https://ac.finance.naver.com/ac?q={q}&st=11&r_format=json&r_enc=utf-8&n__={datetime.now().timestamp()}"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        # 네이버 응답 구조: data['items'][0]에 결과 리스트가 담겨 있음
        items = data.get('items', [[]])[0]
        
        results = []
        for item in items:
            # item 구조: ["종목명", "티커", "기타1", "기타2", ...]
            name = item[0]
            ticker = item[1]
            
            results.append({
                "symbol": f"{ticker}.KS" if len(ticker) == 6 else ticker, # 6자리 숫자는 한국 티커 처리
                "description": name,
                "type": "KOREA"
            })
            
        return {"status": "success", "count": len(results), "result": results}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}
        return {"status": "error", "message": str(e)}
