import requests
import json
from datetime import datetime
import time

# ModelScope API接口
api_url = "https://modelscope.cn/api/v1/dolphin/models"

# 初始页码和页面大小
page_size = 100
page_number = 1

# 存储所有模型数据
all_models = []

print("开始获取ModelScope平台模型信息...")

# 持续获取直到最后一页
while True:
    params = {
        "PageSize": page_size,
        "PageNumber": page_number,
        "SortBy": "Default",
        "Target":"",
        "SingleCriterion": [],
    }
    
    response = requests.put(api_url, json=params)
    data = response.json()
    
    # 如果已经到最后一页,退出循环
    if not data["Data"]:
        break
    
    # 添加当前页的模型数据
    all_models.extend(data["Data"]["Model"]["Models"])
    
    # 更新页码
    page_number += 1
    
    # 输出进度信息
    print(f"已获取 {len(all_models)} 个模型信息...")
#    time.sleep(1)  # 添加一秒钟的延迟,避免频繁访问API

print("已完成模型信息爬取,正在统计数据...")

# 统计每个月新增的模型数量
monthly_counts = {}
for model in all_models:
    created_at = datetime.strptime(model["CreatedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
    month_year = created_at.strftime("%Y-%m")
    if month_year not in monthly_counts:
        monthly_counts[month_year] = 0
    monthly_counts[month_year] += 1

# 保存原始数据到JSON文件
with open("modelscope_models.json", "w") as f:
    json.dump(all_models, f, indent=4)

print("数据统计完成,结果如下:")
for month_year, count in monthly_counts.items():
    print(f"{month_year}: {count}")
print("原始数据已保存到 modelscope_models.json 文件。")