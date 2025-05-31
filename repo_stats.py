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
import urllib.parse
import re
import asyncio
import aiohttp
import json
import os
import shutil
import subprocess
import logging
import sys
import signal
from datetime import datetime, timezone
import pygit2
from tqdm.asyncio import tqdm
import urllib.parse

# 配置日志，输出到 stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Conventional Commits 正则表达式
CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?: .+$"
)

def validate_conventional_commit(commit_message):
    """
    验证提交信息是否符合 Conventional Commits 标准。
    """
    return bool(CONVENTIONAL_COMMIT_PATTERN.match(commit_message.split('\n')[0]))

# 获取最大并发数，默认为 20
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "20"))
# 创建信号量
semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
logger.info(f"最大并发数为: {MAX_CONCURRENCY}")

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

async def get_contributor_commits_local(repo_path, year):
    """本地使用 git log 统计指定年份的每个贡献者的 commits 数量。"""
    try:
        start_date = f"{year}-01-01"
        end_date = f"{year+1}-01-01"
        command = [
            "git", "log",
            f"--since={start_date}",
            f"--until={end_date}",
            "--pretty=format:%an" # 只输出作者名
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.error(f"执行 git log --pretty=format:%an 失败: {err_msg}")
            return None

        authors = stdout.decode().strip().split('\n')
        contributor_commits = {}
        for author in authors:
            if author: # 避免空行
                contributor_commits[author] = contributor_commits.get(author, 0) + 1
        return contributor_commits
    except asyncio.CancelledError:
        logger.info(f"获取贡献者提交的任务被取消。")
        return None
    except Exception as e:
        logger.error(f"获取贡献者提交时发生异常：{e}")
        return None
    
async def get_all_commits_details_local(repo_path, year):
    """
    本地使用 git log 统计指定年份的每个提交的 SHA、作者和完整提交信息。
    """
    try:
        start_date = f"{year}-01-01"
        end_date = f"{year+1}-01-01"
        command = [
            "git", "log",
            f"--since={start_date}",
            f"--until={end_date}",
            "--pretty=format:%H%x00%an%x00%B" # SHA, 作者名, 完整提交信息 (使用空字符分隔)
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.error(f"执行 git log 获取提交详情失败: {err_msg}")
            return None

        commits_raw = stdout.decode().strip().split('\n\n') # 提交之间用两个换行符分隔
        detailed_commits = []
        for commit_block in commits_raw:
            if not commit_block.strip():
                continue
            parts = commit_block.split('\x00')
            if len(parts) >= 3:
                sha = parts[0].strip()
                author = parts[1].strip()
                message = parts[2].strip()
                detailed_commits.append({
                    "sha": sha,
                    "author": author,
                    "message": message
                })
        return detailed_commits
    except asyncio.CancelledError:
        logger.info(f"获取提交详情的任务被取消。")
        return None
    except Exception as e:
        logger.error(f"获取提交详情时发生异常：{e}")
        return None

async def check_pull_request_review(session, token, org_name, repo_name, commit_sha):
    """
    检查给定提交是否经过了代码审查（即是否是合并自一个已批准的拉取请求）。
    """
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    # 获取与提交关联的拉取请求
    pulls_url = f"https://api.github.com/repos/{org_name}/{repo_name}/commits/{commit_sha}/pulls"
    try:
        async with session.get(pulls_url, headers=headers) as response:
            response.raise_for_status()
            pulls_data = await response.json()

            for pull in pulls_data:
                if pull.get("merged_at"): # 检查是否已合并
                    # 获取拉取请求的审查列表
                    reviews_url = pull["_links"]["reviews"]["href"]
                    async with session.get(reviews_url, headers=headers) as review_response:
                        review_response.raise_for_status()
                        reviews_data = await review_response.json()
                        for review in reviews_data:
                            if review.get("state") == "APPROVED":
                                return True # 找到一个已批准的审查
            return False # 没有找到已合并且已批准的拉取请求
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            logger.warning(f"未找到提交 {commit_sha} 相关的拉取请求或审查信息。")
        else:
            logger.error(f"检查提交 {commit_sha} 的拉取请求审查失败: {e}")
        return False
    except aiohttp.ClientError as e:
        logger.error(f"检查提交 {commit_sha} 的拉取请求审查时发生网络错误: {e}")
        return False
    except Exception as e:
        logger.error(f"检查提交 {commit_sha} 的拉取请求审查时发生未知错误: {e}")
        return False

async def process_single_commit(session, token, org_name, repo_name, year, commit_data):
    """
    处理单个提交，检查其审查状态和提交信息规范性。
    """
    commit_sha = commit_data["sha"]
    commit_message = commit_data["message"]

    is_pr_merged_and_reviewed = await check_pull_request_review(
        session, token, org_name, repo_name, commit_sha
    )
    is_conventional_commit = validate_conventional_commit(commit_message)

    commit_data["is_pr_merged_and_reviewed"] = is_pr_merged_and_reviewed
    commit_data["is_conventional_commit"] = is_conventional_commit
    
    # 添加 repo_name 和 year 到返回数据，以便在 main 函数中重新组织
    commit_data["repo_name"] = repo_name
    commit_data["year"] = year
    return commit_data

async def async_run_git_command(repo_path, *command):
    """异步执行 git 命令。"""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=repo_path, # 设置工作目录
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            if stderr:
                err_msg = stderr.decode().strip()
                logger.error(f"执行 git 命令 {' '.join(command)} 失败: {err_msg}")
            else:
                logger.error(f"执行 git 命令 {' '.join(command)} 失败，返回码: {process.returncode}")
            return False
        return True
    except asyncio.CancelledError:
        logger.info(f"执行 git 命令 {' '.join(command)} 的任务被取消。")
        return False
    except Exception as e:
        logger.error(f"执行 git 命令 {' '.join(command)} 时发生异常：{e}")
        return False

async def async_get_branches(repo_path):
    """异步获取仓库的所有分支。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "branch", "-a", # 获取所有分支，包括远程分支
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            if stderr:
                err_msg = stderr.decode().strip()
                logger.error(f"执行 git branch -a 失败: {err_msg}")
            else:
                logger.error(f"执行 git branch -a 失败，返回码: {process.returncode}")
            return None
        branches = []
        for line in stdout.decode().splitlines():
            branch = line.strip()
            # 过滤掉 HEAD 分支和远程分支的头部信息
            branch = re.sub(r"^\*\s*", "", branch) # 去除星号和空格
            branch = re.sub(r"^remotes\/origin\/", "", branch) # 去除 remotes/origin/
            if branch and not branch.startswith("HEAD"): # 确保不是空字符串且不是 HEAD
                branches.append(branch)
        return branches
    except asyncio.CancelledError:
        logger.info(f"获取分支的任务被取消。")
        return None
    except Exception as e:
        logger.error(f"获取分支时发生异常：{e}")
        return None

async def async_clone_repo(repo_url, repo_path):
    # 使用信号量进行并发控制
    async with semaphore:
        if os.path.exists(repo_path) and os.path.isdir(os.path.join(repo_path, ".git")):
            logger.info(f"仓库 {repo_path} 已存在，执行 fetch 和 checkout。")
            if not await async_run_git_command(repo_path, "git", "fetch"):
                return False

            branches = await async_get_branches(repo_path)
            if branches:
                if "main" in branches:
                    branch_to_checkout = "main"
                elif "master" in branches:
                    branch_to_checkout = "master"
                else:
                    branch_to_checkout = branches[0] if branches else None

                if branch_to_checkout:
                    if await async_run_git_command(repo_path, "git", "checkout", branch_to_checkout):
                        logger.info(f"成功 checkout 分支：{branch_to_checkout}")
                        return True
                    else:
                        logger.error(f"checkout 分支 {branch_to_checkout} 失败。")
                        return False
                else:
                    logger.error("没有找到任何分支可以 checkout。")
                    return False
            else:
                logger.error("无法获取分支信息。")
                return False

        else:
            logger.info(f"仓库 {repo_path} 不存在，执行 clone。")
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

async def check_test_files_or_dirs(repo_path):
    """
    检查仓库目录中是否存在常见的测试文件或测试目录。
    """
    test_dirs = ["tests", "test"]
    test_file_patterns = [
        re.compile(r"^test_.*\.py$"),  # Python
        re.compile(r".*\.test\.js$"),  # JavaScript
        re.compile(r".*\.spec\.ts$"),  # TypeScript
        re.compile(r".*\.test\.jsx$"), # React JSX
        re.compile(r".*\.spec\.tsx$"), # React TSX
        re.compile(r".*_test\.go$"),   # Go
        re.compile(r".*\.rs$"),        # Rust (often in src/tests or separate test files)
        re.compile(r".*\.java$"),      # Java (e.g., JUnit tests)
        re.compile(r".*\.kt$"),        # Kotlin (e.g., JUnit tests)
        re.compile(r".*\.php$"),       # PHP (e.g., PHPUnit tests)
        re.compile(r".*\.rb$"),        # Ruby (e.g., RSpec, Minitest)
        re.compile(r".*\.cs$"),        # C# (e.g., NUnit, XUnit)
        re.compile(r".*\.cpp$"),       # C++ (e.g., Google Test)
        re.compile(r".*\.c$"),         # C (e.g., Unity)
    ]

    for root, dirs, files in os.walk(repo_path):
        # 检查测试目录
        for td in test_dirs:
            if td in dirs:
                logger.info(f"在 {repo_path} 中找到测试目录: {os.path.join(root, td)}")
                return True
        
        # 检查测试文件
        for f in files:
            for pattern in test_file_patterns:
                if pattern.match(f):
                    logger.info(f"在 {repo_path} 中找到测试文件: {os.path.join(root, f)}")
                    return True
    return False

async def process_repo(session, token, org_name, my_username, repo, all_repo_stats, exclude_repos, end_year):
    """处理单个仓库的统计信息。"""
    repo_key = f"{org_name}/{repo}" # 生成 repo_key

    if repo_key in exclude_repos:
        logger.info(f"仓库 {repo_key} 在排除列表中，跳过。") # 使用 repo_key
        return

    repo_path = None  # 在 try 块外部初始化 repo_path

    try:
        creation_year = await get_repo_creation_year(session, token, org_name, repo)
        if not creation_year:
            return

        encoded_token = urllib.parse.quote(token, safe="")
        repo_url = f"https://{my_username}:{encoded_token}@github.com/{repo_key}.git"
        repo_path = f"{repo_key}" # 在克隆之前赋值

        try:
            clone_success = await async_clone_repo(repo_url, repo_path) # 异步克隆
            if not clone_success: # 克隆失败直接返回
                return

            # 调用 check_test_files_or_dirs 函数并存储返回值
            has_test_files_or_dirs = await check_test_files_or_dirs(repo_path)
            
            # 记录日志
            logger.info(f"仓库 {repo_key} 测试文件/目录存在情况: {has_test_files_or_dirs}")

        except Exception as e:
            logger.error(f"克隆仓库 {repo_url} 时发生异常：{e}")
            return

        # 确保 all_repo_stats[repo_key] 字典存在
        if repo_key not in all_repo_stats:
            all_repo_stats[repo_key] = {}
        
        # 添加 has_test_files_or_dirs 字段到统计结果中
        all_repo_stats[repo_key]['has_test_files_or_dirs'] = has_test_files_or_dirs

        for year in range(creation_year, end_year + 1):
            latest_commit_sha = await get_latest_commit_sha(session, token, org_name, repo, year)
            if not latest_commit_sha:
                logger.warning(f"无法获取仓库 {repo_key} {year} 年的最新 commit SHA。")
                continue

            if 'yearly_stats' not in all_repo_stats[repo_key]:
                all_repo_stats[repo_key]['yearly_stats'] = {} # 初始化 yearly_stats

            # 检查是否需要更新
            current_year_stats = all_repo_stats[repo_key]['yearly_stats'].get(str(year), {})
            if current_year_stats.get('latest_commit_sha') == latest_commit_sha:
                logger.info(f"仓库 {repo_key} {year} 年没有更新，跳过。")
                continue

            commits_count = await get_commits_count_local(repo_path, year)
            lines_of_code = await get_lines_of_code_local(repo_path)
            contributor_commits = await get_contributor_commits_local(repo_path, year) # 获取贡献者提交

            # 新增：获取所有提交的详细信息（SHA, 作者, 消息）
            all_commits_raw_for_year = await get_all_commits_details_local(repo_path, year)

            if commits_count is not None and lines_of_code is not None and contributor_commits is not None:
                all_repo_stats[repo_key]['yearly_stats'][str(year)] = {
                    "latest_commit_sha": latest_commit_sha,
                    "lines_of_code": lines_of_code,
                    "commits_count": commits_count,
                    "contributors": contributor_commits, # 存储贡献者信息
                    "all_commits_raw": all_commits_raw_for_year if all_commits_raw_for_year else [] # 存储原始提交详情
                }
                logger.info(f"成功获取仓库 {repo_key} {year} 年的统计信息，包含 {commits_count} 个提交。")
            else:
                logger.warning(f"无法获取仓库 {repo_key} 的提交数、代码行数或贡献者信息。")

    except Exception as e:
        logger.error(f"处理仓库 {repo_key} 时发生异常：{e}")
        return
    finally:
        pass

async def main():
    parser = argparse.ArgumentParser(description="统计 GitHub 组织下所有仓库的信息。")
    parser.add_argument("-t", "--token", required=True, help="GitHub Personal Access Token。")
    parser.add_argument("-o", "--org", required=True, help="需要统计的组织名。")
    parser.add_argument("-y", "--year", type=int, help="要统计的年份 (可选)。")
    parser.add_argument("-O", "--output", help="输出 JSON 文件名 (可选)。")
    parser.add_argument("-E", "--exclude", nargs='*', default=[], help="需要排除的仓库列表，用空格分隔。")

    args = parser.parse_args()
    github_token = args.token
    org_name = args.org
    target_year = args.year
    output_filename = args.output if args.output else DATA_FILENAME
    exclude_repos = set(args.exclude) # 将排除列表转换为集合以便快速查找

    all_repo_stats = {}

    # 尝试从现有文件加载数据
    if os.path.exists(output_filename):
        try:
            with open(output_filename, 'r', encoding='utf-8') as f:
                all_repo_stats = json.load(f)
            logger.info(f"成功从 {output_filename} 加载现有数据。")
        except json.JSONDecodeError:
            logger.warning(f"无法解析 {output_filename}，将创建新文件。")
            all_repo_stats = {}
        except Exception as e:
            logger.error(f"加载现有数据时发生错误: {e}")
            all_repo_stats = {}

    async with aiohttp.ClientSession() as session:
        my_username = await get_my_username(session, github_token)
        if not my_username:
            logger.error("无法获取 GitHub 用户名，请检查 token 是否有效。")
            return

        repos = await get_org_repos(session, github_token, org_name)
        if not repos:
            logger.warning(f"组织 {org_name} 下没有找到任何仓库。")
            return

        logger.info(f"开始处理 {len(repos)} 个仓库...")

        tasks = []
        current_year = datetime.now(timezone.utc).year
        end_year = target_year if target_year else current_year

        for repo in repos:
            tasks.append(process_repo(
                session, github_token, org_name, my_username, repo, all_repo_stats, exclude_repos, end_year
            ))

        # 使用 tqdm.asyncio.tqdm 显示进度条
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="处理仓库"):
            await f

    # 将结果保存到 JSON 文件
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(all_repo_stats, f, ensure_ascii=False, indent=4)
        logger.info(f"所有仓库统计信息已保存到 {output_filename}")
    except Exception as e:
        logger.error(f"保存数据到文件失败：{e}")

def signal_handler(sig, frame):
    logger.info("接收到中断信号，正在退出...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    asyncio.run(main())
