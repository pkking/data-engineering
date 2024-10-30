import requests
import re
import time
import json
import os
from typing import Generator, Optional, Dict, Any, Tuple, List
from datetime import datetime
from collections import defaultdict
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class HuggingFaceModelsFetcher:
    """处理 Hugging Face 模型 API 的分页请求、缓存和统计"""

    def __init__(self,
                 base_url: str = "https://huggingface.co/api/models",
                 auth_token: Optional[str] = None,
                 rate_limit: float = 1.0,
                 cache_file: str = "huggingface_models_cache.json",
                 cache_expiry_hours: int = 24,
                 max_retries: int = 3,
                 backoff_factor: float = 0.5,
                 retry_status_codes: Optional[List[int]] = None):
        """
        初始化获取器

        Args:
            base_url: Hugging Face API 的基础URL
            auth_token: Hugging Face API token (可选)
            rate_limit: 请求间隔时间(秒)
            cache_file: 缓存文件路径
            cache_expiry_hours: 缓存有效期(小时)
            max_retries: 最大重试次数
            backoff_factor: 重试延迟的指数因子
            retry_status_codes: 需要重试的HTTP状态码列表
        """
        self.base_url = base_url
        self.headers = {}
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.rate_limit = rate_limit
        self.cache_file = cache_file
        self.cache_expiry_hours = cache_expiry_hours

        # 配置重试机制
        if retry_status_codes is None:
            retry_status_codes = [429, 500, 502, 503, 504]

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=retry_status_codes,
            allowed_methods=["GET"]
        )

        # 创建带有重试机制的会话
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _make_request(self, url: str) -> requests.Response:
        """
        发送GET请求并处理重试

        Args:
            url: 请求URL

        Returns:
            Response对象

        Raises:
            requests.RequestException: 当请求失败且重试耗尽时抛出
        """
        try:
            response = self.session.get(url, headers=self.headers)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"\n请求失败 (URL: {url}): {str(e)}")
            raise

    def _is_cache_valid(self) -> bool:
        """检查缓存是否存在且在有效期内"""
        if not os.path.exists(self.cache_file):
            return False

        # 检查文件修改时间
        file_mtime = os.path.getmtime(self.cache_file)
        cache_age_hours = (time.time() - file_mtime) / 3600

        return cache_age_hours < self.cache_expiry_hours

    def _load_cache(self) -> Optional[List[Dict[str, Any]]]:
        """从缓存文件加载数据"""
        try:
            if self._is_cache_valid():
                print(f"从缓存文件加载数据: {self.cache_file}")
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                print(f"已加载 {len(cache_data)} 条模型数据")
                return cache_data
        except Exception as e:
            print(f"读取缓存文件失败: {str(e)}")
        return None

    def _save_cache(self, data: List[Dict[str, Any]]):
        """保存数据到缓存文件"""
        try:
            print(f"\n保存数据到缓存文件: {self.cache_file}")
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"已保存 {len(data)} 条模型数据")
        except Exception as e:
            print(f"保存缓存文件失败: {str(e)}")

    def _extract_next_link(self, link_header: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
        """从 Link header 中提取下一页的 URL 和总页数"""
        if not link_header:
            return None, None

        next_url = None
        total_pages = None

        links = link_header.split(",")
        for link in links:
            if 'rel="next"' in link:
                match = re.match(r'<(.+)>;\s*rel="next"', link.strip())
                if match:
                    next_url = match.group(1)

            if 'rel="last"' in link:
                match = re.match(r'<(.+)>;\s*rel="last"', link.strip())
                if match:
                    last_url = match.group(1)
                    page_match = re.search(r'page=(\d+)', last_url)
                    if page_match:
                        total_pages = int(page_match.group(1))

        return next_url, total_pages

    def fetch_all_models(self) -> Generator[Dict[str, Any], None, None]:
        """获取所有模型信息的生成器"""
        # 首先尝试从缓存加载
        cached_data = self._load_cache()
        if cached_data is not None:
            for model in cached_data:
                yield model
            return

        # 如果没有有效缓存，则从API获取
        all_models = []
        next_url = self.base_url
        current_page = 1
        total_pages = None
        start_time = time.time()
        models_processed = 0

        # 首次请求以获取总页数
        try:
            response = self._make_request(next_url)
            next_url, total_pages = self._extract_next_link(response.headers.get("Link"))

            if total_pages:
                progress_bar = tqdm(total=total_pages, desc="获取模型数据",
                                  unit="页", dynamic_ncols=True)
            else:
                print("警告: 无法获取总页数，将显示简化的进度信息")

            # 处理第一页数据
            first_page_models = response.json()
            all_models.extend(first_page_models)
            models_processed += len(first_page_models)

            if total_pages:
                progress_bar.update(1)
                progress_bar.set_postfix({
                    'models': models_processed,
                    'avg_models/page': f"{models_processed/current_page:.1f}"
                })

            for model in first_page_models:
                yield model

        except requests.RequestException as e:
            print(f"初始请求失败: {str(e)}")
            raise

        while next_url:
            try:
                # 添加请求间隔
                time.sleep(self.rate_limit)

                response = self._make_request(next_url)

                # 获取当前页的模型数据
                models = response.json()
                all_models.extend(models)
                models_in_page = len(models)
                models_processed += models_in_page

                # 更新进度
                if total_pages:
                    progress_bar.update(1)
                    progress_bar.set_postfix({
                        'models': models_processed,
                        'avg_models/page': f"{models_processed/current_page:.1f}"
                    })
                else:
                    print(f"处理第 {current_page} 页，已获取 {models_processed} 个模型")

                # 产出当前页的模型数据
                for model in models:
                    yield model

                # 获取下一页
                next_url, _ = self._extract_next_link(response.headers.get("Link"))
                current_page += 1

            except requests.RequestException as e:
                print(f"\n请求失败: {str(e)}")
                raise
            except Exception as e:
                print(f"\n处理数据时发生错误: {str(e)}")
                break

        if total_pages:
            progress_bar.close()

        # 保存到缓存
        self._save_cache(all_models)

        # 打印最终统计信息
        elapsed_time = time.time() - start_time
        print(f"\n获取完成:")
        print(f"- 总页数: {current_page}")
        print(f"- 总模型数: {models_processed}")
        print(f"- 平均每页模型数: {models_processed/current_page:.1f}")
        print(f"- 总耗时: {elapsed_time:.1f}秒")
        print(f"- 平均每页耗时: {elapsed_time/current_page:.1f}秒")

    def get_2024_monthly_stats(self) -> Dict[str, Dict[str, Any]]:
        """统计2024年每月的模型数量和详细信息"""
        monthly_stats = defaultdict(lambda: {'count': 0, 'models': []})
        processed_count = 0

        print("开始统计2024年月度数据...")

        for model in self.fetch_all_models():
            processed_count += 1

            # 获取模型创建时间
            created_at = model.get('createdAt')
            if not created_at:
                continue

            try:
                # 解析时间戳为datetime对象
                created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))

                # 只统计2024年的数据
                if created_date.year == 2024:
                    month_key = created_date.strftime('%Y-%m')
                    monthly_stats[month_key]['count'] += 1
                    monthly_stats[month_key]['models'].append({
                        'id': model.get('id'),
                        'modelId': model.get('modelId'),
                        'created_at': created_at,
                        'likes': model.get('likes', 0),
                        'downloads': model.get('downloads', 0)
                    })

            except (ValueError, AttributeError) as e:
                print(f"\n处理日期时发生错误: {str(e)}")
                continue

        return dict(monthly_stats)

