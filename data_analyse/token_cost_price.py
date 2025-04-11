# 通过分析excel计算token持有的成本价
import pandas as pd

# 读取excel
file_path = "D:/files/finance/欧易统一交易账单：2024-04-08~2025-04-08~UTC+8~369342.xlsx"
df = pd.read_excel(file_path)

# 选择需要的列
target_units = ['BTC', 'ETH', 'SUI', 'SOL', 'DOGE']
deal_type = ['买入']

# excel处理
print(df.columns.tolist())
df.columns = df.columns.str.strip()  # 去除空格
print(df.columns.tolist())
# 过滤数据
filtered_df = df[
    (df['交易单位'].isin(target_units)) &
    (df['交易类型'].isin(deal_type))
].copy()

# 计算每种token的成本价
filtered_df['成本'] = filtered_df['成交价'] * filtered_df['数量']
summary = filtered_df.groupby('交易单位').agg(
    总成本=('成本', 'sum'),
    总数量=('数量', 'sum')
)
summary['成本价'] = summary['总成本'] / summary['总数量']

# 输出结果
print(summary)

