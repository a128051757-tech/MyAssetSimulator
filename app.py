import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="多資產成長模擬器 (Dividend Option)", layout="wide", page_icon="📈")

# --- 2. 側邊欄：參數設定 ---
st.sidebar.header("⚙️ 參數設定")

# 2.1 資金與槓桿
st.sidebar.subheader("💰 資金與槓桿")
initial_capital = st.sidebar.number_input("起始本金 (TWD)", value=1000000, step=100000)

use_leverage = st.sidebar.checkbox("啟用信貸/質押模擬")
loan_amount = 0.0
loan_rate_percent = 2.5

if use_leverage:
    loan_amount = st.sidebar.number_input("初始借貸金額 (TWD)", value=500000.0, step=10000.0)
    loan_rate_percent = st.sidebar.number_input("借貸年利率 (%)", value=2.2, step=0.1)

loan_rate = loan_rate_percent / 100

# 2.2 股息設定 (新增功能)
st.sidebar.subheader("💵 股息策略")
enable_drip = st.sidebar.checkbox("啟用股息再投入 (DRIP)", value=True, help="打勾：使用還原股價 (Adj Close)，模擬股息自動滾入本金。\n取消：使用一般收盤價 (Close)，模擬股息領出花掉，不計入資產。")

# 2.3 時間設定
st.sidebar.subheader("📅 回測時間")
default_start = datetime.now() - timedelta(days=365*3)
default_end = datetime.now()

start_date = st.sidebar.date_input("開始日期", default_start)
end_date = st.sidebar.date_input("結束日期", default_end)

# 2.4 再平衡策略
st.sidebar.subheader("⚖️ 再平衡邏輯")
rebalance_freq = st.sidebar.selectbox(
    "定期再平衡頻率", 
    ["每月 (Monthly)", "每年 (Yearly)", "不定期 (Only Threshold)", "不進行 (Buy & Hold)"]
)

use_threshold = st.sidebar.checkbox("啟用偏離度再平衡 (Threshold)", value=True)
threshold_pct = 0.05
if use_threshold:
    threshold_pct = st.sidebar.number_input("偏離容許值 (%)", value=5.0, step=1.0) / 100

# --- 3. 主畫面：標的輸入 ---
st.title("📈 多資產成長模擬器 (含股息開關)")
st.caption("新增功能：可取消「股息再投入」，模擬純粹的股價成長 (Price Return)。")

# 預設顯示的投資組合 (包含 CASH)
default_data = pd.DataFrame(
    [
        {"Ticker": "00662.TW", "Weight (%)": 40},
        {"Ticker": "00670L.TW", "Weight (%)": 30},
        {"Ticker": "CASH", "Weight (%)": 30}, 
    ]
)

st.info("👇 請在表格設定配置。若要固定現金比例，請新增一行代號輸入 **`CASH`** 或 **`現金`**。")
edited_df = st.data_editor(default_data, num_rows="dynamic", use_container_width=True)

# --- 權重計算與防呆 ---
# 1. 識別哪些是現金，哪些是股票
edited_df['Ticker_Upper'] = edited_df['Ticker'].astype(str).str.strip().str.upper()
is_cash_row = edited_df['Ticker_Upper'].isin(['CASH', '現金', 'MONEY'])

stock_rows = edited_df[~is_cash_row]
cash_rows = edited_df[is_cash_row]

total_weight = edited_df["Weight (%)"].sum()
stock_weight_sum = stock_rows["Weight (%)"].sum()
cash_weight_sum = cash_rows["Weight (%)"].sum()

# 2. 計算最終現金權重
residual_cash = 100 - total_weight
final_cash_pct = cash_weight_sum + residual_cash

# 顯示權重狀態
col1, col2 = st.columns(2)
with col1:
    if final_cash_pct < 0:
        st.error(f"⚠️ 權重總和超過 100% (目前: {total_weight}%)，請減少配置！")
    else:
        status_text = "✅ 股息策略: 再投入 (滾複利)" if enable_drip else "🛑 股息策略: 領出 (不投入)"
        st.success(f"✅ 股票: {stock_weight_sum:.1f}% | 💰 現金: {final_cash_pct:.1f}% | {status_text}")

