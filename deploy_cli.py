import argparse
from backend.deploy_utils import generate_static_site, push_to_github
import shutil

parser = argparse.ArgumentParser(description="MarkLume 一键部署到 GitHub Pages")
parser.add_argument("--title", required=True, help="站点标题")
parser.add_argument("--link", required=True, help="站点链接")
parser.add_argument("--token", required=True, help="GitHub Personal Access Token")
parser.add_argument("--repo", required=True, help="GitHub 仓库 (username/repo)")

args = parser.parse_args()
site_dir = generate_static_site(args.title, args.link)
push_to_github(site_dir, args.token, args.repo)
shutil.rmtree(site_dir)
print("部署完成！")