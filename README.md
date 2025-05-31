# 仓库统计工具 (repo_stats.py)

`repo_stats.py` 是一个用于分析 GitHub 组织下仓库的 Python 脚本。它能够帮助您识别热点仓库、主要贡献者，并评估代码审查情况、提交信息规范性以及是否存在测试文件或目录。

## 功能特性

*   获取指定 GitHub 组织下的所有仓库列表。
*   本地克隆或更新仓库。
*   统计指定年份的提交数量和代码行数。
*   识别热点仓库（按提交总数排名前 20%）。
*   识别热点仓库的主要贡献者（提交数量最多的前 5 名）。
*   评估主要贡献者提交的代码是否经过了拉取请求审查。
*   验证主要贡献者提交信息的 Conventional Commits 规范性。
*   检查仓库中是否存在常见的测试文件或目录。
*   支持异步并发处理以提高效率。
*   将统计结果保存到 JSON 文件中，并支持增量更新。

## 安装依赖

在运行 `repo_stats.py` 之前，您需要安装以下依赖：

### 1. Python 依赖

使用 `pip` 安装所需的 Python 库：

```bash
pip install aiohttp pygit2 tqdm
```

### 2. `cloc` 工具

`cloc` (Count Lines of Code) 是一个用于统计代码行数的命令行工具。请根据您的操作系统安装 `cloc`：

*   **macOS (使用 Homebrew):**
    ```bash
    brew install cloc
    ```
*   **Linux (使用 apt):**
    ```bash
    sudo apt-get install cloc
    ```
*   **Windows:**
    ```
    winget install AlDanial.Cloc
    ```

## 使用方法

### 命令行参数

`repo_stats.py` 支持以下命令行参数：

*   `-t`, `--token` (必填): 您的 GitHub 个人访问令牌 (Personal Access Token)。需要 `repo` 范围的权限才能访问私有仓库和获取提交详情。
*   `-o`, `--org` (必填): 要分析的 GitHub 组织名称。
*   `-y`, `--year` (可选): 要统计的年份。默认为当前年份。
*   `-f`, `--file` (可选): 输出 JSON 文件的名称。默认为 `<组织名>_<年份>_stats.json`。
*   `-e`, `--exclude` (可选): 一个逗号分隔的仓库名称列表，这些仓库将被排除在统计之外。例如：`repo1,repo2`。

### 使用示例

以下是一些使用 `repo_stats.py` 的示例：

**1. 统计指定组织在当前年份的所有仓库信息：**

```bash
python repo_stats.py --token YOUR_GITHUB_TOKEN --org YOUR_ORGANIZATION_NAME
```

**2. 统计指定组织在 2023 年的所有仓库信息，并将结果保存到 `my_org_2023_data.json`：**

```bash
python repo_stats.py --token YOUR_GITHUB_TOKEN --org YOUR_ORGANIZATION_NAME --year 2023 --file my_org_2023_data.json
```

**3. 统计指定组织的所有仓库信息，并排除 `excluded-repo-1` 和 `another-excluded-repo`：**

```bash
python repo_stats.py --token YOUR_GITHUB_TOKEN --org YOUR_ORGANIZATION_NAME --exclude excluded-repo-1,another-excluded-repo
```

**4. 结合所有参数的示例：**

```bash
python repo_stats.py --token YOUR_GITHUB_TOKEN --org YOUR_ORGANIZATION_NAME --year 2024 --file my_company_2024_report.json --exclude old-project,test-repo
```

请将 `YOUR_GITHUB_TOKEN` 替换为您的实际 GitHub 个人访问令牌，将 `YOUR_ORGANIZATION_NAME` 替换为您要分析的 GitHub 组织名称。

