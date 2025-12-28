import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面設定 (必須放第一行) ---
st.set_page_config(page_title="全方位資產成長模擬器 (終極版)", layout="wide", page_icon="📈")

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

# (C) 資金與現金流
st.sidebar.subheader("💸 資金與現金流")
initial_capital = st.sidebar.number_input("初始本金", value=1000000, step=100000)
monthly_cashflow = st.sidebar.number_input(
    "📅 每月現金流 (+存入 / -提款)", 
    value=20000, 
    step=5000, 
    help="正數代表定期定額存入；負數代表從投資組合提款 (或還信貸本利和)"
)
cash_interest_rate = st.sidebar.number_input("💰 現金/短債年化報酬率 (%)", value=1.5, step=0.1, help="模擬活存或短債ETF的無風險利率") / 100

# (D) 槓桿設定
st.sidebar.subheader("⚙️ 槓桿設定")
use_leverage = st.sidebar.checkbox("啟用信貸/質押模擬")
loan_amount = 0.0
loan_rate = 0.0
if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸金額", value=0.0, step=100000.0)
    loan_rate = st.sidebar.number_input("借貸年利率 (%)", value=2.5, step=0.1) / 100

# (E) 再平衡策略
st.sidebar.subheader("⚖️ 再平衡策略")
rebalance_mode = st.sidebar.selectbox("再平衡頻率", ["每月 (Monthly)", "每年 (Yearly)", "不進行 (Buy & Hold)"])
threshold_mode = st.sidebar.checkbox("啟用偏移閾值 (Threshold)")
threshold_pct = 0.05
if threshold_mode:
    threshold_pct = st.sidebar.slider("容許偏移值 (%)", 1, 20, 5) / 100

# --- 3. 核心函數：下載數據 (安全版) ---
def get_data_safe(ticker_list, start, end):
    try:
        # 強制 auto_adjust=False 以保留原始欄位結構
        df = yf.download(ticker_list, start=start, end=end, progress=False, auto_adjust=False)
        
        if df.empty: return pd.DataFrame()

        # 優先找 Adj Close，沒有則找 Close
        target_col = 'Adj Close' if 'Adj Close' in df.columns else ('Close' if 'Close' in df.columns else None)
        
        if not target_col: return pd.DataFrame()

        data = df[target_col]

        # 格式標準化 (單檔轉 DataFrame)
        if isinstance(data, pd.Series):
            data = data.to_frame()
            data.columns = ticker_list
        elif isinstance(data, pd.DataFrame):
            if len(ticker_list) == 1 and len(data.columns) == 1:
                 data.columns = ticker_list
        
        # 補值與清洗
        data = data.ffill().dropna()
        return data

    except Exception as e:
        st.error(f"數據下載錯誤: {e}")
        return pd.DataFrame()

# --- 4. 主程式邏輯 ---
st.title("📈 全方位資產成長模擬器 (終極版)")

