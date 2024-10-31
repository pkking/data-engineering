import gradio as gr
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import json
from datetime import datetime, timedelta
import re

def parse_link_header(link_header):
    """
    解析Link Header，提取分页URL
    
    Link Header示例:
    <https://huggingface.co/api/datasets?page=2>; rel="next", 
    <https://huggingface.co/api/datasets?page=10>; rel="last"
    
    返回字典，包含next和last页面的URL
    """
    if not link_header:
        return {}
    
    url_match = re.search(r'<([^>]+)>', link_header)
    rel_match = re.search(r'rel="([^"]+)"', link_header)
    
    if url_match and rel_match:
        url = url_match.group(1)
    
    return url

def fetch_paginated_data(base_url, params=None):
    """
    使用Link Header处理分页获取
    
    Args:
        base_url (str): 基础URL
        params (dict, optional): 查询参数
    
    Returns:
        list: 所有页面的数据
    """
    if params is None:
        params = {}
    
    all_results = []
    current_url = base_url
    
    while current_url:
        try:
            response = requests.get(current_url, params=params)
            response.raise_for_status()
            
            # 解析响应数据
            current_results = response.json()
            all_results.extend(current_results)
            
            # 解析Link Header
            link_header = response.headers.get('Link')
            link = parse_link_header(link_header)
            
            # 确定下一页URL
            current_url = link.get('next')
            params = {}  # 清空params，使用完整的next URL
        
        except Exception as e:
            print(f"分页获取数据时发生错误 {link}: {e}")
            break
    
    return all_results

class HuggingFaceStatsExplorer:
    def __init__(self, cache_dir='./hf_cache'):
        self.base_url = "https://huggingface.co/api/"
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_path(self, resource_type):
        """生成缓存文件路径"""
        return os.path.join(self.cache_dir, f"{resource_type}_cache.json")
    
    def _is_cache_valid(self, cache_path):
        """检查缓存是否有效（1天内）"""
        if not os.path.exists(cache_path):
            return False
        
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        cache_time = datetime.fromisoformat(cache_data.get('timestamp', '2000-01-01'))
        return datetime.now() - cache_time < timedelta(days=1)
    
    def _fetch_all_pages(self, base_url, params=None):
        """
        使用Link Header处理分页获取数据
        """
        return fetch_paginated_data(base_url, params)
    
    def fetch_datasets(self, force_refresh=False):
        """获取所有数据集"""
        cache_path = self._get_cache_path('datasets')
        
        # 检查缓存
        if not force_refresh and self._is_cache_valid(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)['data']
        
        # 获取数据
        url = self.base_url + "datasets"
        datasets = self._fetch_all_pages(url)
        
        # 处理数据
        processed_datasets = []
        for dataset in datasets:
            processed_datasets.append({
                "name": dataset.get('id', 'N/A'),
                "downloads": dataset.get('downloads', 0),
                "likes": dataset.get('likes', 0),
                "tags": ', '.join(dataset.get('tags', [])),
                "description": dataset.get('description', '')
            })
        
        # 缓存数据
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'data': processed_datasets
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
        
        return processed_datasets
    
    def fetch_models(self, force_refresh=False):
        """获取所有模型"""
        cache_path = self._get_cache_path('models')
        
        # 检查缓存
        if not force_refresh and self._is_cache_valid(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)['data']
        
        # 获取数据
        url = self.base_url + "models"
        models = self._fetch_all_pages(url)
        
        # 处理数据
        processed_models = []
        for model in models:
            processed_models.append({
                "name": model.get('id', 'N/A'),
                "downloads": model.get('downloads', 0),
                "likes": model.get('likes', 0),
                "task": model.get('task', 'N/A'),
                "description": model.get('description', '')
            })
        
        # 缓存数据
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'data': processed_models
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
        
        return processed_models
    
    def fetch_spaces(self, force_refresh=False):
        """获取所有空间"""
        cache_path = self._get_cache_path('spaces')
        
        # 检查缓存
        if not force_refresh and self._is_cache_valid(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)['data']
        
        # 获取数据
        url = self.base_url + "spaces"
        spaces = self._fetch_all_pages(url)
        
        # 处理数据
        processed_spaces = []
        for space in spaces:
            processed_spaces.append({
                "name": space.get('id', 'N/A'),
                "likes": space.get('likes', 0),
                "run_time": space.get('run_time', 'N/A'),
                "sdk": space.get('sdk', 'N/A'),
                "description": space.get('description', '')
            })
        
        # 缓存数据
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'data': processed_spaces
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
        
        return processed_spaces
    
    def filter_data(self, data, search_term):
        """根据搜索词过滤数据"""
        if not search_term:
            return data
        
        # 不区分大小写的模糊搜索
        search_term = search_term.lower()
        return [
            item for item in data 
            if (search_term in str(item.get('name', '')).lower() or 
                search_term in str(item.get('description', '')).lower() or 
                search_term in str(item.get('tags', '')).lower())
        ]
    
    def create_visualization(self, data, resource_type):
        """创建数据可视化"""
        df = pd.DataFrame(data)
        
        if df.empty:
            return None
        
        if resource_type == "Datasets":
            fig = px.bar(
                df.nlargest(10, 'downloads'), 
                x='name', y='downloads', 
                title='Top 10 Datasets by Downloads',
                labels={'name': 'Dataset Name', 'downloads': 'Downloads'}
            )
        elif resource_type == "Models":
            fig = px.scatter(
                df, 
                x='downloads', y='likes', 
                color='task', 
                hover_name='name',
                title='Model Downloads vs Likes',
                labels={'downloads': 'Downloads', 'likes': 'Likes', 'task': 'Task'}
            )
        else:  # Spaces
            fig = px.pie(
                df.nlargest(10, 'likes'), 
                values='likes', 
                names='name', 
                title='Top 10 Spaces by Likes'
            )
        
        return fig

