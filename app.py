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
# 預設起始日 (後續會根據資料實際狀況調整)
requested_start_date = end_date - timedelta(days=years_back*365)

# 2. 標的與配置 (動態生成 1~5 檔)
st.sidebar.subheader("📊 資產配置")
num_assets = st.sidebar.slider("選擇標的數量", 1, 5, 2)

assets = [] # 儲存標的資訊的列表
total_asset_weight = 0

for i in range(num_assets):
    col1, col2 = st.sidebar.columns([1, 2])
    # 預設值設定 (方便快速測試)
    default_ticker = "00662.TW" if i == 0 else ("00670L.TW" if i == 1 else "")
    default_weight = 40 if i == 0 else (30 if i == 1 else 10)
    
    with col1:
        ticker = st.text_input(f"標的 {i+1} 代號", default_ticker, key=f"t_{i}")
    with col2:
        weight = st.slider(f"配置 %", 0, 100, default_weight, key=f"w_{i}")
    
    if ticker:
        assets.append({'ticker': ticker, 'weight': weight / 100})
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
st.title("📈 多資產成長模擬器 (最多5檔 + 自動日期校正)")

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
                # 為了確保能涵蓋所有日期，先寬鬆下載，再做交集
                raw_data = yf.download(ticker_list, start=requested_start_date, end=end_date)['Adj Close']
                
                # 2. 自動日期校正 (關鍵步驟)
                # dropna() 會移除任何有空值的列 -> 只保留所有標的都已經上市的日期
                data = raw_data.dropna()
                
                if data.empty:
                    st.error("資料為空！可能是標的代號錯誤，或選定的標的之間沒有共同的上市時間重疊。")
                else:
                    # 抓取實際開始日期
                    actual_start_date = data.index[0]
                    date_diff = actual_start_date - requested_start_date.replace(tzinfo=None) if hasattr(requested_start_date, 'tzinfo') else actual_start_date - pd.to_datetime(requested_start_date).replace(tzinfo=None)
                    
                    # 顯示日期調整提示
                    if actual_start_date > pd.Timestamp(requested_start_date).replace(tzinfo=None):
                        st.warning(f"⚠️ 注意：由於部分標的上市時間較晚，回測起始日已自動調整為 **{actual_start_date.strftime('%Y-%m-%d')}** (所有標的皆有數據的日期)。")
                    
                    # 3. 初始化模擬
                    current_cash = (initial_capital + loan_amount) * (weight_cash / 100)
                    
                    # 動態初始化股數
                    shares = {}
                    # 使用第一筆有資料的股價來建倉
                    first_prices = data.iloc[0]
                    for asset in assets:
                        t_name = asset['ticker']
                        t_w = asset['weight']
                        # 初始買入金額 = 總資金 * 權重
                        allocation = (initial_capital + loan_amount) * t_w
                        shares[t_name] = allocation / first_prices[t_name]
                    
                    history = []
                    monthly_rate = loan_rate / 12
                    total_invested = initial_capital
                    
                    # 4. 開始回測迴圈
                    for date, row in data.iterrows():
                        # A. 現金生息 (日複利)
                        daily_interest = current_cash * (cash_interest_rate / 365)
                        current_cash += daily_interest
                        
                        # B. 月初事件 (定期定額 & 借貸利息)
                        is_month_start = date.is_month_start
                        is_year_start = date.is_year_start
                        
                        if is_month_start:
                            if monthly_contribution > 0:
                                current_cash += monthly_contribution
                                total_invested += monthly_contribution
                            
                            if use_leverage:
                                current_cash -= (loan_amount * monthly_rate)

                        # C. 計算當前總市值
                        current_stock_value = 0
                        asset_values = {} # 暫存各個資產當下價值
                        
                        for asset in assets:
                            t_name = asset['ticker']
                            val = shares[t_name] * row[t_name]
                            asset_values[t_name] = val
                            current_stock_value += val
                        
                        total_assets = current_cash + current_stock_value
                        net_worth = total_assets - loan_amount
                        
                        # D. 判斷再平衡
                        do_rebalance = False
                        
                        # 時間觸發
                        if rebalance_mode == "每月 (Monthly)" and is_month_start:
                            do_rebalance = True
                        elif rebalance_mode == "每年 (Yearly)" and is_year_start:
                            do_rebalance = True
                        
                        # 閾值觸發 (檢查每一檔標的是否偏離)
                        if threshold_mode and total_assets > 0:
                            for asset in assets:
                                t_name = asset['ticker']
                                t_target_w = asset['weight']
                                current_w = asset_values[t_name] / total_assets
                                if abs(current_w - t_target_w) > threshold_pct:
                                    do_rebalance = True
                                    break # 只要有一檔偏離就觸發重整

                        # E. 執行再平衡
                        if do_rebalance and total_assets > 0:
                            # 重新計算每一檔應該持有的金額
                            new_shares = {}
                            cost_of_stocks = 0
                            
                            for asset in assets:
                                t_name = asset['ticker']
                                t_target_w = asset['weight']
                                target_val = total_assets * t_target_w
                                
                                # 計算新股數
                                new_s = target_val / row[t_name]
                                new_shares[t_name] = new_s
                                cost_of_stocks += target_val
                            
                            # 更新持股與現金
                            shares = new_shares
                            current_cash = total_assets - cost_of_stocks

                        # F. 記錄數據
                        record = {
                            "Date": date,
                            "Net Worth": net_worth,
                            "Total Invested": total_invested,
                            "Cash": current_cash
                        }
                        # 加入個別資產價值
                        for t_name, val in asset_values.items():
                            record[t_name] = val
                            
                        history.append(record)
                    
                    # 5. 結果展示
                    df_res = pd.DataFrame(history)
                    
                    final_nav = df_res.iloc[-1]['Net Worth']
                    final_invested = df_res.iloc[-1]['Total Invested']
                    total_profit = final_nav - final_invested
                    roi = (total_profit / final_invested) * 100 if final_invested > 0 else 0
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("最終淨資產", f"${int(final_nav):,}")
                    c2.metric("總投入本金", f"${int(final_invested):,}")
                    c3.metric("總損益 (ROI)", f"${int(total_profit):,}", f"{roi:.2f}%")
                    
                    st.subheader("資產累積走勢")
                    
                    # 繪圖：只畫 Net Worth 和 Total Invested 保持清晰，詳細可看表格
                    fig = px.line(df_res, x="Date", y=["Net Worth", "Total Invested"], 
                                  title="淨值成長 vs 投入成本",
                                  color_discrete_map={"Net Worth": "red", "Total Invested": "gray"})
                    st.plotly_chart(fig, use_container_width=True)
                    
                    with st.expander("查看詳細數據與個別資產價值"):
                        st.dataframe(df_res.sort_values("Date", ascending=False))

            except Exception as e:
                st.error(f"發生錯誤: {e}")
