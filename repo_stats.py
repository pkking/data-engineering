import aiohttp
import argparse
import json
import asyncio
import os
import shutil
import subprocess
import logging
import sys
import signal
from datetime import datetime, timezone
import pygit2
from tqdm.asyncio import tqdm
import urllib.parse  # 正确导入 urllib.parse

# 配置日志，输出到 stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # 指定输出流为 stdout
)
logger = logging.getLogger(__name__)

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

async def get_latest_commit_sha(session, token, org_name, repo_name, year):
    """获取指定年份的最新 commit SHA。"""
    commits_url = f"https://api.github.com/repos/{org_name}/{repo_name}/commits"
    headers = {"Authorization": f"token {token}"}
    params = {'per_page': 1, 'until': f"{year + 1}-01-01T00:00:00Z"} # 关键修改：添加 until 参数
    async with session.get(commits_url, headers=headers, params=params) as response:
        if response.status == 200:
            commits = await response.json()
            if commits:
                return commits[0].get("sha")
            else:
                return None
        else:
            logger.error(f"获取 {year} 年最新 commit SHA 失败: {response.status}")
            return None

async def get_repo_creation_year(session, token, org_name, repo_name):
    """获取仓库的创建年份。"""
    repo_url = f"https://api.github.com/repos/{org_name}/{repo_name}"
    headers = {"Authorization": f"token {token}"}
    async with session.get(repo_url, headers=headers) as response:
        response.raise_for_status()
        repo_data = await response.json()
        created_at_str = repo_data.get("created_at")
        if created_at_str:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) #处理时区问题
            return created_at.year
        else:
            logger.warning(f"无法获取仓库 {org_name}/{repo_name} 的创建时间。")
            return None

DATA_FILENAME = "repo_stats.json"  # 数据文件名

async def get_commits_count_local(repo_path, year):
    """本地使用 git log 统计指定年份的 commits 数量。"""
    try:
        start_date = f"{year}-01-01"
        end_date = f"{year+1}-01-01"
        command = [
            "git", "log",
            f"--since={start_date}",
            f"--until={end_date}",
            "--pretty=format:%h", # 只输出 commit hash，提高效率
            "--shortstat" # 获取提交的统计信息
        ]
        result = subprocess.run(command, cwd=repo_path, capture_output=True, text=True, check=True)
        # 解析输出，统计 commits 数量
        commits = result.stdout.strip().split('\n')
        commits_count = len([c for c in commits if c])
        return commits_count
    except subprocess.CalledProcessError as e:
        logger.error(f"git log 命令执行失败：{e}")
        return None

async def get_lines_of_code_local(repo_path):
    """本地使用 cloc 获取代码行数。"""
    try:
        result = subprocess.run(["cloc", repo_path, "--json"], capture_output=True, text=True, check=True)
        cloc_data = json.loads(result.stdout)
        if "SUM" in cloc_data:
            del cloc_data["SUM"]
        total_lines = sum(lang_data.get("code", 0) for lang_data in cloc_data.values())
        return total_lines
    except FileNotFoundError:
        logger.error("cloc 命令未找到，请确保已安装 cloc。")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"cloc 命令执行失败：{e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"cloc 输出 JSON 解析失败：{e}")
        return None
    
