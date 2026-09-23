import baostock as bs
import pandas as pd
import time

lg = bs.login()

# 1. 获取成分股列表（同上）
rs = bs.query_hs300_stocks()
hs300_stocks = []
while (rs.error_code == '0') & rs.next():
    hs300_stocks.append(rs.get_row_data())
df_stocks = pd.DataFrame(hs300_stocks, columns=rs.fields)

# 2. 循环下载每只股票的日线数据
all_data = []  # 用于存放所有股票的行情数据

for index, row in df_stocks.iterrows():
    code = row['code']
    name = row['code_name']
    
    # 请求单只股票的日线数据
    k_rs = bs.query_history_k_data_plus(
        code,
        "date,code,open,high,low,close,preclose,volume,amount,pctChg,turn",  # 选择你需要的字段
        start_date='2024-01-01',
        end_date='2024-12-31',
        frequency="d",       # d=日线
        adjustflag="2"       # 2=前复权（回测常用），也可以选 "3" 不复权
    )
    
    # 收集该股票的数据
    while (k_rs.error_code == '0') & k_rs.next():
        all_data.append(k_rs.get_row_data())
    
    # 礼貌性暂停，避免请求过快
    time.sleep(0.1)
    
    # 可选：打印进度
    if (index + 1) % 50 == 0:
        print(f"已处理 {index + 1}/{len(df_stocks)} 只股票")

# 3. 汇总为一个大 DataFrame
df_all = pd.DataFrame(all_data, columns=k_rs.fields)
print(f"共获取到 {len(df_all)} 条行情记录")

# 保存到 CSV
df_all.to_csv("hs300_daily_data.csv", index=False, encoding="utf-8-sig")

bs.logout()