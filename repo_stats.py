import aiohttp
import argparse
import json
import asyncio
import os
import shutil
import subprocess
import logging
import sys  # 正确导入 sys
from prettytable import PrettyTable
from datetime import datetime
import pygit2
import signal  # 导入 signal 模块
from tqdm.asyncio import tqdm

# 配置日志，输出到 stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # 指定输出流为 stdout
)
logger = logging.getLogger(__name__)

# 全局变量，用于控制任务的取消
tasks_to_cancel = []

def signal_handler(sig, frame):
    """处理 Control-C 中断信号。"""
    logger.info("接收到中断信号，正在取消任务...")
    for task in tasks_to_cancel:
        if not task.done():
            task.cancel()  # 取消任务
    logger.info("任务取消完成，程序即将退出。")
    sys.exit(0)  # 立即退出程序


async def get_my_username(session, token):
    """通过 API 获取 token 持有者的用户名。"""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = "https://api.github.com/user"
    try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            user_data = await response.json()
            return user_data.get("login")
    except aiohttp.ClientError as e:
        logger.error(f"获取用户信息失败：{e}")
        return None

async def get_repo_stats(session, token, org_name, my_username, repo_name, year=None):
    """异步获取指定仓库的统计信息。"""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{org_name}/{repo_name}"
    try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            repo_data = await response.json()

            stats = {
                "name": repo_data["name"],
                "full_name": repo_data["full_name"],
                "description": repo_data.get("description", "N/A"),
                "stars": repo_data["stargazers_count"],
                "forks": repo_data["forks_count"],
                "open_issues": repo_data["open_issues_count"],
                "created_at": repo_data["created_at"],
                "updated_at": repo_data["updated_at"],
                "language": repo_data.get("language", "N/A")
            }

            commits_url = f"https://api.github.com/repos/{org_name}/{repo_name}/commits"
            commits_count = 0
            page = 1
            while True:
                params = {'per_page': 100, 'page': page}
                if year:
                    params['since'] = f"{year}-01-01T00:00:00Z"
                    params['until'] = f"{year+1}-01-01T00:00:00Z"
                async with session.get(commits_url, headers=headers, params=params) as commits_response:
                    commits_response.raise_for_status()
                    commits = await commits_response.json()
                    if not commits:
                        break
                    commits_count += len(commits)
                    page += 1

            stats["commits_count"] = commits_count

            stats["lines_of_code"] = await get_lines_of_code(token, org_name, my_username, repo_name)
            return stats
    except aiohttp.ClientError as e:
        logger.error(f"获取仓库 {repo_name} 信息时发生错误：{e}")
        return None

async def get_lines_of_code(token, org_name, my_username, repo_name):
    """使用 pygit2 克隆仓库并使用 cloc 统计代码行数。"""
    repo_url = f"https://{my_username}:{token}@github.com/{org_name}/{repo_name}.git"
    local_path = f"./temp_repos/{org_name}/{repo_name}"

    try:
        if os.path.exists(local_path):
            shutil.rmtree(local_path)
        repo = pygit2.clone_repository(repo_url, local_path)

        cloc_output = subprocess.check_output(["cloc", "--json", local_path], text=True, encoding="utf-8")
        cloc_data = json.loads(cloc_output)
        lines_of_code = cloc_data.get("SUM", {}).get("code", 0)

        return lines_of_code

    except pygit2.GitError as e:
        logger.error(f"克隆仓库 {repo_name} 失败: {e}")
        return "克隆失败"
    except FileNotFoundError:
        logger.error("请确保已安装 cloc (http://cloc.sourceforge.net/)。")
        return "未安装 cloc"
    except subprocess.CalledProcessError as e:
        logger.error(f"cloc 执行 {repo_name} 失败: {e}")
        return "cloc 执行失败"
    except json.JSONDecodeError as e:
        logger.error(f"解析 cloc 输出 {repo_name} 失败: {e}. Cloc Output: {cloc_output if 'cloc_output' in locals() else 'N/A'}")
        return "解析 cloc 输出失败"
    finally:
        if os.path.exists(local_path):
            shutil.rmtree(local_path)

