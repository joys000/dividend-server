from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🚨 서버 메모리에 한국 주식 명부를 저장할 변수
krx_df = None

# 서버가 켜질 때 딱 한 번 실행되는 엔진 (KRX 전체 명부 다운로드)
@app.on_event("startup")
def load_krx_data():
    global krx_df
    try:
        print("서버 시동: 한국거래소(KRX) 주식 명부 장전 중...")
        # 한국거래소(코스피, 코스닥, 코넥스) 전체 종목 가져오기
        krx_df = fdr.StockListing('KRX')
        print(f"장전 완료: 총 {len(krx_df)}개 종목 대기 중.")
    except Exception as e:
        print(f"KRX 명부 장전 실패: {e}")

@app.get("/")
def read_root():
    return {"message": "재우의 배당금 데이터 공장 가동 중 ⚙️"}

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
        return {"status": "success", "rate": rate, "source": "Naver"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/dividend/{ticker}")
async def get_dividend_history(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
        if dividends.empty:
            return {"status": "error", "message": "배당 내역이 없습니다."}
        
        recent_divs = dividends.tail(5).sort_index(ascending=False)
        history = [{"date": date.strftime("%Y-%m-%d"), "amount": f"{amount:.4f}"} for date, amount in recent_divs.items()]
        return {"status": "success", "ticker": ticker, "history": history}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 🚨 네이버를 버리고, 서버 내부 메모리에서 초고속으로 검색하는 API
@app.get("/search/kr")
async def search_korean_stock(q: str):
    global krx_df
    
    # 데이터가 아직 로드되지 않았을 경우 방어 코드
    if krx_df is None or krx_df.empty:
        return {"status": "error", "message": "주식 데이터를 로딩 중입니다. 10초 후 다시 시도하세요."}

    try:
        # 대소문자 구분 없이 검색어 포함 여부 확인 (이름 또는 코드)
        mask = krx_df['Name'].str.contains(q, case=False, na=False) | krx_df['Code'].str.contains(q, na=False)
        filtered = krx_df[mask]
        
        results = []
        # 너무 많이 보내면 프론트가 뻗으므로 상위 10개만 전송
        for _, row in filtered.head(10).iterrows():
            code = row['Code']
            name = row['Name']
            market = row.get('Market', '')
            
            # 코스피는 .KS, 코스닥은 .KQ를 붙여 yfinance와 호환되게 만듦
            suffix = ".KS" if market == "KOSPI" else ".KQ" if market == "KOSDAQ" else ".KS"
            
            results.append({
                "symbol": f"{code}{suffix}",
                "description": name,
                "type": "KOREA"
            })
            
        return {"status": "success", "count": len(results), "result": results}
    except Exception as e:
        print(f"메모리 검색 에러: {e}")
        return {"status": "error", "message": str(e)}
