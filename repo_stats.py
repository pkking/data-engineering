import asyncio
import aiohttp
import pygal
import csv
from datetime import datetime
from operator import itemgetter

async def get_org_repos(session, token, org):
    headers = {'Authorization': f'token {token}'}
    repos = []
    page = 1
    while True:
        async with session.get(f'https://api.github.com/orgs/{org}/repos?page={page}&per_page=100', headers=headers) as response:
            data = await response.json()
            if not data:
                break
            repos.extend(data)
            page += 1
    return repos

async def get_repo_stats(session, token, org, repo_name):
    headers = {'Authorization': f'token {token}'}
    current_year = datetime.now().year
    
    async with session.get(f'https://api.github.com/repos/{org}/{repo_name}/languages', headers=headers) as response:
        langs = await response.json()
        code_size = sum(langs.values())
    
    async with session.get(
        f'https://api.github.com/repos/{org}/{repo_name}/commits?since={current_year}-01-01T00:00:00Z',
        headers=headers
    ) as response:
        commits = await response.json()
        commits_count = len(commits)
    
    return code_size, commits_count

def create_charts(data, org_name, output_csv):
    # 导出所有数据到CSV
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Repository', 'Code Size', f'Commits in {datetime.now().year}'])
        for repo, (size, commits) in data.items():
            writer.writerow([repo, size, commits])
    
    # 按代码量排序获取TOP20
    sorted_by_size = dict(sorted(data.items(), key=lambda x: x[1][0], reverse=True)[:20])
    # 按提交数排序获取TOP20
    sorted_by_commits = dict(sorted(data.items(), key=lambda x: x[1][1], reverse=True)[:20])
    
    # 代码量图表
    code_pie = pygal.Pie(
        title=f'Top 20 Repositories by Code Size - {org_name}',
        tooltip_border_radius=10,
        inner_radius=.4,
        style=pygal.style.LightColorizedStyle
    )
    for repo, (size, _) in sorted_by_size.items():
        code_pie.add(f"{repo} ({size:,})", size)
    code_pie.render_to_file('code_size.svg')
    
    # 提交数图表
    commits_pie = pygal.Pie(
        title=f'Top 20 Repositories by Commits {datetime.now().year} - {org_name}',
        tooltip_border_radius=10,
        inner_radius=.4,
        style=pygal.style.LightColorizedStyle
    )
    for repo, (_, commits) in sorted_by_commits.items():
        commits_pie.add(f"{repo} ({commits})", commits)
    commits_pie.render_to_file('commits.svg')

async def process_repos(token, org):
    async with aiohttp.ClientSession() as session:
        repos = await get_org_repos(session, token, org)
        tasks = []
        data = {}
        
        for repo in repos:
            task = asyncio.create_task(
                get_repo_stats(session, token, org, repo['name'])
            )
            tasks.append((repo['name'], task))
        
        for repo_name, task in tasks:
            try:
                code_size, commits = await task
                data[repo_name] = (code_size, commits)
                print(f"Processed {repo_name}")
            except Exception as e:
                print(f"Error processing {repo_name}: {e}")
        
        return data

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', '-t', required=True)
    parser.add_argument('--org', '-o', required=True)
    parser.add_argument('--output-csv', default='github_analytics.csv')
    args = parser.parse_args()
    
    data = await process_repos(args.token, args.org)
    create_charts(data, args.org, args.output_csv)
    print("生成完成：")
    print("- code_size.svg (Top 20)")
    print("- commits.svg (Top 20)")
    print(f"- {args.output_csv} (All data)")

if __name__ == "__main__":
    asyncio.run(main())
