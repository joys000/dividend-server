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

# main.py에 추가
@app.get("/")
async def health_check():

    return {"status": "alive", "message": "서버가 깨어있습니다!"}

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
    # 🚨 main.py 파일의 가장 아랫부분에 이 코드를 추가하고 깃허브에 Push(배포) 하십시오.

@app.get("/quote/kr/{ticker}")
async def get_kr_quote(ticker: str):
    try:
        # 티커에서 숫자 6자리만 추출 (예: 005930.KS -> 005930)
        code = ticker.split('.')[0]
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        
        # 봇 차단을 막기 위한 User-Agent 설정
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 1. 현재가 추출
        today_price = soup.select_one('.no_today .blind').text
        
        # 2. 전일대비 변동 및 부호 추출
        exday = soup.select_one('.no_exday')
        blinds = exday.select('.blind')
        change_val = blinds[0].text if len(blinds) > 0 else "0"
        change_pct = blinds[1].text if len(blinds) > 1 else "0"
        
        # 상승/하락 판별 (클래스명으로 판별)
        is_up = "up" in exday.get('class', []) or "red02" in exday.parent.get('class', [])
        is_down = "down" in exday.get('class', []) or "nv01" in exday.parent.get('class', [])
        sign = "+" if is_up else ("-" if is_down else "")

        # 3. 전일가, 고가, 시가, 저가 추출
        info_tds = soup.select('.no_info td .blind')
        prev_close = info_tds[0].text
        high = info_tds[1].text
        open_val = info_tds[3].text
        low = info_tds[4].text
        
        # 4. 기준 시간 추출 (예: 2026.03.25 12:00 기준)
        time_info_el = soup.select_one('.description .date')
        time_info = time_info_el.text if time_info_el else "실시간"

        return {
            "status": "success",
            "price": today_price,
            "change": f"{sign}{change_val}",
            "change_percent": f"{sign}{change_pct}%",
            "prev_close": prev_close,
            "high": high,
            "open": open_val,
            "low": low,
            "time": time_info,
            "is_positive": is_up,
            "is_negative": is_down
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
