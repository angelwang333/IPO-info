import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
import io

# 設定網頁標題與寬度
st.set_page_config(page_title="台灣 IPO 競拍追蹤", layout="wide")

# === 核心函數：抓取與處理資料 (最終修正版：修復 List 格式與 SSL 問題) ===
def get_twse_auction_data():
    url = "https://www.twse.com.tw/rwd/zh/announcement/auction"
    try:
        # 忽略 SSL 警告
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # 加上 verify=False 避開憑證問題
        res = requests.get(url, headers=headers, verify=False)
        data = res.json()
        
        if 'data' not in data:
            return None, "無法取得資料，可能來源格式變更"
            
        raw_list = data['data']
        processed_data = []

        # 證交所資料欄位對應 (依據觀察 API 回傳順序)
        # 0: 競拍期間 (e.g., 113/11/12~113/11/14)
        # 1: 股票代號
        # 2: 股票名稱
        # 3: 產業
        # 4: 承銷商
        # 5: 承銷張數
        # 6: 競拍張數
        # 9: 底價
        # 10: 承銷價
        # 12: 最低得標價
        # 13: 最高得標價
        # 14: 得標加權平均價
        # 17: 掛牌日期
        # 18: 開標日期 (位置可能變動，通常在最後)

        for item in raw_list:
            # 安全檢查：確保資料長度足夠，避免 IndexError
            if len(item) < 18: 
                continue

            # 使用索引 (Index) 抓取資料，而非 .get()
            row = {
                "競拍期間": item[0],
                "證券代號": item[1],
                "證券名稱": item[2],
                "所屬產業": item[3],
                "承銷商": item[4],
                "承銷張數": item[5],
                "競拍張數": item[6],
                "底價": item[9],
                "承銷價": item[10],
                "最低得標價": item[12],
                "最高得標價": item[13],
                "得標加權平均價": item[14],
                "掛牌日期": item[17],
                "開標日期": item[18] if len(item) > 18 else "" # 開標日通常在第 19 格 (index 18)
            }
            
            # --- 處理日期格式 (民國轉西元) ---
            def roc_to_date(roc_str):
                try:
                    if not roc_str: return None
                    parts = roc_str.split('/')
                    # 簡單檢查格式是否正確
                    if len(parts) != 3: return None
                    year = int(parts[0]) + 1911
                    return date(year, int(parts[1]), int(parts[2]))
                except:
                    return None

            row['date_open_obj'] = roc_to_date(row['開標日期'])
            row['date_list_obj'] = roc_to_date(row['掛牌日期'])
            
            # 解析競拍結束日
            try:
                # 格式通常是 "113/11/01~113/11/03"
                if '~' in row['競拍期間']:
                    end_date_str = row['競拍期間'].split('~')[1]
                    row['date_auction_end_obj'] = roc_to_date(end_date_str)
                else:
                    row['date_auction_end_obj'] = None
            except:
                row['date_auction_end_obj'] = None

            processed_data.append(row)

        return pd.DataFrame(processed_data), None

    except Exception as e:
        return None, str(e)

# === 核心函數：分類邏輯 ===
def classify_data(df):
    today = date.today()
    
    # 建立遮罩 (Mask)
    # 1. 進行中：今天 <= 競拍結束日 OR (還沒開標)
    mask_ongoing = (df['date_auction_end_obj'] >= today) | (df['date_open_obj'] > today)
    
    # 2. 已掛牌：今天 >= 掛牌日
    mask_listed = (df['date_list_obj'] <= today)
    
    # 3. 已開標 (但在掛牌之前)：開標日 <= 今天 < 掛牌日
    mask_auctioned = (df['date_open_obj'] <= today) & (df['date_list_obj'] > today)

    # 分割 DataFrame
    df_ongoing = df[mask_ongoing].copy()
    df_listed = df[mask_listed].copy()
    df_auctioned = df[mask_auctioned].copy()
    
    # 移除輔助用的日期物件欄位，保持介面乾淨
    drop_cols = ['date_open_obj', 'date_list_obj', 'date_auction_end_obj']
    return df_ongoing.drop(columns=drop_cols), df_auctioned.drop(columns=drop_cols), df_listed.drop(columns=drop_cols)

# === 核心函數：產生 Excel ===
def convert_df_to_excel(df_ongoing, df_auctioned, df_listed):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_ongoing.to_excel(writer, index=False, sheet_name='IPO競拍_進行中')
        df_auctioned.to_excel(writer, index=False, sheet_name='IPO競拍_開標')
        df_listed.to_excel(writer, index=False, sheet_name='IPO競拍_掛牌')
    return output.getvalue()

# === 主介面 (UI) ===
st.title("📊 台灣 IPO 競拍自動追蹤看板")
st.markdown(f"資料來源：台灣證券交易所 | 最後更新日期：{date.today()}")

# 執行抓取
with st.spinner('正在連線證交所抓取最新資料...'):
    df_all, error = get_twse_auction_data()

if error:
    st.error(f"發生錯誤：{error}")
else:
    # 進行分類
    df_ongoing, df_auctioned, df_listed = classify_data(df_all)

    # 顯示下載按鈕
    excel_data = convert_df_to_excel(df_ongoing, df_auctioned, df_listed)
    st.download_button(
        label="📥 下載 Excel 報表",
        data=excel_data,
        file_name=f'IPO_Auction_Data_{date.today()}.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

    # 顯示分頁
    tab1, tab2, tab3 = st.tabs(["🚀 進行中", "⚖️ 已開標 (待掛牌)", "🏁 已掛牌"])

    with tab1:
        st.subheader(f"進行中案件 ({len(df_ongoing)})")
        if not df_ongoing.empty:
            st.dataframe(df_ongoing, use_container_width=True)
        else:
            st.info("目前沒有進行中的競拍案件。")

    with tab2:
        st.subheader(f"已開標案件 ({len(df_auctioned)})")
        if not df_auctioned.empty:
            st.dataframe(df_auctioned, use_container_width=True)
        else:
            st.info("目前沒有等待掛牌的案件。")

    with tab3:
        st.subheader(f"已掛牌歷史資料 ({len(df_listed)})")
        if not df_listed.empty:
            st.dataframe(df_listed, use_container_width=True)
        else:
            st.info("尚無歷史資料。")
