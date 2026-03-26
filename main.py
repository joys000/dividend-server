from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=10) # 동기 함수 처리를 위한 도구

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 글로벌 데이터 저장소
krx_df = pd.DataFrame()

# 서버 시작 시 데이터 로드 함수
def load_krx_data():
    global krx_df
    print("🚀 KRX 주식 목록 로딩 중...")
    try:
        krx_df = fdr.StockListing('KRX')
        print(f"✅ 로딩 완료! (총 {len(krx_df)}개 종목)")
    except Exception as e:
        print(f"❌ 로딩 실패: {e}")
        krx_df = pd.DataFrame()

load_krx_data()

@app.get("/")
def read_root():
    return {"status": "alive", "message": "재우의 데이터 공장 가동 중 ⚙️"}

# 2. 시장 지수 API (예외 처리 강화)
@app.get("/indices")
async def get_indices():
    def fetch():
        tickers = ["^KS11", "^KQ11", "^GSPC", "^IXIC"]
        # 안전하게 5일치 데이터를 가져옴 (주말/휴장 대비)
        data = yf.download(tickers, period="5d", interval="1d", progress=False)['Close']
        if data.empty or len(data) < 2:
            return None
        
        last_row = data.iloc[-1]
        prev_row = data.iloc[-2] # 전일 데이터
        
        indices = []
        names = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ", "^GSPC": "S&P 500", "^IXIC": "NASDAQ"}
        
        for ticker in tickers:
            curr = last_row[ticker]
            prev = prev_row[ticker]
            change = curr - prev
            pct = (change / prev) * 100
            indices.append({
                "name": names[ticker],
                "price": round(curr, 2),
                "change": round(change, 2),
                "pct": round(pct, 2)
            })
        return indices

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, fetch)
    
    if result:
        return {"status": "success", "data": result}
    return {"status": "error", "message": "지수 데이터를 가져올 수 없습니다."}

# 3. 실시간 환율 (크롤링 안정화)
@app.get("/exchange")
async def get_exchange_rate():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://finance.naver.com/marketindex/", headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        rate_str = soup.select_one(".exchange_grid .value").text # 더 정확한 선택자
        rate = float(rate_str.replace(",", ""))
        return {"status": "success", "rate": rate}
    except:
        return {"status": "success", "rate": 1400.0, "message": "기본 환율 적용"}

# 4. 배당 히스토리
@app.get("/dividend/{ticker}")
async def get_dividend_history(ticker: str):
    def fetch():
        stock = yf.Ticker(ticker)
        divs = stock.dividends
        if divs.empty: return None
        recent = divs.tail(5).sort_index(ascending=False)
        return [{"date": d.strftime("%Y-%m-%d"), "amount": f"{a:.4f}"} for d, a in recent.items()]

    loop = asyncio.get_event_loop()
    history = await loop.run_in_executor(executor, fetch)
    if history:
        return {"status": "success", "ticker": ticker, "history": history}
    return {"status": "error", "message": "배당 내역 없음"}

# 5. 한국 주식 검색 (메모리 최적화)
@app.get("/search/kr")
async def search_korean_stock(q: str):
    if krx_df.empty:
        return {"status": "error", "message": "데이터 로딩 중"}
    
    # 이름이나 코드에 검색어 포함 여부 확인
    mask = krx_df['Name'].str.contains(q, case=False, na=False) | krx_df['Code'].str.contains(q, na=False)
    filtered = krx_df[mask].head(10)
    
    results = []
    for _, row in filtered.iterrows():
        mkt = row.get('Market', 'KOSPI')
        suffix = ".KS" if mkt == "KOSPI" else ".KQ"
        results.append({
            "symbol": f"{row['Code']}{suffix}",
            "description": row['Name'],
            "type": "KOREA"
        })
    return {"status": "success", "result": results}

# 6. 한국 현재가 조회 (상승/하락 판별 로직 수정)
@app.get("/quote/kr/{ticker}")
async def get_kr_quote(ticker: str):
    try:
        code = ticker.split('.')[0]
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 현재가
        price = soup.select_one('.no_today .blind').text
        
        # 변동폭 및 색상 판별 (텍스트 포함 여부로 판별하는 것이 가장 안전함)
        exday = soup.select_one('.no_exday')
        is_up = "상승" in exday.text or "상한" in exday.text
        is_down = "하락" in exday.text or "하한" in exday.text
        
        blinds = exday.select('.blind')
        change_val = blinds[0].text if blinds else "0"
        change_pct = blinds[1].text if len(blinds) > 1 else "0"
        sign = "+" if is_up else ("-" if is_down else "")

        info = soup.select('.no_info td .blind')
        return {
            "status": "success",
            "price": price,
            "change": f"{sign}{change_val}",
            "change_percent": f"{sign}{change_pct}%",
            "prev_close": info[0].text,
            "high": info[1].text,
            "open": info[3].text,
            "low": info[4].text,
            "time": soup.select_one('.description .date').text if soup.select_one('.description .date') else "실시간",
            "is_positive": is_up,
            "is_negative": is_down
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