def print_monthly_stats(stats: Dict[str, Dict[str, Any]]):
    """打印月度统计信息的漂亮格式"""
    print("\n2024年每月模型发布统计")
    print("=" * 50)
    print(f"{'月份':^10} | {'模型数量':^10} | {'平均点赞':^10} | {'平均下载':^10}")
    print("-" * 50)

    for month, data in sorted(stats.items()):
        models = data['models']
        avg_likes = sum(m['likes'] for m in models) / len(models) if models else 0
        avg_downloads = sum(m['downloads'] for m in models) / len(models) if models else 0

        print(f"{month:^10} | {data['count']:^10} | {avg_likes:^10.1f} | {avg_downloads:^10.1f}")

def main():
    """主函数示例"""
    # 初始化获取器
    fetcher = HuggingFaceModelsFetcher(
        auth_token="YOUR_TOKEN_HERE",  # 替换为你的 token
        rate_limit=1.0,  # 每次请求间隔1秒
        cache_file="huggingface_models_cache.json",  # 缓存文件路径
        cache_expiry_hours=24,  # 缓存24小时有效
        max_retries=3,  # 最大重试3次
        backoff_factor=0.5,  # 重试延迟的指数因子
        retry_status_codes=[429, 500, 502, 503, 504]  # 需要重试的HTTP状态码
    )

    try:
        # 获取2024年每月统计
        monthly_stats = fetcher.get_2024_monthly_stats()

        # 打印统计信息
        print_monthly_stats(monthly_stats)

        # 输出详细信息示例
        print("\n详细信息示例:")
        print("=" * 50)
        for month, data in sorted(monthly_stats.items()):
            print(f"\n{month} 热门模型 (前3个):")
            # 按点赞数排序
            sorted_models = sorted(data['models'], key=lambda x: x['likes'], reverse=True)[:3]
            for model in sorted_models:
                print(f"- {model['id']}: {model['likes']} 赞, {model['downloads']} 下载")

    except requests.RequestException as e:
        print(f"获取模型时发生错误: {str(e)}")

if __name__ == "__main__":
    main()
