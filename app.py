import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# --- 頁面設定 ---
st.set_page_config(page_title="多資產成長模擬器 Pro+ (穩定版)", layout="wide", page_icon="📈")

# --- 側邊欄：參數設定 ---
st.sidebar.header("⚙️ 模擬參數設定")

# 1. 時間設定
years_back = st.sidebar.slider("回測年數", 1, 20, 5)
end_date = datetime.now()
requested_start_date = end_date - timedelta(days=years_back*365)

# 2. 標的與配置
st.sidebar.subheader("📊 資產配置")
num_assets = st.sidebar.slider("選擇標的數量", 1, 5, 2)

assets = [] 
total_asset_weight = 0

for i in range(num_assets):
    col1, col2 = st.sidebar.columns([1, 2])
    # 預設值
    default_ticker = "00662.TW" if i == 0 else ("00670L.TW" if i == 1 else "")
    default_weight = 40 if i == 0 else (30 if i == 1 else 10)
    
    with col1:
        ticker = st.text_input(f"標的 {i+1} 代號", default_ticker, key=f"t_{i}")
    with col2:
        weight = st.slider(f"配置 %", 0, 100, default_weight, key=f"w_{i}")
    
    if ticker:
        clean_ticker = ticker.strip().upper()
        assets.append({'ticker': clean_ticker, 'weight': weight / 100})
        total_asset_weight += weight

weight_cash = 100 - total_asset_weight
if weight_cash < 0:
    st.sidebar.error(f"⚠️ 警告：配置總和 {total_asset_weight}% 超過 100%！")
else:
    st.sidebar.info(f"💰 現金/短債部位: {weight_cash}%")

# 3. 資金與其他參數
st.sidebar.subheader("💸 資金投入")
initial_capital = st.sidebar.number_input("初始本金", value=1000000, step=100000)
monthly_contribution = st.sidebar.number_input("每月定期定額", value=20000, step=5000)
cash_interest_rate = st.sidebar.number_input("現金年化報酬率 (%)", value=1.5, step=0.1) / 100

st.sidebar.subheader("⚙️ 進階設定")
use_leverage = st.sidebar.checkbox("啟用信貸/質押")
loan_amount = 0.0
loan_rate = 0.0
if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸", value=0.0)
    loan_rate = st.sidebar.number_input("借貸利率 (%)", value=2.5) / 100

rebalance_mode = st.sidebar.selectbox("再平衡頻率", ["每月 (Monthly)", "每年 (Yearly)", "不進行"])
threshold_mode = st.sidebar.checkbox("啟用偏移閾值")
threshold_pct = 0.05
if threshold_mode:
    threshold_pct = st.sidebar.slider("容許值 (%)", 1, 20, 5) / 100

# --- 核心函數：下載數據 (修復 KeyError 問題) ---
def get_data_safe(ticker_list, start, end):
    try:
        # 1. 嘗試下載，強制 auto_adjust=False 以保留原始欄位結構
        df = yf.download(ticker_list, start=start, end=end, progress=False, auto_adjust=False)
        
        if df.empty:
            return pd.DataFrame()

        # 2. 判斷並提取股價數據 (解決 KeyError: 'Adj Close')
        target_col = None
        
        # 檢查欄位結構 (MultiIndex 或是 Flat Index)
        # 優先找 Adj Close
        if 'Adj Close' in df.columns:
            target_col = 'Adj Close'
        elif 'Close' in df.columns:
            target_col = 'Close'
            st.toast("⚠️ 提示：找不到 'Adj Close'，系統自動改用 'Close' 進行計算。", icon="ℹ️")
        else:
            # 萬一真的都沒有，嘗試直接抓取第一層數據 (極端情況)
            st.error("錯誤：下載的資料中沒有收盤價欄位。")
            return pd.DataFrame()

        # 提取數據
        data = df[target_col]

        # 3. 格式標準化 (處理單檔 vs 多檔的差異)
        if isinstance(data, pd.Series):
            # 如果是 Series (單檔)，轉成 DataFrame 並重新命名欄位
            data = data.to_frame()
            data.columns = ticker_list
        elif isinstance(data, pd.DataFrame):
            # 如果是 DataFrame，確保欄位名稱正確
            if len(ticker_list) == 1 and len(data.columns) == 1:
                 data.columns = ticker_list
        
        # 4. 補值與清洗
        data = data.ffill() # 補前值
        data = data.dropna() # 刪除仍為空的行
        
        return data

    except Exception as e:
        st.error(f"數據處理發生錯誤: {e}")
        return pd.DataFrame()

# --- 主程式 ---
st.title("📈 多資產成長模擬器 Pro+ (穩定版)")

