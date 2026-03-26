from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client  # 1. 도구 가져오기

# 2. 금고에서 열쇠 꺼내기 (환경 변수)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

app = FastAPI()

# CORS 설정 (프론트엔드와 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 📦 1. 데이터 창고 (Server Warehouse) ---
# 서버가 켜져 있는 동안 고래 데이터를 저장하는 메모리 공간이야.
intel_storage = [] 
MAX_INTEL_SIZE = 50 # 최신 데이터 50개까지만 보관

# 글로벌 주식 데이터 로드
krx_df = pd.DataFrame()

@app.on_event("startup")
def load_startup_data():
    global krx_df
    try:
        krx_df = fdr.StockListing('KRX')
        print(f"✅ KRX 로딩 완료! (총 {len(krx_df)}개)")
    except Exception as e:
        print(f"❌ KRX 로딩 실패: {e}")

# --- 🚀 2. 시스템 통로 (System Endpoints) ---

@app.get("/")
def read_root():
    return {"status": "alive", "message": "재우의 데이터 공장 가동 중 ⚙️"}

# 🚨 스케줄러 'output too large' 에러 해결용 초경량 통로
@app.get("/ping")
def ping():
    return "ok"

# 🐋 고래 데이터 입구 (봇이 데이터를 쏘는 곳)
@app.post("/update_intel")
async def update_intel(data: dict):
    global intel_storage
    data['timestamp'] = datetime.now().strftime("%H:%M") # 수집 시간 기록
    
    # 중복 데이터 체크 (티커와 금액이 같으면 무시)
    if any(i.get('symbol') == data.get('symbol') and i.get('value') == data.get('value') for i in intel_storage):
        return {"status": "ignored"}

    intel_storage.insert(0, data) # 최신 데이터를 맨 앞으로
    if len(intel_storage) > MAX_INTEL_SIZE:
        intel_storage.pop()
    
    print(f"🐋 창고 입고 성공: {data.get('symbol')}")
    return {"status": "success"}

# 📡 웹사이트용 데이터 출구 (브라우저가 데이터를 가져가는 곳)
@app.get("/get_intel")
def get_intel():
    return {"status": "success", "data": intel_storage[:10]}

# --- 📊 3. 기존 주식 API 기능들 (유지) ---

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
                indices.append({
                    "name": name, "symbol": ticker,
                    "price": round(curr, 2), "change": round(change, 2), "pct": round((change/prev)*100, 2)
                })
        except: continue
    return {"status": "success", "data": indices}

@app.get("/exchange")
def get_exchange_rate():
    try:
        url = "https://finance.naver.com/marketindex/"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        rate = float(soup.select_one(".value").text.replace(",", ""))
        return {"status": "success", "rate": rate}
    except: return {"status": "error"}

@app.get("/dividend/{ticker}")
def get_dividend_history(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        divs = stock.dividends
        if divs.empty: return {"status": "error", "message": "없음"}
        history = [{"date": d.strftime("%Y-%m-%d"), "amount": f"{a:.4f}"} for d, a in divs.tail(5).sort_index(ascending=False).items()]
        return {"status": "success", "history": history}
    except: return {"status": "error"}

@app.get("/search/kr")
def search_korean_stock(q: str):
    if krx_df.empty: return {"status": "error"}
    mask = krx_df['Name'].str.contains(q, case=False, na=False) | krx_df['Code'].str.contains(q, na=False)
    filtered = krx_df[mask].head(10)
    results = [{"symbol": f"{r['Code']}{'.KS' if r['Market']=='KOSPI' else '.KQ'}", "description": r['Name']} for _, r in filtered.iterrows()]
    return {"status": "success", "result": results}

@app.get("/quote/kr/{ticker}")
def get_kr_quote(ticker: str):
    try:
        code = ticker.split('.')[0]
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        price = soup.select_one('.no_today .blind').text
        return {"status": "success", "price": price}
    except: return {"status": "error"}
