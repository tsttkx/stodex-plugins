# Stodex 插件市场

这是 Stodex 客户端的官方 GitHub 市场源。官方插件放在 `plugins/`，社区投稿放在 `community/`。客户端从同一份公开索引发现两者。

在 Stodex 中打开「插件广场」，选择插件查看它提供的技能、斜杠命令或子智能体。安装后可以在插件管理中停用、启用和卸载。

## 从会话投稿

可以直接告诉 Stodex 想做什么插件。会话工具 `publish_plugin` 会把作品保存到个人插件列表。作者在详情中检查可公开的清单，再通过 GitHub 提交。审核合并后，其他人刷新市场就能发现它。[投稿步骤与清单示例](CONTRIBUTING.md)

## 市场清单

- [marketplace.json](marketplace.json) 是自动生成的 Stodex 原生插件索引。
- [external.json](external.json) 记录外部市场中已在 Stodex 验收的具体版本。每条记录包含上游仓库、提交、使用条件和验收结果。上游发布新版后，需要重新验收才能更新记录。

校验使用 Python 3.10 或更新版本。在仓库根目录运行 `python scripts/catalog.py check`。
