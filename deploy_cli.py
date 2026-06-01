import argparse
from configparser import ConfigParser
from backend.deploy_utils import generate_static_site, push_to_github
import shutil

# 加载配置文件中的 giscus 默认值
config = ConfigParser()
config.read("config.ini", encoding="utf-8")

DEFAULT_GISCUS_REPO = config.get("giscus", "repo", fallback="")
DEFAULT_GISCUS_REPO_ID = config.get("giscus", "repoId", fallback="")
DEFAULT_GISCUS_CATEGORY = config.get("giscus", "category", fallback="")
DEFAULT_GISCUS_CATEGORY_ID = config.get("giscus", "categoryId", fallback="")
DEFAULT_GISCUS_MAPPING = config.get("giscus", "mapping", fallback="pathname")
DEFAULT_GISCUS_REACTIONS = config.get("giscus", "reactionsEnabled", fallback="1")
DEFAULT_GISCUS_METADATA = config.get("giscus", "emitMetadata", fallback="0")
DEFAULT_GISCUS_INPUT_POS = config.get("giscus", "inputPosition", fallback="bottom")
DEFAULT_GISCUS_THEME = config.get("giscus", "theme", fallback="preferred_color_scheme")
DEFAULT_GISCUS_LANG = config.get("giscus", "lang", fallback="zh-CN")

parser = argparse.ArgumentParser(description="MarkLume 一键部署到 GitHub Pages")
parser.add_argument("--title", required=True, help="站点标题")
parser.add_argument("--link", required=True, help="站点链接")
parser.add_argument("--token", required=True, help="GitHub Personal Access Token")
parser.add_argument("--repo", required=True, help="GitHub 仓库 (username/repo)")

# Giscus 评论功能参数
parser.add_argument("--giscus", action="store_true", help="启用 Giscus 评论功能")
parser.add_argument("--giscus-repo", default=DEFAULT_GISCUS_REPO, help="Giscus 仓库 (owner/repo)")
parser.add_argument("--giscus-repo-id", default=DEFAULT_GISCUS_REPO_ID, help="Giscus 仓库 ID")
parser.add_argument("--giscus-category", default=DEFAULT_GISCUS_CATEGORY, help="Giscus Discussion 分类名")
parser.add_argument("--giscus-category-id", default=DEFAULT_GISCUS_CATEGORY_ID, help="Giscus 分类 ID")
parser.add_argument("--giscus-mapping", default=DEFAULT_GISCUS_MAPPING, help="页面映射方式 (default: pathname)")
parser.add_argument("--giscus-theme", default=DEFAULT_GISCUS_THEME, help="Giscus 主题 (default: preferred_color_scheme)")
parser.add_argument("--giscus-lang", default=DEFAULT_GISCUS_LANG, help="Giscus 语言 (default: zh-CN)")

args = parser.parse_args()

# 构建 giscus 配置
giscus_config = None
if args.giscus:
    if not args.giscus_repo or not args.giscus_repo_id or not args.giscus_category or not args.giscus_category_id:
        parser.error("启用 --giscus 时必须提供 --giscus-repo、--giscus-repo-id、--giscus-category 和 --giscus-category-id")
    giscus_config = {
        "enabled": True,
        "repo": args.giscus_repo,
        "repoId": args.giscus_repo_id,
        "category": args.giscus_category,
        "categoryId": args.giscus_category_id,
        "mapping": args.giscus_mapping,
        "reactionsEnabled": DEFAULT_GISCUS_REACTIONS,
        "emitMetadata": DEFAULT_GISCUS_METADATA,
        "inputPosition": DEFAULT_GISCUS_INPUT_POS,
        "theme": args.giscus_theme,
        "lang": args.giscus_lang,
    }
    # 更新配置文件
    if not config.has_section("giscus"):
        config.add_section("giscus")
    config.set("giscus", "enabled", "true")
    config.set("giscus", "repo", args.giscus_repo)
    config.set("giscus", "repoId", args.giscus_repo_id)
    config.set("giscus", "category", args.giscus_category)
    config.set("giscus", "categoryId", args.giscus_category_id)
    config.set("giscus", "mapping", args.giscus_mapping)
    config.set("giscus", "reactionsEnabled", DEFAULT_GISCUS_REACTIONS)
    config.set("giscus", "emitMetadata", DEFAULT_GISCUS_METADATA)
    config.set("giscus", "inputPosition", DEFAULT_GISCUS_INPUT_POS)
    config.set("giscus", "theme", args.giscus_theme)
    config.set("giscus", "lang", args.giscus_lang)
    with open("config.ini", "w", encoding="utf-8") as f:
        config.write(f)
    print("Giscus 评论功能已启用")

site_dir = generate_static_site(args.title, args.link, giscus_config=giscus_config)
push_to_github(site_dir, args.token, args.repo)
shutil.rmtree(site_dir)
print("部署完成！")
