# MarkLume - 极简文件型博客系统

![MarkLume Logo](https://via.placeholder.com/150/4a86e8/ffffff?text=ML)  
*轻如羽毛，快如闪电的个人 Markdown 博客*

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

MarkLume 是一个为写作者设计的极简博客系统，所有文章以 Markdown 文件形式存储在本地，无需数据库，开箱即用。  
使用 FastAPI 驱动后端，配合 Jinja2 模板引擎，提供流畅的管理体验。

---

## ✨ 特性

- **纯 Markdown 存储** – 每一篇文章都是一个 `.md` 文件，可直接用任何编辑器打开  
- **零数据库** – 文件系统即数据库，迁移和备份简单到复制目录  
- **按需加载 & 智能缓存** – 文章内容仅在阅读时读入内存，空闲后自动释放  
- **管理员密钥管理** – 首次启动自动生成密钥，支持在面板中安全刷新  
- **站点配置** – 通过 `config.ini` 自定义站点名称和链接  
- **响应式前端** – 简洁清晰的阅读与写作界面  
- **轻量部署** – 单条命令即可启动，适合 VPS、树莓派甚至本地开发

---

## 🚀 快速开始

### 环境要求
- 推荐 Python 3.13 或更高版本

### 安装与运行

```bash
# 1. 克隆仓库
git clone https://github.com/athenavi/marklume.git
cd marklume

# 2. 创建并激活虚拟环境
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务
uvicorn backend.main:app --reload
```

访问 http://localhost:8000 即可看到你的博客。

> 启动时会自动创建 `archive/` 目录（如果不存在），并扫描其中已有的 `.md` 文件作为文章。

### Docker 部署

```bash
docker build -t marklume .
docker run -d -p 8000:8000 -v $(pwd)/archive:/app/archive marklume
```

---

## ⚙️ 配置

### 管理员密钥

MarkLume 通过浏览器 Cookie 验证管理员身份，无需记住密码。  
首次启动时，程序会在项目根目录生成 `admin_key.txt`，其中包含唯一的密钥。

- 登录：访问 `/admin/key`，输入密钥后点击登录（Cookie 有效期长达 10 年）
- 刷新密钥：登录后在管理页面可生成新密钥，旧密钥立即失效
- 手动重置：删除 `admin_key.txt` 并重启服务，系统会自动生成新密钥

### 站点信息

创建 `config.ini` 文件（放在项目根目录，与 `backend/` 同级）来自定义站点标题和链接：

```ini
[site]
site_name = 我的博客
site_link = https://example.com
```

重启服务后生效。若不提供该文件，将使用默认值 `Marklume`。

---

## 📂 项目结构

```
marklume/
├── archive/                 # 文章存档目录（.md 文件）
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── database.py          # 文章存取与缓存逻辑
│   ├── models.py            # Article 数据模型
│   └── ...                  # 其他模块
├── frontend/
│   ├── static/              # 静态资源（CSS, JS）
│   └── templates/           # Jinja2 模板
├── admin_key.txt            # 管理员密钥（自动生成）
├── config.ini               # 可选站点配置
├── requirements.txt
└── README.md
```

---

## 📝 使用指南

### 前台读者
- 首页展示所有文章列表
- 点击标题阅读全文

### 管理员操作
1. 通过 `/admin/key` 登录（使用 `admin_key.txt` 中的密钥）
2. 创建文章：点击导航栏的“新建文章”
3. 编辑 / 删除：进入文章页后可见编辑和删除按钮
4. 刷新密钥：在管理页面生成新密钥，增强安全性

### 文章文件管理
每篇文章对应 `archive/` 目录下的一个 Markdown 文件，文件名基于文章标题自动生成。  
你可以直接用喜欢的编辑器修改文件，重启服务后改动会自动同步（内容按需加载时读取）。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！  
如果你想添加新功能或改进文档，请先开 issue 讨论你的想法。

1. Fork 本仓库
2. 创建你的功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交修改 (`git commit -m '添加某个功能'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 发起 Pull Request

---

## 📜 许可证

基于 MIT 许可证开源，详见 [LICENSE](LICENSE) 文件。  
你可以自由使用、修改和分发本项目，但请保留原作者署名。

---

## 🙏 致谢

MarkLume 受到以下项目的启发：

- [Docsify](https://docsify.js.org/) – 动态文档生成  
- [htmx](https://htmx.org/) – 轻量前端交互思想  
- [Jekyll](https://jekyllrb.com/) – 静态网站生成先驱  

---

**MarkLume** © 2025 Athenavi