if st.button("🚀 開始模擬", type="primary"):
    if weight_cash < 0:
        st.error("配置超過 100%！")
    elif not assets:
        st.error("請輸入標的。")
    else:
        with st.spinner('正在下載並修復資料...'):
            ticker_list = [a['ticker'] for a in assets]
            
            # 使用新的安全下載函數
            data = get_data_safe(ticker_list, requested_start_date, end_date)
            
            if data.empty:
                st.error(f"❌ 無法取得資料。請確認股票代號 {ticker_list} 是否正確 (台股需加 .TW)。")
            else:
                # 顯示實際開始日期
                actual_start = data.index[0]
                # 簡單的時間比較 (去除時區資訊以免報錯)
                act_ts = actual_start.tz_localize(None) if actual_start.tzinfo else actual_start
                req_ts = pd.Timestamp(requested_start_date).tz_localize(None)

                if act_ts > req_ts:
                    st.warning(f"⚠️ 資料起始日自動調整為 **{actual_start.strftime('%Y-%m-%d')}** (以數據最完整的日期為準)")

                # 初始化
                current_cash = (initial_capital + loan_amount) * (weight_cash / 100)
                shares = {}
                
                # 建倉
                first_prices = data.iloc[0]
                valid_simulation = True
                
                for asset in assets:
                    t = asset['ticker']
                    # 防呆：確認該股票在資料中
                    if t not in data.columns:
                        st.error(f"錯誤：資料中遺失 {t} 的欄位，請檢查代號。")
                        valid_simulation = False
                        break
                    
                    price = first_prices[t]
                    if pd.isna(price) or price <= 0:
                        price = data[t].dropna().iloc[0] # 往後找有效價格
                        
                    shares[t] = ((initial_capital + loan_amount) * asset['weight']) / price

                if valid_simulation:
                    history = []
                    monthly_rate = loan_rate / 12
                    total_invested = initial_capital
                    
                    for date, row in data.iterrows():
                        # A. 現金生息
                        current_cash += current_cash * (cash_interest_rate / 365)
                        
                        # B. 月初事件
                        if date.is_month_start:
                            if monthly_contribution > 0:
                                current_cash += monthly_contribution
                                total_invested += monthly_contribution
                            if use_leverage:
                                current_cash -= (loan_amount * monthly_rate)

                        # C. 計算市值
                        stock_val = 0
                        asset_vals = {}
                        for t in ticker_list:
                            # 再次確認欄位存在
                            if t in row:
                                val = shares[t] * row[t]
                                asset_vals[t] = val
                                stock_val += val
                        
                        total_assets = current_cash + stock_val
                        net_worth = total_assets - loan_amount

                        # D. 再平衡
                        do_rebalance = False
                        if rebalance_mode == "每月 (Monthly)" and date.is_month_start: do_rebalance = True
                        elif rebalance_mode == "每年 (Yearly)" and date.is_year_start: do_rebalance = True
                        
                        if threshold_mode and total_assets > 0:
                            for asset in assets:
                                t = asset['ticker']
                                if t in asset_vals:
                                    target = asset['weight']
                                    curr_w = asset_vals[t] / total_assets
                                    if abs(curr_w - target) > threshold_pct:
                                        do_rebalance = True
                                        break
                        
                        if do_rebalance and total_assets > 0:
                            cost_stock = 0
                            for asset in assets:
                                t = asset['ticker']
                                if t in row:
                                    target_val = total_assets * asset['weight']
                                    shares[t] = target_val / row[t]
                                    cost_stock += target_val
                            current_cash = total_assets - cost_stock

                        # E. 記錄
                        rec = {"Date": date, "Net Worth": net_worth, "Total Invested": total_invested, "Cash": current_cash}
                        history.append(rec)

                    # 繪圖
                    df_res = pd.DataFrame(history)
                    if not df_res.empty:
                        final_nav = df_res.iloc[-1]['Net Worth']
                        final_inv = df_res.iloc[-1]['Total Invested']
                        profit = final_nav - final_inv
                        roi = (profit/final_inv)*100 if final_inv>0 else 0

                        c1, c2, c3 = st.columns(3)
                        c1.metric("最終淨資產", f"${int(final_nav):,}")
                        c2.metric("總投入本金", f"${int(final_inv):,}")
                        c3.metric("總損益 (ROI)", f"${int(profit):,}", f"{roi:.2f}%")

                        fig = px.line(df_res, x="Date", y=["Net Worth", "Total Invested"], 
                                      color_discrete_map={"Net Worth": "red", "Total Invested": "gray"})
                        st.plotly_chart(fig, use_container_width=True)
                        
                        with st.expander("詳細數據"):
                            st.dataframe(df_res.sort_values("Date", ascending=False))