def main():
    explorer = HuggingFaceStatsExplorer()
    
    with gr.Blocks() as demo:
        gr.Markdown("# Hugging Face Statistics Explorer")
        
        with gr.Tab("Datasets"):
            with gr.Row():
                dataset_refresh_btn = gr.Button("获取所有数据集")
                dataset_search_input = gr.Textbox(label="搜索数据集")
                dataset_search_btn = gr.Button("搜索")
            
            dataset_output = gr.Dataframe(label="数据集统计")
            dataset_plot = gr.Plot(label="数据集可视化")
            
            # 获取全部数据集
            dataset_refresh_btn.click(
                fn=lambda: (
                    explorer.fetch_datasets(force_refresh=True),
                    explorer.fetch_datasets()
                ),
                outputs=[dataset_output, dataset_output]
            )
            
            # 搜索数据集
            dataset_search_btn.click(
                fn=lambda search_term: (
                    pd.DataFrame(
                        explorer.filter_data(
                            explorer.fetch_datasets(), 
                            search_term
                        )
                    ),
                    explorer.create_visualization(
                        explorer.filter_data(
                            explorer.fetch_datasets(), 
                            search_term
                        ), 
                        "Datasets"
                    )
                ),
                inputs=dataset_search_input,
                outputs=[dataset_output, dataset_plot]
            )
        
        with gr.Tab("Models"):
            with gr.Row():
                model_refresh_btn = gr.Button("获取所有模型")
                model_search_input = gr.Textbox(label="搜索模型")
                model_search_btn = gr.Button("搜索")
            
            model_output = gr.Dataframe(label="模型统计")
            model_plot = gr.Plot(label="模型可视化")
            
            # 获取全部模型
            model_refresh_btn.click(
                fn=lambda: (
                    explorer.fetch_models(force_refresh=True),
                    explorer.fetch_models()
                ),
                outputs=[model_output, model_output]
            )
            
            # 搜索模型
            model_search_btn.click(
                fn=lambda search_term: (
                    pd.DataFrame(
                        explorer.filter_data(
                            explorer.fetch_models(), 
                            search_term
                        )
                    ),
                    explorer.create_visualization(
                        explorer.filter_data(
                            explorer.fetch_models(), 
                            search_term
                        ), 
                        "Models"
                    )
                ),
                inputs=model_search_input,
                outputs=[model_output, model_plot]
            )
        
        with gr.Tab("Spaces"):
            with gr.Row():
                space_refresh_btn = gr.Button("获取所有空间")
                space_search_input = gr.Textbox(label="搜索空间")
                space_search_btn = gr.Button("搜索")
            
            space_output = gr.Dataframe(label="空间统计")
            space_plot = gr.Plot(label="空间可视化")
            
            # 获取全部空间
            space_refresh_btn.click(
                fn=lambda: (
                    explorer.fetch_spaces(force_refresh=True),
                    explorer.fetch_spaces()
                ),
                outputs=[space_output, space_output]
            )
            
            # 搜索空间
            space_search_btn.click(
                fn=lambda search_term: (
                    pd.DataFrame(
                        explorer.filter_data(
                            explorer.fetch_spaces(), 
                            search_term
                        )
                    ),
                    explorer.create_visualization(
                        explorer.filter_data(
                            explorer.fetch_spaces(), 
                            search_term
                        ), 
                        "Spaces"
                    )
                ),
                inputs=space_search_input,
                outputs=[space_output, space_plot]
            )
    
    return demo

if __name__ == "__main__":
    demo = main()
    demo.launch()