# --- 4. 核心功能函數 ---
def safe_download_data(tickers, start, end, use_drip=True):
    if not tickers:
        return pd.DataFrame(), "無股票代號"
        
    try:
        # 下載數據
        df = yf.download(tickers, start=start, end=end, auto_adjust=False, progress=False)
        if df.empty: return None, "下載為空"

        # 決定要抓哪個欄位
        # 如果開啟 DRIP -> 優先抓 Adj Close
        # 如果關閉 DRIP -> 優先抓 Close
        target_col = 'Adj Close' if use_drip else 'Close'
        fallback_col = 'Close' if use_drip else 'Adj Close' # 萬一沒有目標欄位時的備案

        cols_level0 = df.columns.get_level_values(0)
        
        # 檢查目標欄位是否存在
        final_col = None
        if target_col in cols_level0:
            final_col = target_col
        elif fallback_col in cols_level0:
            final_col = fallback_col
            # 如果使用者想用 Close 但只抓到 Adj Close，通常不太會發生，除非資料源怪異
            # 但如果想用 Adj Close 卻只有 Close，代表沒辦法算股息，只能將就
        
        if final_col is None:
             # 單檔股票結構檢查 (有時 columns 沒有 level)
            if target_col in df.columns: final_col = target_col
            elif fallback_col in df.columns: final_col = fallback_col
        
        if final_col is None:
             return None, f"找不到股價欄位 ({target_col} or {fallback_col})"

        # 提取數據
        if final_col in cols_level0:
            price_data = df[final_col]
        else:
            price_data = df[final_col]

        # 如果變成 Series，轉回 DataFrame
        if isinstance(price_data, pd.Series):
            price_data = price_data.to_frame(name=tickers[0])
            
        price_data = price_data.fillna(method='ffill').dropna()
        if price_data.empty: return None, "資料清洗後為空"
            
        return price_data, None

    except Exception as e:
        return None, str(e)