async def async_clone_repo(repo_url, repo_path):
    """异步克隆仓库。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "clone", repo_url, repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            if stderr:
                err_msg = stderr.decode().strip()
                logger.error(f"克隆仓库 {repo_url} 失败: {err_msg}")
            else:
                logger.error(f"克隆仓库 {repo_url} 失败，返回码: {process.returncode}")
            return False
        return True
    except asyncio.CancelledError:
        logger.info(f"克隆仓库 {repo_url} 的任务被取消。")
        return False
    except Exception as e:
        logger.error(f"克隆仓库 {repo_url} 时发生异常：{e}")
        return False

async def process_repo(session, token, org_name, my_username, repo, all_repo_stats, exclude_repos, end_year):
    """处理单个仓库的统计信息。"""
    if repo in exclude_repos:
        logger.info(f"仓库 {org_name}/{repo} 在排除列表中，跳过。")
        return

    repo_path = None  # 在 try 块外部初始化 repo_path

    try:
        creation_year = await get_repo_creation_year(session, token, org_name, repo)
        if not creation_year:
            return

        encoded_token = urllib.parse.quote(token, safe="")
        repo_url = f"https://{my_username}:{encoded_token}@github.com/{org_name}/{repo}.git"
        repo_path = f"{org_name}/{repo}" # 在克隆之前赋值

        try:
            if os.path.exists(repo_path):
                shutil.rmtree(repo_path)

            clone_success = await async_clone_repo(repo_url, repo_path) # 异步克隆
            if not clone_success: # 克隆失败直接返回
                return

        except Exception as e:
            logger.error(f"克隆仓库 {repo_url} 时发生异常：{e}")
            return

        for year in range(creation_year, end_year + 1):
            latest_commit_sha = await get_latest_commit_sha(session, token, org_name, repo, year)
            if not latest_commit_sha:
                logger.warning(f"无法获取仓库 {org_name}/{repo} {year} 年的最新 commit SHA。")
                continue

            if repo not in all_repo_stats:
                all_repo_stats[repo] = {'stats': {}}

            if str(year) in all_repo_stats[repo]['stats'] and all_repo_stats[repo]['stats'][str(year)].get('latest_commit_sha') == latest_commit_sha:
                logger.info(f"仓库 {org_name}/{repo} {year} 年没有更新，跳过。")
                continue

            commits_count = await get_commits_count_local(repo_path, year)
            lines_of_code = await get_lines_of_code_local(repo_path)

            if commits_count is not None and lines_of_code is not None:
                all_repo_stats[repo]['stats'][str(year)] = {
                    "latest_commit_sha": latest_commit_sha,
                    "lines_of_code": lines_of_code,
                    "commits_count": commits_count
                }
                logger.info(f"成功获取仓库 {org_name}/{repo} {year} 年的统计信息，包含 {commits_count} 个提交。")
            else:
                logger.warning(f"获取仓库 {org_name}/{repo} {year} 年统计信息失败")

    except Exception as e:
        logger.error(f"处理仓库 {org_name}/{repo} 时发生异常：{e}")
        return
    finally:
        if repo_path and os.path.exists(repo_path): # 检查 repo_path 是否被赋值
            shutil.rmtree(repo_path)

async def main():
    parser = argparse.ArgumentParser(description="统计 GitHub 组织下所有仓库的信息。")
    parser.add_argument("-t", "--token", required=True, help="GitHub Personal Access Token。")
    parser.add_argument("-o", "--org", required=True, help="需要统计的组织名。")
    parser.add_argument("-y", "--year", type=int, help="要统计的年份 (可选)。")
    parser.add_argument("-O", "--output", help="输出 JSON 文件名 (可选)。")
    parser.add_argument("-e", "--exclude", nargs='+', default=[], help="需要排除的仓库名列表 (可选)。") # 添加 exclude 参数

    args = parser.parse_args()

    end_year = args.year if args.year else datetime.now().year # 如果 year 参数未提供，则使用当前年份

    async with aiohttp.ClientSession() as session:
        my_username = await get_my_username(session, args.token)
        if not my_username:
            print("无法获取您的用户名，请检查您的 Token 是否有效。")
            return

        repos = await get_org_repos(session, args.token, args.org)
        exclude_repos = set(args.exclude)

        DATA_FILENAME = f"{args.org}_{end_year}_stats.json"  # 数据文件名包含截止年份
        try:
            with open(DATA_FILENAME, "r", encoding="utf-8") as f:
                all_repo_stats = json.load(f)
        except FileNotFoundError:
            all_repo_stats = {}

        tasks = [process_repo(session, args.token, args.org, my_username, repo, all_repo_stats, exclude_repos, end_year) for repo in repos] # 传递 end_year 参数
        global tasks_to_cancel
        tasks_to_cancel = tasks

        try:
            for future in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc=f"正在处理仓库至 {end_year} 年"): # 修改 tqdm 描述
                try:
                    await future
                except asyncio.CancelledError:
                    logger.info("一个任务被取消。")
        except asyncio.CancelledError:
                logger.info("主任务被取消。")
        finally:
            with open(DATA_FILENAME, "w", encoding="utf-8") as f:
                json.dump(all_repo_stats, f, indent=4, ensure_ascii=False)
            logger.info(f"统计信息已保存到 {DATA_FILENAME}")

if __name__ == "__main__":
    asyncio.run(main())
