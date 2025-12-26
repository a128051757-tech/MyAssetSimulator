import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# --- 頁面設定 ---
st.set_page_config(page_title="資產成長模擬器 Pro", layout="wide", page_icon="📈")

# --- 側邊欄：參數設定 ---
st.sidebar.header("⚙️ 模擬參數設定")

# 1. 時間設定
years_back = st.sidebar.slider("回測年數", 1, 10, 5)
end_date = datetime.now()
start_date = end_date - timedelta(days=years_back*365)

# 2. 標的與配置
st.sidebar.subheader("📊 資產配置 (總和需為 100%)")
ticker_1 = st.sidebar.text_input("標的 1 代號 (Yahoo)", "00662.TW")
weight_1 = st.sidebar.slider(f"{ticker_1} 配置 %", 0, 100, 40)

ticker_2 = st.sidebar.text_input("標的 2 代號", "00670L.TW")
weight_2 = st.sidebar.slider(f"{ticker_2} 配置 %", 0, 100, 30)

weight_cash = 100 - weight_1 - weight_2
st.sidebar.info(f"💰 現金/短債部位: {weight_cash}%")

# 3. 資金投入 (新增功能!)
st.sidebar.subheader("💸 資金投入")
initial_capital = st.sidebar.number_input("初始本金 (元)", value=1000000, step=100000)
monthly_contribution = st.sidebar.number_input("📅 每月定期定額 (元)", value=20000, step=5000, help="每個月初自動加入現金部位")

# 4. 槓桿設定
use_leverage = st.sidebar.checkbox("啟用信貸/質押模擬")
loan_amount = 0
loan_rate = 0
if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸金額", value=0, step=100000)
    loan_rate = st.sidebar.number_input("借貸年利率 (%)", value=2.5, step=0.1) / 100

# 5. 再平衡策略
st.sidebar.subheader("⚖️ 再平衡策略")
rebalance_mode = st.sidebar.selectbox("再平衡頻率", ["每月 (Monthly)", "每年 (Yearly)", "不進行 (Buy & Hold)"])
threshold_mode = st.sidebar.checkbox("啟用偏移閾值 (Threshold)")
threshold_pct = 0.05
if threshold_mode:
    threshold_pct = st.sidebar.slider("偏移容許值 (%)", 1, 20, 5) / 100

# --- 主程式邏輯 ---
st.title("📈 資產成長模擬器 (含定期定額)")

if st.button("🚀 開始模擬", type="primary"):
    with st.spinner('正在下載真實股價資料...'):
        try:
            tickers = [ticker_1, ticker_2]
            data = yf.download(tickers, start=start_date, end=end_date)['Adj Close']
            data = data.fillna(method='ffill')
            
            if data.empty:
                st.error("找不到資料，請檢查股票代號。")
            else:
                # 初始化
                # 總資產 = 本金 + 借貸
                current_cash = (initial_capital + loan_amount) * (weight_cash / 100)
                
                # 計算初始股數
                p1_start = data.iloc[0][ticker_1]
                p2_start = data.iloc[0][ticker_2]
                
                shares = {
                    ticker_1: (initial_capital + loan_amount) * (weight_1 / 100) / p1_start,
                    ticker_2: (initial_capital + loan_amount) * (weight_2 / 100) / p2_start
                }
                
                history = []
                monthly_rate = loan_rate / 12
                total_invested = initial_capital # 用來計算總投入成本 (本金 + 定期定額)
                
                # 開始回測
                for date, row in data.iterrows():
                    # 1. 處理月初事件 (定期定額 & 利息)
                    is_month_start = date.is_month_start
                    is_year_start = date.is_year_start
                    
                    if is_month_start:
                        # A. 注入定期定額資金
                        if monthly_contribution > 0:
                            current_cash += monthly_contribution
                            total_invested += monthly_contribution
                        
                        # B. 扣除借貸利息
                        if use_leverage:
                            current_cash -= (loan_amount * monthly_rate)

                    # 2. 計算當前市值
                    val_1 = shares[ticker_1] * row[ticker_1]
                    val_2 = shares[ticker_2] * row[ticker_2]
                    total_assets = current_cash + val_1 + val_2
                    net_worth = total_assets - loan_amount
                    
                    # 3. 判斷是否再平衡
                    do_rebalance = False
                    
                    # 頻率條件
                    if rebalance_mode == "每月 (Monthly)" and is_month_start:
                        do_rebalance = True
                    elif rebalance_mode == "每年 (Yearly)" and is_year_start:
                        do_rebalance = True
                    
                    # 閾值條件
                    if threshold_mode:
                        w1_curr = val_1 / total_assets if total_assets > 0 else 0
                        w2_curr = val_2 / total_assets if total_assets > 0 else 0
                        if abs(w1_curr - weight_1/100) > threshold_pct or abs(w2_curr - weight_2/100) > threshold_pct:
                            do_rebalance = True

                    # 4. 執行再平衡
                    if do_rebalance:
                        # 目標金額
                        target_v1 = total_assets * (weight_1 / 100)
                        target_v2 = total_assets * (weight_2 / 100)
                        
                        # 計算需買賣股數
                        shares[ticker_1] = target_v1 / row[ticker_1]
                        shares[ticker_2] = target_v2 / row[ticker_2]
                        
                        # 剩餘的就是現金
                        current_cash = total_assets - target_v1 - target_v2
                    
                    history.append({
                        "Date": date,
                        "Net Worth": net_worth,
                        "Total Invested": total_invested, # 記錄累計投入本金
                        "Cash": current_cash,
                        f"{ticker_1}": val_1,
                        f"{ticker_2}": val_2
                    })
                
                df = pd.DataFrame(history)
                
                # --- 結果展示 ---
                final_nav = df.iloc[-1]['Net Worth']
                final_invested = df.iloc[-1]['Total Invested']
                total_profit = final_nav - final_invested
                roi = (total_profit / final_invested) * 100 if final_invested > 0 else 0
                
                c1, c2, c3 = st.columns(3)
                c1.metric("最終淨資產", f"${int(final_nav):,}")
                c2.metric("總投入本金 (含定額)", f"${int(final_invested):,}")
                c3.metric("總損益 (ROI)", f"${int(total_profit):,}", f"{roi:.2f}%")
                
                st.subheader("資產累積走勢")
                # 畫出兩條線：淨值 vs 投入本金
                fig = px.line(df, x="Date", y=["Net Worth", "Total Invested"], 
                              labels={"value": "金額", "variable": "項目"},
                              color_discrete_map={"Net Worth": "red", "Total Invested": "gray"})
                st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("查看詳細數據"):
                    st.dataframe(df.sort_values("Date", ascending=False))

        except Exception as e:
            st.error(f"發生錯誤: {e}")