async def get_org_repos(session, token, org_name):
    """获取组织下的所有仓库名"""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/orgs/{org_name}/repos"
    repos = []
    page = 1
    while True:
        params = {'per_page': 100, 'page': page}
        try:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                repo_data = await response.json()
                if not repo_data:
                    break
                for repo in repo_data:
                    repos.append(repo['name'])
                page += 1
        except aiohttp.ClientError as e:
            logger.error(f"获取组织仓库列表失败: {e}")
            return [] # 如果获取失败，返回空列表，避免后续出错
    return repos

async def process_repo(session, token, org_name, my_username, repo, year_to_use):
    """处理单个仓库的统计信息。优化：检查目标年份是否有提交，无则跳过。"""
    logger.info(f"开始处理仓库：{org_name}/{repo}")
    try:
        # 无论 year_to_use 是否为当前年份，都先检查是否有提交
        commits_url = f"https://api.github.com/repos/{org_name}/{repo}/commits"
        headers = {"Authorization": f"token {token}"}
        params = {'per_page': 1, 'since': f"{year_to_use}-01-01T00:00:00Z", 'until': f"{year_to_use+1}-01-01T00:00:00Z"}
        async with session.get(commits_url, headers=headers, params=params) as commits_response:
            commits_response.raise_for_status()
            commits = await commits_response.json()
            if not commits:
                logger.info(f"仓库 {org_name}/{repo} 在 {year_to_use} 年没有提交，跳过。")
                return repo, None  # 没有提交，直接返回None

        # 只有在有提交的情况下才进行后续的统计
        repo_stats = await get_repo_stats(session, token, org_name, my_username, repo, year_to_use)
        if repo_stats:
            logger.info(f"成功获取仓库 {org_name}/{repo} 的统计信息")
            return repo, repo_stats
        else:
            logger.warning(f"获取仓库 {org_name}/{repo} 统计信息失败")
            return repo, None
    except Exception as e:
        logger.error(f"处理仓库 {org_name}/{repo} 时发生异常：{e}")
        return repo, None

async def main():
    parser = argparse.ArgumentParser(description="统计 GitHub 组织下所有仓库的信息。")
    parser.add_argument("-t", "--token", required=True, help="GitHub Personal Access Token。")
    parser.add_argument("-o", "--org", required=True, help="需要统计的组织名。")
    parser.add_argument("-y", "--year", type=int, help="要统计的年份 (可选)。")
    parser.add_argument("-O", "--output", help="输出 JSON 文件名 (可选)。")

    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, signal_handler)  # 注册信号处理函数

    async with aiohttp.ClientSession() as session:
        my_username = await get_my_username(session, args.token)
        if not my_username:
            print("无法获取您的用户名，请检查您的 Token 是否有效。")
            return

        current_year = datetime.now().year
        year_to_use = args.year if args.year else current_year

        output_filename = args.output if args.output else f"{args.org}_{year_to_use}_stats.json"

        repos = await get_org_repos(session, args.token, args.org)

        tasks = [process_repo(session, args.token, args.org, my_username, repo, year_to_use) for repo in repos]
        global tasks_to_cancel # 声明全局变量
        tasks_to_cancel = tasks  # 将任务列表赋值给全局变量

        all_repo_stats = {}
        try:
            for future in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="正在处理仓库"):
                try: # 捕获 CancelledError
                    repo, stats = await future
                    if stats:
                        all_repo_stats[repo] = stats
                except asyncio.CancelledError:
                    logger.info("一个任务被取消。")
        except asyncio.CancelledError:
            logger.info("主任务被取消。")
        finally:
            if all_repo_stats:
                with open(output_filename, "w", encoding="utf-8") as f:
                    json.dump(all_repo_stats, f, indent=4, ensure_ascii=False)
                logger.info(f"统计信息已保存到 {output_filename}")
            else:
                logger.warning("没有获取到任何仓库的数据，请检查组织名或网络连接")

if __name__ == "__main__":
    asyncio.run(main())
