from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd
import asyncio

app = FastAPI()

# CORS 설정 (프론트엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🚨 [추가] 한국 주식 데이터 메모리 로드 (서버 시작 시 1회 실행)
print("🚀 KRX 주식 목록 로딩 중...")
try:
    krx_df = fdr.StockListing('KRX')
    print("✅ 로딩 완료!")
except Exception as e:
    print(f"❌ 로딩 실패: {e}")
    krx_df = pd.DataFrame()

# 1. 헬스 체크 (서버 예열용)
@app.get("/")
def read_root():
    return {"status": "alive", "message": "재우의 배당금 데이터 공장 가동 중 ⚙️"}

# 2. [신규] 시장 지수 API (홈페이지 전광판용)
@app.get("/indices")
async def get_indices():
    try:
        # 주요 지수 티커
        tickers = ["^KS11", "^KQ11", "^GSPC", "^IXIC"]
        # 최근 2일 데이터를 가져와서 전일 대비 변동폭 계산
        data = yf.download(tickers, period="2d", interval="1d")['Close']
        
        indices = []
        names = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ", "^GSPC": "S&P 500", "^IXIC": "NASDAQ"}
        
        last_row = data.iloc[-1]
        prev_row = data.iloc[0]
        
        for ticker in tickers:
            current = last_row[ticker]
            prev = prev_row[ticker]
            change = current - prev
            pct = (change / prev) * 100
            indices.append({
                "name": names[ticker],
                "price": round(current, 2),
                "change": round(change, 2),
                "pct": round(pct, 2)
            })
        return {"status": "success", "data": indices}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 3. 실시간 환율 API (네이버 크롤링)
@app.get("/exchange")
async def get_exchange_rate():
    try:
        url = "https://finance.naver.com/marketindex/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        rate_str = soup.select_one("#exchangeList > li.on > a.head.usd > div > span.value").text
        rate = float(rate_str.replace(",", ""))
        return {"status": "success", "rate": rate}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 4. 미국/한국 배당 히스토리 API
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

# 5. 한국 주식 초고속 검색 API (메모리 기반)
@app.get("/search/kr")
async def search_korean_stock(q: str):
    if krx_df.empty:
        return {"status": "error", "message": "데이터 로딩 중입니다."}
    try:
        mask = krx_df['Name'].str.contains(q, case=False, na=False) | krx_df['Code'].str.contains(q, na=False)
        filtered = krx_df[mask]
        results = []
        for _, row in filtered.head(10).iterrows():
            market = row.get('Market', '')
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            results.append({
                "symbol": f"{row['Code']}{suffix}",
                "description": row['Name'],
                "type": "KOREA"
            })
        return {"status": "success", "result": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 6. 한국 주식 현재가 상세 조회 (네이버 크롤링)
@app.get("/quote/kr/{ticker}")
async def get_kr_quote(ticker: str):
    try:
        code = ticker.split('.')[0]
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        
        today_price = soup.select_one('.no_today .blind').text
        exday = soup.select_one('.no_exday')
        blinds = exday.select('.blind')
        change_val = blinds[0].text if len(blinds) > 0 else "0"
        change_pct = blinds[1].text if len(blinds) > 1 else "0"
        
        is_up = "up" in exday.get('class', [])
        is_down = "down" in exday.get('class', [])
        sign = "+" if is_up else ("-" if is_down else "")

        info_tds = soup.select('.no_info td .blind')
        return {
            "status": "success",
            "price": today_price,
            "change": f"{sign}{change_val}",
            "change_percent": f"{sign}{change_pct}%",
            "prev_close": info_tds[0].text,
            "high": info_tds[1].text,
            "open": info_tds[3].text,
            "low": info_tds[4].text,
            "time": soup.select_one('.description .date').text if soup.select_one('.description .date') else "실시간",
            "is_positive": is_up,
            "is_negative": is_down
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
