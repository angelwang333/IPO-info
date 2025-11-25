import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
import io
import urllib3

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台灣 IPO 競拍追蹤", layout="wide")

# === 核心函數：抓取資料 (智慧對應版) ===
def get_twse_auction_data():
    url = "https://www.twse.com.tw/rwd/zh/announcement/auction"
    
    # 這裡加入除錯訊息，讓你知道程式跑到哪了
    status_log = []
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 抓取資料
        status_log.append("正在連線到證交所...")
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        
        if res.status_code != 200:
            return None, f"連線失敗，狀態碼：{res.status_code}"
            
        status_log.append("連線成功，正在解析 JSON...")
        json_data = res.json()
        
        # 檢查資料結構
        if 'data' not in json_data:
            return None, f"API 回傳格式異常，找不到 'data' 欄位。原始回傳：{str(json_data)[:200]}"
            
        raw_data = json_data['data']
        raw_fields = json_data.get('fields', []) # 嘗試取得欄位名稱
        
        status_log.append(f"取得 {len(raw_data)} 筆資料。")
        
        if not raw_data:
            return None, "證交所目前回傳的資料列表是空的 (No Data)。"

        # === 智慧 DataFrame 建立 ===
        # 如果 API 有給欄位名稱，直接用；如果沒給，我們只能用猜的 (通常都會給)
        if raw_fields:
            df = pd.DataFrame(raw_data, columns=raw_fields)
        else:
            # 萬一真的沒給欄位名，這裡提供備用方案 (Blind Mapping)
            df = pd.DataFrame(raw_data)
            status_log.append("警告：API 未提供欄位名稱，使用預設索引。")

        # === 欄位標準化 (Rename) ===
        # 為了讓後面的程式碼看得懂，我們要確保欄位名稱統一
        # 下面是常見的欄位名稱對應，程式會自動找對應的
        col_mapping = {
            # 證交所欄位名 : 我們的標準名
            "證券代號": "證券代號", "股票代號": "證券代號", "Code": "證券代號",
            "證券名稱": "證券名稱", "股票名稱": "證券名稱", "Name": "證券名稱",
            "競拍期間": "競拍期間", "DateRange": "競拍期間",
            "開標日期": "開標日期", "OpenDate": "開標日期",
            "掛牌日期": "掛牌日期", "ListingDate": "掛牌日期",
            "公開承銷股數": "承銷張數", "承銷張數": "承銷張數",
            "競拍數量": "競拍張數", "競拍張數": "競拍張數",
            "最低得標價格": "最低得標價", "最低得標價": "最低得標價",
            "最高得標價格": "最高得標價", "最高得標價": "最高得標價",
            "得標加權平均價格": "得標加權平均價", "得標加權平均價": "得標加權平均價",
            "公開承銷價格": "承銷價", "承銷價": "承銷價",
            "最低承銷價格": "底價", "底價": "底價"
        }
        
        # 重新命名欄位
        df = df.rename(columns=col_mapping)
        
        # === 日期處理 ===
        def clean_date(x):
            if not isinstance(x, str): return None
            x = x.strip()
            if not x: return None
            try:
                parts = x.split('/')
                if len(parts) == 3:
                    return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
            except:
                pass
            return None

        # 確保關鍵日期欄位存在，若不存在則補上 None，避免報錯
        required_cols = ['開標日期', '掛牌日期', '競拍期間']
        for col in required_cols:
            if col not in df.columns:
                df[col] = "" # 補空字串

        df['date_open_obj'] = df['開標日期'].apply(clean_date)
        df['date_list_obj'] = df['掛牌日期'].apply(clean_date)
        
        def parse_end_date(range_str):
            try:
                return clean_date(range_str.split('~')[1])
            except:
                return None
        
        df['date_auction_end_obj'] = df['競拍期間'].apply(parse_end_date)
        
        return df, None

    except Exception as e:
        import traceback
        return None, f"程式執行錯誤：{str(e)} \n詳細記錄：{status_log}"

# === 分類與下載邏輯 (維持不變) ===
def classify_data(df):
    today = date.today()
    # 確保有這幾個欄位，避免報錯
    if 'date_auction_end_obj' not in df.columns: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    mask_ongoing = (df['date_auction_end_obj'] >= today) | ((df['date_open_obj'] > today) & (df['date_open_obj'].notna()))
    mask_listed = (df['date_list_obj'] <= today)
    mask_auctioned = (df['date_open_obj'] <= today) & (df['date_list_obj'] > today)

    return df[mask_ongoing].copy(), df[mask_auctioned].copy(), df[mask_listed].copy()

def convert_df_to_excel(df_ongoing, df_auctioned, df_listed):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_ongoing.to_excel(writer, index=False, sheet_name='IPO競拍_進行中')
        df_auctioned.to_excel(writer, index=False, sheet_name='IPO競拍_開標')
        df_listed.to_excel(writer, index=False, sheet_name='IPO競拍_掛牌')
    return output.getvalue()

# === UI 介面 ===
st.title("📊 台灣 IPO 競拍自動追蹤 (除錯模式)")
st.markdown(f"最後更新：{date.today()}")

# 顯示除錯資訊的區塊 (如果成功可摺疊)
with st.expander("🔍 查看原始資料抓取狀態 (除錯用)", expanded=False):
    st.write("正在測試連線...")

df_all, error_msg = get_twse_auction_data()

if error_msg:
    st.error(f"❌ 發生錯誤：{error_msg}")
    st.info("請將上面的錯誤訊息截圖給我。")
elif df_all is not None and not df_all.empty:
    # 成功抓到資料，顯示預覽
    with st.expander("✅ 成功抓取！點此查看原始表格"):
        st.dataframe(df_all.head())

    df_ongoing, df_auctioned, df_listed = classify_data(df_all)

    # 下載按鈕
    st.download_button(
        label="📥 下載 Excel 報表",
        data=convert_df_to_excel(df_ongoing, df_auctioned, df_listed),
        file_name=f'IPO_Auction_{date.today()}.xlsx'
    )

    tab1, tab2, tab3 = st.tabs(["🚀 進行中", "⚖️ 已開標", "🏁 已掛牌"])
    tab1.dataframe(df_ongoing, use_container_width=True)
    tab2.dataframe(df_auctioned, use_container_width=True)
    tab3.dataframe(df_listed, use_container_width=True)
else:
    st.warning("⚠️ 連線成功，但沒有資料 (Data is empty)。")
