from datetime import datetime,timezone,timedelta
import pandas as pd

def datetime_from_timestamp(timestamp):
    """datetime对象转字符串（保持原格式）"""
    dt_from_timestamp = datetime.fromtimestamp(timestamp,tz=timezone.utc)
    full_str = dt_from_timestamp.strftime("%Y-%m-%d-%H:%M:%S.%f")
    
    return full_str


a = datetime_from_timestamp(2020606)

file = "./log/vehicle_imu.csv"
df = pd.read_csv(file, encoding='gbk',)
print(f"数据形状: {df.shape}")  # (行数, 列数)
print(f"列名: {list(df.columns)}")
print(f"数据预览:")
print(df.head())
# df.rename(columns={'timestamp': 'date_time'}, inplace=True)
# df.rename(columns={'timestamp_sample': 'time_ts'}, inplace=True)
# df.to_csv(file, index=False, encoding='gbk')

# first_col_name =  df["date_time"]
# second_col_name = df["time_ts"]
# a = first_col_name.tolist()
# b = second_col_name.tolist()
# for i, timestamp in enumerate(b):
#     a[i] =datetime_from_timestamp( int( a[i] + float(timestamp)))[:19]

# a = first_col_name.tolist()
# c= [x.replace("-","_").replace(':',"_") for x in a ]

# df["date_time"] = c

print(df)
# df.to_csv(file, index=False, encoding='gbk')