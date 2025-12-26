import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# --- 頁面設定 ---
st.set_page_config(page_title="多資產成長模擬器 Pro+", layout="wide", page_icon="📈")

# --- 側邊欄：參數設定 ---
st.sidebar.header("⚙️ 模擬參數設定")

# 1. 時間設定
years_back = st.sidebar.slider("回測年數 (若超過上市日將自動調整)", 1, 20, 5)
end_date = datetime.now()
requested_start_date = end_date - timedelta(days=years_back*365)

# 2. 標的與配置 (動態生成 1~5 檔)
st.sidebar.subheader("📊 資產配置")
num_assets = st.sidebar.slider("選擇標的數量", 1, 5, 2)

assets = [] 
total_asset_weight = 0

for i in range(num_assets):
    col1, col2 = st.sidebar.columns([1, 2])
    # 預設值設定
    default_ticker = "00662.TW" if i == 0 else ("00670L.TW" if i == 1 else "")
    default_weight = 40 if i == 0 else (30 if i == 1 else 10)
    
    with col1:
        ticker = st.text_input(f"標的 {i+1} 代號", default_ticker, key=f"t_{i}")
    with col2:
        weight = st.slider(f"配置 %", 0, 100, default_weight, key=f"w_{i}")
    
    if ticker:
        # 移除空格並轉大寫，避免代號錯誤
        clean_ticker = ticker.strip().upper()
        assets.append({'ticker': clean_ticker, 'weight': weight / 100})
        total_asset_weight += weight

# 計算現金權重
weight_cash = 100 - total_asset_weight
if weight_cash < 0:
    st.sidebar.error(f"⚠️ 警告：目前配置總和為 {total_asset_weight}%，已超過 100%！請調整權重。")
else:
    st.sidebar.info(f"💰 現金/短債部位: {weight_cash}%")

# 3. 資金投入
st.sidebar.subheader("💸 資金投入")
initial_capital = st.sidebar.number_input("初始本金 (元)", value=1000000, step=100000)
monthly_contribution = st.sidebar.number_input("📅 每月定期定額 (元)", value=20000, step=5000)
cash_interest_rate = st.sidebar.number_input("💰 現金/短債年化報酬率 (%)", value=1.5, step=0.1) / 100

# 4. 槓桿設定
use_leverage = st.sidebar.checkbox("啟用信貸/質押模擬")
loan_amount = 0.0
loan_rate = 0.0
if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸金額", value=0.0, step=100000.0)
    loan_rate = st.sidebar.number_input("借貸年利率 (%)", value=2.5, step=0.1) / 100

# 5. 再平衡策略
st.sidebar.subheader("⚖️ 再平衡策略")
rebalance_mode = st.sidebar.selectbox("再平衡頻率", ["每月 (Monthly)", "每年 (Yearly)", "不進行 (Buy & Hold)"])
threshold_mode = st.sidebar.checkbox("啟用偏移閾值 (Threshold)")
threshold_pct = 0.05
if threshold_mode:
    threshold_pct = st.sidebar.slider("偏移容許值 (%)", 1, 20, 5) / 100

# --- 主程式邏輯 ---
st.title("📈 多資產成長模擬器 Pro+ (修復版)")

