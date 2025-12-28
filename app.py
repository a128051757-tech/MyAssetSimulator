import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面設定 ---
st.set_page_config(page_title="全方位資產成長模擬器 (信貸還款完整版)", layout="wide", page_icon="📈")

# 自定義 PMT 函數 (避免依賴 numpy_financial)
def calculate_pmt(rate, nper, pv):
    if rate == 0: return -(pv / nper)
    return -(pv * rate * (1 + rate)**nper) / ((1 + rate)**nper - 1)

# --- 2. 側邊欄：參數設定 ---
st.sidebar.header("⚙️ 模擬參數設定")

# (A) 時間設定
years_back = st.sidebar.slider("回測年數", 1, 20, 7)
end_date = datetime.now()
requested_start_date = end_date - timedelta(days=years_back*365)

# (B) 標的與配置
st.sidebar.subheader("📊 資產配置")
num_assets = st.sidebar.slider("選擇標的數量", 1, 5, 2)

assets = [] 
total_asset_weight = 0

for i in range(num_assets):
    col1, col2 = st.sidebar.columns([1, 2])
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

# (C) 資金與現金流
st.sidebar.subheader("💸 資金與現金流")
initial_capital = st.sidebar.number_input("初始自備本金 (不含信貸)", value=0, step=100000)
monthly_cashflow = st.sidebar.number_input(
    "📅 額外每月定期定額 (+存入/-提款)", 
    value=0, 
    step=5000, 
    help="除了信貸還款外，您每個月額外想存入(正數)或提領(負數)的金額"
)
cash_interest_rate = st.sidebar.number_input("💰 現金/短債年化報酬率 (%)", value=1.5, step=0.1) / 100

# (D) 信貸/槓桿設定
st.sidebar.subheader("🏦 信貸設定")
use_leverage = st.sidebar.checkbox("啟用信貸模擬", value=True)
loan_amount = 0.0
loan_rate = 0.0
loan_type = "只繳息 (Interest Only)"
loan_years = 7
monthly_payment = 0.0
repayment_source = "薪水/外部資金 (增加投入成本)"

if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸金額", value=1000000.0, step=100000.0)
    loan_rate = st.sidebar.number_input("借貸年利率 (%)", value=3.0, step=0.1) / 100
    
    loan_type = st.sidebar.radio("還款模式", ["只繳息 (Interest Only)", "本利攤還 (Amortized)"], index=1)
    
    if loan_type == "本利攤還 (Amortized)":
        loan_years = st.sidebar.slider("還款年限 (年)", 1, 30, 7)
        monthly_rate = loan_rate / 12
        n_periods = loan_years * 12
        monthly_payment = -calculate_pmt(monthly_rate, n_periods, loan_amount)
        st.sidebar.success(f"📅 每月需還款: ${int(monthly_payment):,}")
        
        repayment_source = st.sidebar.selectbox(
            "還款資金來源", 
            ["薪水/外部資金 (增加投入成本)", "投資組合/賣股 (不增加投入成本)"]
        )
    else:
        monthly_payment = loan_amount * (loan_rate / 12)
        st.sidebar.info(f"📅 每月繳息: ${int(monthly_payment):,}")

# (E) 再平衡策略
st.sidebar.subheader("⚖️ 再平衡策略")
rebalance_mode = st.sidebar.selectbox("再平衡頻率", ["每月 (Monthly)", "每年 (Yearly)", "不進行 (Buy & Hold)"], index=1)
threshold_mode = st.sidebar.checkbox("啟用偏移閾值 (Threshold)")
threshold_pct = 0.05
if threshold_mode:
    threshold_pct = st.sidebar.slider("容許偏移值 (%)", 1, 20, 5) / 100

