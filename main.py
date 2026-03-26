from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 글로벌 데이터 저장소
krx_df = pd.DataFrame()
# --- [신규 추가] 고래 & 뉴스 데이터 창고 ---
# 실제 운영 환경에서는 DB를 써야 하지만, 우선 서버가 켜져 있는 동안 유지되는 메모리 저장소를 씁니다.
whale_storage = [] 
MAX_STORAGE_SIZE = 50 # 최신 데이터 50개까지만 보관

# 1. 고래(내부자 거래) 데이터를 받는 입구 (POST)
# 네 whale_tracker.py에서 이 주소로 데이터를 쏴줄 거야.
@app.post("/update_whales")
async def update_whales(data: dict):
    global whale_storage
    # 새로운 데이터를 리스트 맨 앞에 추가 (최신순)
    whale_storage.insert(0, data)
    
    # 너무 많이 쌓이면 오래된 건 삭제
    if len(whale_storage) > MAX_STORAGE_SIZE:
        whale_storage.pop()
    
    print(f"🐋 새로운 고래 포착: {data.get('symbol')}")
    return {"status": "success", "message": "창고에 저장 완료"}

# 2. 저장된 데이터를 웹사이트에 주는 출구 (GET)
@app.get("/get_whales")
def get_whales():
    return {"status": "success", "data": whale_storage}

# 🚀 서버가 켜질 때 안전하게 백그라운드에서 데이터를 로드하는 공식 방법
@app.on_event("startup")
def load_startup_data():
    global krx_df
    print("🚀 KRX 주식 목록 로딩 시작...")
    try:
        krx_df = fdr.StockListing('KRX')
        print(f"✅ 로딩 완료! (총 {len(krx_df)}개 종목)")
    except Exception as e:
        print(f"❌ 로딩 실패: {e}")

# 1. 루트 경로 (상태 확인용 JSON 반환)
@app.get("/")
def read_root():
    return {"status": "alive", "message": "재우의 데이터 공장 가동 중 ⚙️"}

# 🚨 [신규 추가] 10분마다 서버를 깨우기 위한 초경량 전용 엔드포인트
# 스케줄러(Cron-job 등)에서 이 주소를 호출하면 'output too large' 에러가 사라집니다.
@app.get("/ping")
def ping():
    return "ok"

# 2. 시장 지수 API (ETF 우회 타격 방식 - 절대 에러가 나지 않음)
@app.get("/indices")
def get_indices():
    tickers = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ", "SPY": "S&P 500", "QQQ": "NASDAQ"}
    indices = []
    
    for ticker, name in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            
            if len(hist) >= 2:
                curr = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2])
                change = curr - prev
                pct = (change / prev) * 100
                
                indices.append({
                    "name": name,
                    "symbol": ticker,
                    "price": round(curr, 2),
                    "change": round(change, 2),
                    "pct": round(pct, 2)
                })
        except Exception as e:
            print(f"{name} 로드 실패: {e}")
            continue
            
    if indices:
        return {"status": "success", "data": indices}
    else:
        return {"status": "error", "message": "모든 지수 로드 실패"}

# 3. 실시간 환율 API
@app.get("/exchange")
def get_exchange_rate():
    try:
        url = "https://finance.naver.com/marketindex/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        
        rate_str = soup.select_one("#exchangeList > li.on > a.head.usd > div > span.value").text
        rate = float(rate_str.replace(",", ""))
        return {"status": "success", "rate": rate}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 4. 배당 히스토리 API
@app.get("/dividend/{ticker}")
def get_dividend_history(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
        if dividends.empty:
            return {"status": "error", "message": "배당 내역이 없습니다."}
        
        recent_divs = dividends.tail(5).sort_index(ascending=False)
        history = [{"date": d.strftime("%Y-%m-%d"), "amount": f"{a:.4f}"} for d, a in recent_divs.items()]
        return {"status": "success", "ticker": ticker, "history": history}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 5. 한국 주식 검색 API
@app.get("/search/kr")
def search_korean_stock(q: str):
    if krx_df.empty:
        return {"status": "error", "message": "데이터 로딩 중입니다. 잠시 후 다시 시도하세요."}
    try:
        mask = krx_df['Name'].str.contains(q, case=False, na=False) | krx_df['Code'].str.contains(q, na=False)
        filtered = krx_df[mask].head(10)
        
        results = []
        for _, row in filtered.iterrows():
            market = row.get('Market', 'KOSPI')
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            results.append({
                "symbol": f"{row['Code']}{suffix}",
                "description": row['Name'],
                "type": "KOREA"
            })
        return {"status": "success", "result": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 6. 한국 주식 현재가 상세 조회
@app.get("/quote/kr/{ticker}")
def get_kr_quote(ticker: str):
    try:
        code = ticker.split('.')[0]
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        
        today_price = soup.select_one('.no_today .blind').text
        exday = soup.select_one('.no_exday')
        
        ex_text = exday.text if exday else ""
        is_up = "상승" in ex_text or "상한" in ex_text or "+" in ex_text
        is_down = "하락" in ex_text or "하한" in ex_text or "-" in ex_text
        
        blinds = exday.select('.blind') if exday else []
        change_val = blinds[0].text if len(blinds) > 0 else "0"
        change_pct = blinds[1].text if len(blinds) > 1 else "0"
        sign = "+" if is_up else ("-" if is_down else "")

        info_tds = soup.select('.no_info td .blind')
        return {
            "status": "success",
            "price": today_price,
            "change": f"{sign}{change_val}",
            "change_percent": f"{sign}{change_pct}%",
            "prev_close": info_tds[0].text if len(info_tds) > 0 else "0",
            "high": info_tds[1].text if len(info_tds) > 1 else "0",
            "open": info_tds[3].text if len(info_tds) > 3 else "0",
            "low": info_tds[4].text if len(info_tds) > 4 else "0",
            "time": soup.select_one('.description .date').text if soup.select_one('.description .date') else "실시간",
            "is_positive": is_up,
            "is_negative": is_down
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