if st.button("🚀 開始模擬", type="primary"):
    if weight_cash < 0:
        st.error("無法執行：資產配置總和超過 100%。")
    elif not assets:
        st.error("請至少輸入一檔股票代號。")
    else:
        with st.spinner('正在下載並校正資料...'):
            try:
                # 1. 下載資料
                ticker_list = [a['ticker'] for a in assets]
                
                # --- 修正重點：處理 yfinance 下載格式問題 ---
                raw_data = yf.download(ticker_list, start=requested_start_date, end=end_date, progress=False)['Adj Close']
                
                # 如果只有一檔股票，yfinance 會回傳 Series 或沒有 column 名稱的 DataFrame
                # 這裡強制把它轉成以 ticker 為欄位的 DataFrame
                if isinstance(raw_data, pd.Series):
                    raw_data = raw_data.to_frame()
                    raw_data.columns = ticker_list
                elif isinstance(raw_data, pd.DataFrame) and len(ticker_list) == 1:
                    # 如果是 DataFrame 但只有一欄，確保欄位名稱正確
                    raw_data.columns = ticker_list
                
                # 2. 自動日期校正
                data = raw_data.dropna()
                
                if data.empty:
                    st.error(f"資料為空！請檢查股票代號 {ticker_list} 是否正確，或確認它們是否有重疊的上市時間。")
                else:
                    # 抓取實際開始日期
                    actual_start_date = data.index[0]
                    
                    # 判斷日期 (兼容性寫法)
                    req_start_ts = pd.Timestamp(requested_start_date).tz_localize(None)
                    act_start_ts = actual_start_date.tz_localize(None) if actual_start_date.tzinfo else actual_start_date
                    
                    if act_start_ts > req_start_ts:
                        st.warning(f"⚠️ 注意：回測起始日已自動調整為 **{actual_start_date.strftime('%Y-%m-%d')}** (所有標的皆有數據的日期)。")
                    
                    # 3. 初始化模擬
                    current_cash = (initial_capital + loan_amount) * (weight_cash / 100)
                    
                    shares = {}
                    # 確保取出的價格是 Series 格式 (即便只有一行)
                    first_prices = data.iloc[0]
                    
                    for asset in assets:
                        t_name = asset['ticker']
                        t_w = asset['weight']
                        allocation = (initial_capital + loan_amount) * t_w
                        # 防呆：確保能取到價格
                        try:
                            price = first_prices[t_name]
                        except:
                            # 萬一欄位名不對，嘗試直接取值
                            price = first_prices.iloc[0] if len(assets) == 1 else 0
                            
                        if price > 0:
                            shares[t_name] = allocation / price
                        else:
                            shares[t_name] = 0
                    
                    history = []
                    monthly_rate = loan_rate / 12
                    total_invested = initial_capital
                    
                    # 4. 開始回測迴圈
                    for date, row in data.iterrows():
                        # A. 現金生息
                        daily_interest = current_cash * (cash_interest_rate / 365)
                        current_cash += daily_interest
                        
                        # B. 月初事件
                        is_month_start = date.is_month_start
                        is_year_start = date.is_year_start
                        
                        if is_month_start:
                            if monthly_contribution > 0:
                                current_cash += monthly_contribution
                                total_invested += monthly_contribution
                            
                            if use_leverage:
                                current_cash -= (loan_amount * monthly_rate)

                        # C. 計算市值
                        current_stock_value = 0
                        asset_values = {}
                        
                        for asset in assets:
                            t_name = asset['ticker']
                            # 確保 row 裡面有該代號
                            if t_name in row:
                                val = shares[t_name] * row[t_name]
                                asset_values[t_name] = val
                                current_stock_value += val
                        
                        total_assets = current_cash + current_stock_value
                        net_worth = total_assets - loan_amount
                        
                        # D. 判斷再平衡
                        do_rebalance = False
                        
                        if rebalance_mode == "每月 (Monthly)" and is_month_start:
                            do_rebalance = True
                        elif rebalance_mode == "每年 (Yearly)" and is_year_start:
                            do_rebalance = True
                        
                        if threshold_mode and total_assets > 0:
                            for asset in assets:
                                t_name = asset['ticker']
                                if t_name in asset_values:
                                    t_target_w = asset['weight']
                                    current_w = asset_values[t_name] / total_assets
                                    if abs(current_w - t_target_w) > threshold_pct:
                                        do_rebalance = True
                                        break

                        # E. 執行再平衡
                        if do_rebalance and total_assets > 0:
                            new_shares = {}
                            cost_of_stocks = 0
                            
                            for asset in assets:
                                t_name = asset['ticker']
                                t_target_w = asset['weight']
                                target_val = total_assets * t_target_w
                                
                                if t_name in row:
                                    new_s = target_val / row[t_name]
                                    new_shares[t_name] = new_s
                                    cost_of_stocks += target_val
                            
                            shares = new_shares
                            current_cash = total_assets - cost_of_stocks

                        # F. 記錄數據
                        record = {
                            "Date": date,
                            "Net Worth": net_worth,
                            "Total Invested": total_invested,
                            "Cash": current_cash
                        }
                        for t_name, val in asset_values.items():
                            record[t_name] = val
                            
                        history.append(record)
                    
                    # 5. 結果展示
                    df_res = pd.DataFrame(history)
                    
                    if df_res.empty:
                        st.error("計算結果為空，請檢查資料來源。")
                    else:
                        final_nav = df_res.iloc[-1]['Net Worth']
                        final_invested = df_res.iloc[-1]['Total Invested']
                        total_profit = final_nav - final_invested
                        roi = (total_profit / final_invested) * 100 if final_invested > 0 else 0
                        
                        c1, c2, c3 = st.columns(3)
                        c1.metric("最終淨資產", f"${int(final_nav):,}")
                        c2.metric("總投入本金", f"${int(final_invested):,}")
                        c3.metric("總損益 (ROI)", f"${int(total_profit):,}", f"{roi:.2f}%")
                        
                        st.subheader("資產累積走勢")
                        
                        fig = px.line(df_res, x="Date", y=["Net Worth", "Total Invested"], 
                                    title="淨值成長 vs 投入成本",
                                    color_discrete_map={"Net Worth": "red", "Total Invested": "gray"})
                        st.plotly_chart(fig, use_container_width=True)
                        
                        with st.expander("查看詳細數據與個別資產價值"):
                            st.dataframe(df_res.sort_values("Date", ascending=False))

            except Exception as e:
                st.error(f"發生錯誤: {e}")
                # 印出詳細錯誤以便除錯
                import traceback
                st.text(traceback.format_exc())

else:
    st.info("👈 請在左側設定參數，然後點擊按鈕開始。")
