# MarkLume

**极简 · 快速 · 一键部署的个人 Markdown 博客 | GitHub.io 站点生成器**

![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> 轻如羽毛，快如闪电。

> 所有文章以 Markdown 文件存储，零数据库依赖，只需一个 Python 环境即可运行。

> 提供本地动态写作界面，更支持**一键生成静态站点并推送至 GitHub Pages**，几分钟拥有个人博客。

---

## ✨ 为什么选择 MarkLume？

- **纯文本，永久可读** – 每篇文章就是一个 `.md` 文件，用任何编辑器都能打开。
- **零数据库，迁移简单** – 备份只需拷贝 `archive` 目录。
- **本地动态管理** – 基于 FastAPI 的极简后台，支持在线编写、编辑、删除文章。
- **一键 GitHub Pages 部署** – 无需手动配置 Actions，填写 Token 即可自动推送至 `你的用户名.github.io` 仓库。
- **轻量无侵入** – 单个命令启动，无需 Docker，非常适合个人 VPS 或本地使用。

---

## 📦 快速开始

### 环境要求
- Python 3.13 或更高版本
- Git（用于部署）

### 安装与启动

```bash
# 1. 克隆仓库
git clone https://github.com/athenavi/marklume.git
cd marklume

# 2. 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动本地服务
uvicorn backend.main:app --reload
```

访问 `http://localhost:8000` 即可看到你的博客。  
第一次启动会自动创建 `archive/` 目录，并在项目根目录生成 `admin_key.txt`（管理员密钥）。

---

## ⚙️ 配置

### 1. 管理员密钥
- 启动后自动生成 `admin_key.txt`，其中包含一串随机字符串。
- 访问 `/admin/key`，输入该密钥即可登录管理后台（Cookie 有效期 10 年）。
- 如需重置，删除 `admin_key.txt` 后重启服务即可。

### 2. 站点信息
在项目根目录创建 `config.ini`（可选），自定义站点标题和链接：
```ini
[site]
site_name = 我的技术笔记
site_link = https://myblog.github.io
```

### 3. GitHub Token（部署专用）
部署功能需要 GitHub Personal Access Token。获取方式：
- 登录 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
- 点击 **Generate new token (classic)**，勾选 `repo` 全部权限，生成后复制保存。

---

## 📝 本地使用指南

### 前台阅读
- 首页展示文章列表，点击标题阅读全文。

### 后台管理
- 访问 `/admin/key` 输入管理员密钥登录。
- 登录后，导航栏出现“新建文章”按钮，文章页出现“编辑”和“删除”按钮。
- 支持 Markdown 语法实时预览（前端由模板渲染，可自行扩展编辑器）。
- **上传 Markdown 文件**：在新建文章页面，可直接上传本地 `.md` 文件，系统自动以文件名作为标题创建文章。

### 文章存储
所有文章保存在 `archive/` 目录下，每篇文章一个 `.md` 文件：
```
archive/
  ├── getting-started.md
  ├── advanced-features.md
  └── migration-guide.md
```
文件名即为文章标题（自动处理特殊字符）。

---

## 🚀 一键部署到 GitHub Pages
## 🌐 GitHub.io 站点生成器

> MarkLume 不仅仅是一个本地博客工具——它同时也是一个 **GitHub Pages 静态站点生成器**。通过一键部署，它会将你的 Markdown 文章转化为一个完整的、可直接访问的 `.github.io` 站点。

> 仅支持部署到 `你的用户名.github.io` 仓库（例如 `athenavi.github.io`）。部署将强制覆盖该仓库 `main` 分支的全部内容！

### 步骤
1. 确保本地已经运行了 MarkLume（`uvicorn backend.main:app`）。
2. 访问 `http://localhost:8000/deploy`。
3. 填写站点标题（将显示在博客头部）和你的 GitHub Token。
4. 点击“开始部署”，等待状态提示完成。
5. 几分钟后访问 `https://你的用户名.github.io` 即可看到你的个人博客。

**部署过程自动完成**：
- 从 Token 获取你的 GitHub 用户名。
- 生成包含所有文章和静态资源的网站。
- 创建/覆盖 `用户名.github.io` 仓库（公开）。
- 推送至 `main` 分支，GitHub Pages 自动生效。

**注意**：
- Token 仅用于本次部署，不会保存在服务器上。
- 如需更新博客，只需在本地修改/新增文章，然后再次执行部署即可。

---


### 生成的站点特性

| 特性 | 说明 |
|------|------|
| **响应式设计** | 基于 Tailwind CSS 构建，完美适配桌面端和移动端 |
| **深色/浅色主题** | 自动跟随系统偏好，也支持手动切换 |
| **文章分类** | 按 `archive/` 目录结构自动归类，支持分类浏览 |
| **搜索功能** | 首页内置文章搜索，按标题实时过滤 |
| **自定义页面** | 支持独立 HTML 页面（放置在 `pages/` 目录） |
| **Giscus 评论** | 可选集成 GitHub Discussions 评论系统 |
| **增量部署** | 智能对比文件差异，仅推送变更内容，节省部署时间 |
| **仓库 README** | 自动生成包含站点地址、部署时间和变更详情的仓库 README |

### 站点结构

部署后生成的 `.github.io` 仓库结构如下：

```
你的用户名.github.io/
├── index.html                 # 首页（文章列表 + 分类 + 搜索）
├── articles/
│   ├── 1.html                 # 文章页
│   ├── 2.html
│   └── ...
├── cate/
│   └── 技术/                  # 按分类生成的目录
│       └── 3.html
├── pages/
│   └── about.html             # 自定义页面（如有）
├── static/                    # CSS、JS 等静态资源
├── .marklume-manifest.json    # 增量部署用的文件清单
└── README.md                  # 自动生成的仓库说明
```

### 部署模式

- **自动模式**（默认）：首次部署时全量推送，后续自动检测差异并增量推送。
- **全量模式**：重新生成所有文件并强制推送，适用于大规模内容变更。
- **增量模式**：仅推送变更的文件，保持远程历史记录完整。

---

## 📂 项目结构

```
marklume/
├── archive/                 # 文章存档（.md 文件）
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── database.py          # 文章存取与缓存逻辑
│   ├── models.py            # 数据模型
│   ├── deploy_utils.py      # 静态站点生成、README 生成与 GitHub 推送
│   └── manifest.py          # 增量部署的文件变更跟踪
├── frontend/
│   ├── static/              # CSS、JS 等静态资源
│   └── templates/           # Jinja2 模板（含 Giscus 评论组件）
├── deploy_cli.py            # 命令行部署工具
├── admin_key.txt            # 管理员密钥（自动生成）
├── config.ini               # 站点与 Giscus 配置
├── requirements.txt
└── README.md
```

---

## 💻 命令行部署（可选）

除了 Web 界面，你也可以直接用命令行生成并部署：

```bash
python deploy_cli.py --title "我的博客" --token ghp_xxxxxxxxxxxx
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！  
建议先开 Issue 讨论你的想法，避免重复工作。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 发起 Pull Request

---

## 📜 许可证

基于 MIT 许可证开源。你可以自由使用、修改和分发本项目，但需保留原作者署名。

---

## 🙏 致谢

MarkLume 的设计灵感来源于以下项目：
- [Docsify](https://docsify.js.org/) – 动态文档生成
- [htmx](https://htmx.org/) – 轻量前端交互理念
- [Jekyll](https://jekyllrb.com/) – 静态网站生成先驱

---

> **MarkLume** © 2025 Athenavi  
> 用最简单的工具，写下最认真的思考。