# --- 3. 核心函數 ---
def get_data_safe(ticker_list, start, end):
    try:
        df = yf.download(ticker_list, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty: return pd.DataFrame()
        target_col = 'Adj Close' if 'Adj Close' in df.columns else ('Close' if 'Close' in df.columns else None)
        if not target_col: return pd.DataFrame()
        data = df[target_col]
        if isinstance(data, pd.Series):
            data = data.to_frame(); data.columns = ticker_list
        elif isinstance(data, pd.DataFrame):
            if len(ticker_list) == 1 and len(data.columns) == 1: data.columns = ticker_list
        return data.ffill().dropna()
    except Exception as e:
        return pd.DataFrame()
# --- 4. 主程式邏輯 ---
st.title("📈 全方位資產成長模擬器 (還款邏輯修復版)")

# Session State 初始化
if 'simulation_done' not in st.session_state: st.session_state.simulation_done = False
if 'df_res' not in st.session_state: st.session_state.df_res = None
if 'raw_data' not in st.session_state: st.session_state.raw_data = None

if st.button("🚀 開始模擬運算", type="primary"):
    if weight_cash < 0: st.error("配置權重超過 100%！")
    elif not assets: st.error("請至少輸入一檔標的。")
    else:
        with st.spinner('正在計算信貸現金流與回測...'):
            ticker_list = [a['ticker'] for a in assets]
            data = get_data_safe(ticker_list, requested_start_date, end_date)
            
            if data.empty:
                st.error("❌ 無法取得資料，請檢查代號。")
            else:
                st.session_state.raw_data = data
                
                # 初始化
                start_total_assets = initial_capital + loan_amount
                current_cash = start_total_assets * (weight_cash / 100)
                current_loan_balance = loan_amount
                
                shares = {}
                first_prices = data.iloc[0]
                
                for asset in assets:
                    t = asset['ticker']
                    price = first_prices[t]
                    if pd.isna(price) or price <= 0: price = data[t].dropna().iloc[0]
                    shares[t] = (start_total_assets * asset['weight']) / price

                history = []
                total_invested = initial_capital
                
                # --- 修正重點：月份偵測變數 ---
                last_month = None
                
                # 逐日回測
                for date, row in data.iterrows():
                    current_cash += current_cash * (cash_interest_rate / 365)
                    
                    # --- 修正重點：更精準的月初判斷 (不管1號是不是假日都會觸發) ---
                    current_month = date.month
                    is_new_month = False
                    if last_month is None:
                        last_month = current_month
                    elif current_month != last_month:
                        is_new_month = True
                        last_month = current_month
                    
                    # 只有在「換月」的第一個交易日執行扣款
                    if is_new_month:
                        current_cash += monthly_cashflow
                        if monthly_cashflow > 0:
                            total_invested += monthly_cashflow
                        
                        if use_leverage and current_loan_balance > 0:
                            interest_payment = current_loan_balance * (loan_rate / 12)
                            
                            if loan_type == "只繳息 (Interest Only)":
                                payment_now = interest_payment
                                principal_payment = 0
                            else:
                                payment_now = monthly_payment
                                principal_payment = payment_now - interest_payment
                                if principal_payment > current_loan_balance:
                                    principal_payment = current_loan_balance
                                    payment_now = principal_payment + interest_payment

                            if repayment_source == "薪水/外部資金 (增加投入成本)":
                                total_invested += payment_now
                                current_loan_balance -= principal_payment
                            else:
                                current_cash -= payment_now
                                current_loan_balance -= principal_payment
                    
                    stock_val = 0
                    asset_vals = {}
                    for t in ticker_list:
                        if t in row:
                            val = shares[t] * row[t]
                            asset_vals[t] = val
                            stock_val += val
                    
                    total_assets = current_cash + stock_val
                    net_worth = total_assets - current_loan_balance

                    do_rebalance = False
                    if current_cash < 0: do_rebalance = True 
                    # 這裡也要同步修正：使用 is_new_month 來觸發再平衡
                    if rebalance_mode == "每月 (Monthly)" and is_new_month: do_rebalance = True
                    elif rebalance_mode == "每年 (Yearly)" and date.is_year_start: do_rebalance = True
                    
                    if threshold_mode and total_assets > 0:
                        for asset in assets:
                            t = asset['ticker']
                            if t in asset_vals:
                                target = asset['weight']
                                curr_w = asset_vals[t] / total_assets
                                if abs(curr_w - target) > threshold_pct:
                                    do_rebalance = True; break
                    
                    if do_rebalance and total_assets > 0:
                        cost_stock = 0
                        for asset in assets:
                            t = asset['ticker']
                            if t in row:
                                target_val = total_assets * asset['weight']
                                shares[t] = target_val / row[t]
                                cost_stock += target_val
                        current_cash = total_assets - cost_stock

                    history.append({
                        "Date": date, 
                        "Net Worth": net_worth, 
                        "Total Invested": total_invested, 
                        "Loan Balance": current_loan_balance,
                        "Cash": current_cash
                    })

                st.session_state.df_res = pd.DataFrame(history)
                st.session_state.simulation_done = True
                st.rerun()


# --- 顯示結果與進階分析 ---
if st.session_state.simulation_done and st.session_state.df_res is not None:
    df_res = st.session_state.df_res
    data = st.session_state.raw_data
    
    final_nav = df_res.iloc[-1]['Net Worth']
    final_inv = df_res.iloc[-1]['Total Invested']
    final_loan = df_res.iloc[-1]['Loan Balance']
    profit = final_nav - final_inv
    roi = (profit/final_inv)*100 if final_inv>0 else 0
    
    st.markdown("### 📊 回測結果摘要")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最終淨資產 (扣除信貸)", f"${int(final_nav):,}")
    c2.metric("總投入本金 (含還款)", f"${int(final_inv):,}")
    c3.metric("剩餘信貸本金", f"${int(final_loan):,}")
    c4.metric("總損益 (ROI)", f"${int(profit):,}", f"{roi:.2f}%")

    fig = px.line(df_res, x="Date", y=["Net Worth", "Total Invested", "Loan Balance"], 
                  title="淨值成長 vs 投入成本 vs 信貸餘額",
                  color_discrete_map={"Net Worth": "red", "Total Invested": "gray", "Loan Balance": "blue"})
    st.plotly_chart(fig, use_container_width=True)
    
    # --- 滾動報酬 (Rolling Return) ---
    st.markdown("---")
    st.subheader("🔄 歷史滾動報酬分析 (Rolling Returns)")
    
    rc1, rc2 = st.columns(2)
    roll_years = rc1.slider("設定持有年數", 1, 10, 3) 
    target_return_pct = rc2.number_input("設定及格年化報酬 (%)", value=0.0, step=0.5) / 100
    
    window_days = int(roll_years * 252)
    if len(df_res) > window_days:
        df_res['Rolling_CAGR'] = (df_res['Net Worth'] / df_res['Net Worth'].shift(window_days)).pow(1/roll_years) - 1
        df_rolling = df_res.dropna(subset=['Rolling_CAGR'])
        
        win_rate = (df_rolling['Rolling_CAGR'] > target_return_pct).mean() * 100
        avg_ret = df_rolling['Rolling_CAGR'].mean() * 100
        min_ret = df_rolling['Rolling_CAGR'].min() * 100
        
        m1, m2, m3 = st.columns(3)
        m1.metric(f"持有 {roll_years} 年勝率", f"{win_rate:.1f}%")
        m2.metric("平均年化報酬", f"{avg_ret:.2f}%")
        m3.metric("最差年化報酬", f"{min_ret:.2f}%")
        
        fig_roll = px.line(df_rolling, x="Date", y="Rolling_CAGR", title=f"滾動 {roll_years} 年化報酬率")
        fig_roll.add_hline(y=target_return_pct, line_dash="dash", line_color="red")
        fig_roll.layout.yaxis.tickformat = ',.1%'
        st.plotly_chart(fig_roll, use_container_width=True)
    else:
        st.warning("資料長度不足以計算此年數的滾動報酬。")

    # --- 蒙地卡羅 (Monte Carlo) ---
    st.markdown("---")
    st.subheader("🎲 蒙地卡羅壓力測試")
    st.info("註：此壓力測試主要模擬「資產組合本身的波動風險」，信貸還款部分採簡化估算。")
    
    mc1, mc2 = st.columns(2)
    sim_years = mc1.number_input("預測未來年數", value=10)
    sim_count = mc2.number_input("模擬次數", value=100)
    
    if st.button("開始壓力測試"):
        with st.spinner("正在運算..."):
            daily_returns = data.pct_change().dropna()
            ticker_list = [a['ticker'] for a in assets]
            valid_cols = [c for c in ticker_list if c in daily_returns.columns]
            
            if valid_cols:
                daily_returns = daily_returns[valid_cols]
                weighted_ret = daily_returns.mean(axis=1) # 簡化假設
                
                sim_days = sim_years * 252
                success_count = 0
                fig_mc = go.Figure()
                
                for i in range(sim_count):
                    random_rets = weighted_ret.sample(n=sim_days, replace=True).values
                    nav = initial_capital # 蒙地卡羅僅模擬淨值波動，不詳細計算複雜本利攤還
                    survived = True
                    path = [nav]
                    
                    for d in range(sim_days):
                        nav = nav * (1 + random_rets[d])
                        # 簡單現金流模擬
                        if (d+1) % 21 == 0:
                            nav += monthly_cashflow
                            # 若有信貸，模擬每月扣息風險
                            if use_leverage: 
                                nav -= (loan_amount * loan_rate / 12)
                        
                        if nav <= 0:
                            nav = 0; survived = False; path.append(0); break
                        path.append(nav)
                    
                    if survived: success_count += 1
                    if i < 50:
                        fig_mc.add_trace(go.Scatter(y=path, mode='lines', line=dict(width=1, color='rgba(200,200,200,0.5)'), showlegend=False))
                
                rate = (success_count / sim_count) * 100
                st.metric("模擬成功率", f"{rate:.1f}%")
                st.plotly_chart(fig_mc, use_container_width=True)
