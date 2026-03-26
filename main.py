import os
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from bs4 import BeautifulSoup

# --- ⚙️ 초기 설정 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

app = FastAPI()

# Supabase 클라이언트 시동
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# KRX 데이터 로드용 전역 변수
krx_df = pd.DataFrame()

@app.on_event("startup")
def load_startup_data():
    global krx_df
    try:
        krx_df = fdr.StockListing('KRX')
        print(f"✅ KRX 로딩 완료! (총 {len(krx_df)}개)")
    except Exception as e:
        print(f"❌ KRX 로딩 실패: {e}")

# --- 헬퍼 함수: NaN(에러 숫자) 제거 ---
def clean_nan(obj):
    """JSON 전송 시 에러를 유발하는 NaN 값을 None으로 변환"""
    if isinstance(obj, list):
        return [clean_nan(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, float) and np.isnan(obj):
        return None
    return obj

# --- 🚀 핵심 시스템 통로 (DB 연결) ---

@app.get("/")
def read_root():
    return {"status": "alive", "message": "재우의 데이터 공장 가동 중 ⚙️"}

@app.get("/ping")
def ping():
    return "ok"

# 🐋 뉴스/고래 데이터 입구 (DB에 진짜 저장)
@app.post("/update_intel")
async def update_intel(data: dict):
    try:
        # 1. 수집 시간 기록 및 NaN 제거
        data['timestamp'] = datetime.now().strftime("%H:%M")
        clean_data = clean_nan(data)
        
        # 2. 🚨 DB(Supabase)에 직접 입고
        # 'intel_data' 테이블에 한 줄 추가해!
        res = supabase.table("intel_data").insert(clean_data).execute()
        
        print(f"✅ DB 입고 성공: {clean_data.get('title', clean_data.get('symbol'))[:15]}...")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ DB 저장 실패: {e}")
        return {"status": "error", "message": str(e)}

# 📡 웹사이트용 데이터 출구 (DB에서 데이터 꺼내오기)
@app.get("/get_intel")
async def get_intel():
    try:
        # 3. 🚨 주머니(메모리)가 아니라 창고(DB)에서 최신 20개 가져와!
        res = supabase.table("intel_data")\
            .select("*")\
            .order("id", desc=True)\
            .limit(20)\
            .execute()
            
        return {"status": "success", "data": res.data}
    except Exception as e:
        print(f"❌ DB 조회 실패: {e}")
        return {"status": "error", "data": []}

# --- 📊 주식 정보 API (기존 기능 유지) ---

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
    # 🚨 여기서도 NaN 에러 방지를 위해 클리닝
    return {"status": "success", "data": clean_nan(indices)}

@app.get("/exchange")
def get_exchange_rate():
    try:
        url = "https://finance.naver.com/marketindex/"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        rate_text = soup.select_one(".value").text.replace(",", "")
        return {"status": "success", "rate": float(rate_text)}
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