# --- 5. 執行模擬 ---
if st.button("🚀 開始模擬運算", type="primary", disabled=(final_cash_pct < 0)):
    
    stock_tickers = [t for t in stock_rows["Ticker"] if t.strip()]
    
    if not stock_tickers and final_cash_pct < 100:
        st.warning("請至少輸入一檔股票代號，或將現金設為 100%。")
        st.stop()

    with st.spinner('正在下載數據...'):
        
        if stock_tickers:
            # 傳入 enable_drip 參數
            data, error_msg = safe_download_data(stock_tickers, start_date, end_date, use_drip=enable_drip)
            if data is None:
                st.error(f"❌ 錯誤: {error_msg}")
                st.stop()
            
            simulation_dates = data.index
            prices_df = data
        else:
            # 純現金模式
            dates = pd.date_range(start=start_date, end=end_date, freq='D')
            simulation_dates = dates
            prices_df = pd.DataFrame(index=dates)

        # 建立目標權重字典
        target_weights = {}
        for index, row in stock_rows.iterrows():
            t = row['Ticker'].strip()
            if t in prices_df.columns:
                target_weights[t] = row['Weight (%)'] / 100.0
        
        target_cash_ratio = final_cash_pct / 100.0

        # --- 初始化模擬 ---
        start_capital = initial_capital + loan_amount
        current_cash = start_capital * target_cash_ratio
        
        current_shares = {}
        if not prices_df.empty:
            first_prices = prices_df.iloc[0]
            for t, w in target_weights.items():
                allocation = start_capital * w
                current_shares[t] = allocation / first_prices[t]
        
        history = []
        rebalance_log = [] 
        monthly_rate = loan_rate / 12
        
        progress_bar = st.progress(0)
        total_days = len(simulation_dates)
        
        for i, date in enumerate(simulation_dates):
            if i % 100 == 0: progress_bar.progress(i / total_days)

            # 1. 取得今日股價
            if not prices_df.empty and date in prices_df.index:
                today_prices = prices_df.loc[date]
            else:
                continue

            # 2. 計算市值
            stock_val_dict = {}
            total_stock_val = 0
            for t, shares in current_shares.items():
                price = today_prices[t]
                val = shares * price
                stock_val_dict[t] = val
                total_stock_val += val
            
            total_assets = current_cash + total_stock_val
            net_worth = total_assets - loan_amount
            
            # 3. 判斷月初/年初
            is_month_start = (i > 0 and date.month != simulation_dates[i-1].month)
            is_year_start = (i > 0 and date.year != simulation_dates[i-1].year)

            # 扣息
            if use_leverage and is_month_start:
                interest = loan_amount * monthly_rate
                current_cash -= interest

            # 4. 再平衡判斷
            do_rebalance = False
            rebalance_reason = ""
            
            # A. 時間觸發
            if rebalance_freq == "每月 (Monthly)" and is_month_start:
                do_rebalance = True
                rebalance_reason = "定期 (月)"
            elif rebalance_freq == "每年 (Yearly)" and is_year_start:
                do_rebalance = True
                rebalance_reason = "定期 (年)"
            
            # B. 閾值觸發
            if use_threshold and not do_rebalance:
                # 檢查股票
                for t, w in target_weights.items():
                    curr_w = stock_val_dict[t] / total_assets if total_assets > 0 else 0
                    if abs(curr_w - w) > threshold_pct:
                        do_rebalance = True
                        rebalance_reason = f"偏離 ({t})"
                        break
                
                # 檢查現金
                if not do_rebalance:
                    curr_cash_w = current_cash / total_assets if total_assets > 0 else 0
                    if abs(curr_cash_w - target_cash_ratio) > threshold_pct:
                        do_rebalance = True
                        rebalance_reason = "偏離 (Cash)"

            # 5. 執行再平衡
            if do_rebalance and rebalance_freq != "不進行 (Buy & Hold)":
                rebalance_log.append({
                    "Date": date,
                    "Total Assets": total_assets,
                    "Reason": rebalance_reason
                })

                current_cash = total_assets * target_cash_ratio
                for t, w in target_weights.items():
                    target_val = total_assets * w
                    current_shares[t] = target_val / today_prices[t]
            
            history.append({
                "Date": date,
                "Net Worth": net_worth,
                "Total Assets": total_assets,
                "Cash": current_cash,
                "Rebalance": 1 if do_rebalance else 0
            })
        
        progress_bar.empty()

        # --- 結果顯示 ---
        df_res = pd.DataFrame(history)
        
        final_nav = df_res.iloc[-1]["Net Worth"]
        total_ret = (final_nav - initial_capital) / initial_capital * 100
        rebalance_count = len(rebalance_log)
        
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏁 最終淨資產", f"${int(final_nav):,}")
        c2.metric("📈 總報酬率", f"{total_ret:.2f}%")
        c3.metric("⚖️ 再平衡次數", f"{rebalance_count} 次")
        c4.metric("💵 股息模式", "再投入" if enable_drip else "領出花掉")

        # 圖表
        st.subheader("資產成長與再平衡點")
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=df_res['Date'], y=df_res['Net Worth'],
            mode='lines', name='淨值 (Net Worth)',
            line=dict(color='#1f77b4', width=2)
        ))
        
        rebalance_dates = df_res[df_res['Rebalance'] == 1]
        if not rebalance_dates.empty:
            fig.add_trace(go.Scatter(
                x=rebalance_dates['Date'], y=rebalance_dates['Net Worth'],
                mode='markers', name='執行再平衡',
                marker=dict(color='red', size=8, symbol='circle-open-dot'),
                hovertemplate='日期: %{x}<br>淨值: %{y:,.0f}<extra></extra>'
            ))

        fig.update_layout(title="資產淨值走勢", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        
        # 詳細資訊
        c_left, c_right = st.columns(2)
        
        with c_left:
            st.subheader("📋 再平衡詳細紀錄")
            if rebalance_log:
                log_df = pd.DataFrame(rebalance_log)
                log_df['Date'] = log_df['Date'].dt.date
                log_df['Total Assets'] = log_df['Total Assets'].map('${:,.0f}'.format)
                st.dataframe(log_df, use_container_width=True)
            else:
                st.info("期間內未觸發任何再平衡。")
                
        with c_right:
             st.subheader("📊 每日資產明細")
             st.dataframe(
                 df_res[['Date', 'Net Worth', 'Cash', 'Total Assets']].sort_values("Date", ascending=False),
                 use_container_width=True
             )