import asyncio
import aiohttp
import json
from datetime import datetime
import os

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
    stats = {
        'name': repo_name,
        'code_size': {},
        'commits_by_month': {}
    }
    
    # Get code size
    async with session.get(f'https://api.github.com/repos/{org}/{repo_name}/languages', headers=headers) as response:
        langs = await response.json()
        stats['code_size'] = langs
    
    # Get commits by month for the past year
    current_year = datetime.now().year
    for year in [current_year - 1, current_year]:
        for month in range(1, 13):
            # Skip future months
            if year == current_year and month > datetime.now().month:
                break
                
            start_date = f"{year}-{month:02d}-01T00:00:00Z"
            if month == 12:
                end_date = f"{year+1}-01-01T00:00:00Z"
            else:
                end_date = f"{year}-{month+1:02d}-01T00:00:00Z"
            
            async with session.get(
                f'https://api.github.com/repos/{org}/{repo_name}/commits'
                f'?since={start_date}&until={end_date}',
                headers=headers
            ) as response:
                commits = await response.json()
                key = f"{year}-{month:02d}"
                stats['commits_by_month'][key] = len(commits)
    
    return stats

async def collect_data(token, org):
    async with aiohttp.ClientSession() as session:
        repos = await get_org_repos(session, token, org)
        tasks = []
        
        for repo in repos:
            task = asyncio.create_task(
                get_repo_stats(session, token, org, repo['name'])
            )
            tasks.append(task)
        
        print(f"Collecting data for {len(tasks)} repositories...")
        results = await asyncio.gather(*tasks)
        
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Save data to JSON file
        output_file = f'data/github_stats.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"Data collected and saved to {output_file}")

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', '-t', required=True)
    parser.add_argument('--org', '-o', required=True)
    args = parser.parse_args()
    
    await collect_data(args.token, args.org)

if __name__ == "__main__":
    asyncio.run(main())