if st.button("🚀 開始模擬運算", type="primary"):
    if weight_cash < 0:
        st.error("配置權重超過 100%！")
    elif not assets:
        st.error("請至少輸入一檔標的。")
    else:
        with st.spinner('正在下載數據並執行模擬...'):
            ticker_list = [a['ticker'] for a in assets]
            data = get_data_safe(ticker_list, requested_start_date, end_date)
            
            if data.empty:
                st.error(f"❌ 無法取得資料。請確認股票代號 {ticker_list} 是否正確 (台股需加 .TW)。")
            else:
                # 日期校正提示
                actual_start = data.index[0]
                act_ts = actual_start.tz_localize(None) if actual_start.tzinfo else actual_start
                req_ts = pd.Timestamp(requested_start_date).tz_localize(None)
                if act_ts > req_ts:
                    st.warning(f"⚠️ 注意：因部分標的上市較晚，回測起始日自動調整為 **{actual_start.strftime('%Y-%m-%d')}**")

                # --- 模擬初始化 ---
                current_cash = (initial_capital + loan_amount) * (weight_cash / 100)
                shares = {}
                
                # 建倉
                first_prices = data.iloc[0]
                valid_sim = True
                
                for asset in assets:
                    t = asset['ticker']
                    if t not in data.columns:
                        st.error(f"找不到 {t} 的數據。")
                        valid_sim = False; break
                    
                    price = first_prices[t]
                    if pd.isna(price) or price <= 0: price = data[t].dropna().iloc[0]
                    shares[t] = ((initial_capital + loan_amount) * asset['weight']) / price

                if valid_sim:
                    history = []
                    monthly_rate = loan_rate / 12
                    total_invested = initial_capital
                    
                    # --- 逐日回測 ---
                    for date, row in data.iterrows():
                        # A. 現金生息 (日複利)
                        current_cash += current_cash * (cash_interest_rate / 365)
                        
                        # B. 月初事件 (現金流 & 利息)
                        is_month_start = date.is_month_start
                        if is_month_start:
                            # 現金流 (正:存入, 負:提款)
                            current_cash += monthly_cashflow
                            # 只有當是「存入」時，才增加總成本；提款不減少「投入本金」紀錄
                            if monthly_cashflow > 0:
                                total_invested += monthly_cashflow
                            
                            if use_leverage:
                                current_cash -= (loan_amount * monthly_rate)

                        # C. 計算市值
                        stock_val = 0
                        asset_vals = {}
                        for t in ticker_list:
                            if t in row:
                                val = shares[t] * row[t]
                                asset_vals[t] = val
                                stock_val += val
                        
                        total_assets = current_cash + stock_val
                        net_worth = total_assets - loan_amount

                        # D. 再平衡判斷
                        do_rebalance = False
                        if rebalance_mode == "每月 (Monthly)" and is_month_start: do_rebalance = True
                        elif rebalance_mode == "每年 (Yearly)" and date.is_year_start: do_rebalance = True
                        
                        if threshold_mode and total_assets > 0:
                            for asset in assets:
                                t = asset['ticker']
                                if t in asset_vals:
                                    target = asset['weight']
                                    curr_w = asset_vals[t] / total_assets
                                    if abs(curr_w - target) > threshold_pct:
                                        do_rebalance = True; break
                        
                        # E. 執行再平衡
                        if do_rebalance and total_assets > 0:
                            cost_stock = 0
                            for asset in assets:
                                t = asset['ticker']
                                if t in row:
                                    target_val = total_assets * asset['weight']
                                    shares[t] = target_val / row[t]
                                    cost_stock += target_val
                            current_cash = total_assets - cost_stock

                        # F. 記錄
                        rec = {"Date": date, "Net Worth": net_worth, "Total Invested": total_invested, "Cash": current_cash}
                        history.append(rec)

                    # --- 結果展示 ---
                    df_res = pd.DataFrame(history)
                    if not df_res.empty:
                        # 1. 基礎指標
                        final_nav = df_res.iloc[-1]['Net Worth']
                        final_inv = df_res.iloc[-1]['Total Invested']
                        profit = final_nav - final_inv
                        roi = (profit/final_inv)*100 if final_inv>0 else 0
                        
                        # 計算最大回撤 (MDD)
                        df_res['Peak'] = df_res['Net Worth'].cummax()
                        df_res['Drawdown'] = (df_res['Net Worth'] - df_res['Peak']) / df_res['Peak']
                        mdd = df_res['Drawdown'].min() * 100

                        st.markdown("### 📊 回測結果摘要")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("最終淨資產", f"${int(final_nav):,}")
                        c2.metric("總投入本金", f"${int(final_inv):,}")
                        c3.metric("總損益 (ROI)", f"${int(profit):,}", f"{roi:.2f}%")
                        c4.metric("最大回撤 (MDD)", f"{mdd:.2f}%", delta_color="inverse")

                        # 2. 走勢圖
                        fig = px.line(df_res, x="Date", y=["Net Worth", "Total Invested"], 
                                      title="淨值成長 vs 投入成本",
                                      color_discrete_map={"Net Worth": "red", "Total Invested": "gray"})
                        st.plotly_chart(fig, use_container_width=True)

                        # --- 進階分析 1: 滾動報酬 (Rolling Return) ---
                        st.markdown("---")
                        st.subheader("🔄 歷史滾動報酬分析 (Rolling Returns)")
                        st.info("模擬在過去「任意一天」進場，並持有固定年數後的勝率。")
                        
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

                        # --- 進階分析 2: 蒙地卡羅模擬 (Monte Carlo) ---
                        st.markdown("---")
                        st.subheader("🎲 蒙地卡羅壓力測試 (Monte Carlo)")
                        st.info("隨機重組歷史漲跌幅，預測未來的成功機率 (特別適用於評估信貸/提款風險)。")
                        
                        mc1, mc2 = st.columns(2)
                        sim_years = mc1.number_input("預測未來年數", value=10)
                        sim_count = mc2.number_input("模擬次數 (建議 100)", value=100)
                        
                        if st.button("開始壓力測試"):
                            with st.spinner("正在運算平行宇宙..."):
                                daily_returns = data.pct_change().dropna()
                                # 簡化計算：使用資產組合的加權報酬率
                                asset_weights = np.array([a['weight'] for a in assets])
                                # 對齊欄位
                                valid_cols = [c for c in ticker_list if c in daily_returns.columns]
                                if not valid_cols:
                                     st.error("無法計算報酬率")
                                else:
                                    daily_returns = daily_returns[valid_cols]
                                    # 重新調整權重以匹配有效欄位
                                    # 這裡做個簡單正規化，避免因缺資料導致權重錯誤
                                    # (精確做法應更複雜，此為壓力測試近似值)
                                    weighted_ret = daily_returns.mean(axis=1) # 簡化假設
                                    
                                    sim_days = sim_years * 252
                                    success_count = 0
                                    fig_mc = go.Figure()
                                    
                                    # 模擬迴圈
                                    for i in range(sim_count):
                                        # Bootstrap 抽樣
                                        random_rets = weighted_ret.sample(n=sim_days, replace=True).values
                                        
                                        nav = initial_capital
                                        survived = True
                                        path = [nav]
                                        
                                        for d in range(sim_days):
                                            nav = nav * (1 + random_rets[d])
                                            # 約略每月現金流 (每21交易日)
                                            if (d+1) % 21 == 0:
                                                nav += monthly_cashflow
                                                if use_leverage: nav -= (loan_amount * loan_rate / 12)
                                            
                                            if nav <= 0:
                                                nav = 0; survived = False; path.append(0); break
                                            path.append(nav)
                                        
                                        if survived: success_count += 1
                                        if i < 50: # 只畫前50條
                                            fig_mc.add_trace(go.Scatter(y=path, mode='lines', line=dict(width=1, color='rgba(200,200,200,0.5)'), showlegend=False))
                                    
                                    rate = (success_count / sim_count) * 100
                                    st.metric("模擬成功率 (資產未歸零)", f"{rate:.1f}%")
                                    st.plotly_chart(fig_mc, use_container_width=True)
