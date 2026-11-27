# 提交一个 Stodex 插件

## 从 Stodex 会话开始

1. 在会话中描述希望复用的工作。例如「创建一个发布说明插件，提供一个根据我给出的变更列表生成发布说明的斜杠命令，加入我的个人插件」。Stodex 使用 `publish_plugin` 保存技能、命令和子智能体。
2. 打开「插件广场 → 个人」，查看插件详情，安装后在一个会话里实际调用。检查输出，再尝试停用、重新启用和卸载。
3. 打开「投稿到 Stodex 市场」，检查将要公开的名称、描述和每一条资源正文。把可公开的清单复制到 GitHub 编辑器的 `community/<插件 ID>/plugin.json`，通过分支提交 Pull Request。作者决定何时公开。也可在自己的 fork 中创建同一路径。
4. 在 PR 中写明用途、必要账户或本地软件、发布许可，以及实际使用的 Stodex 版本、操作步骤和结果。维护者验收并合并后，市场自动更新。

## 原生清单

目录名与 `name` 一致，使用小写英文或数字，可用短横线、下划线分词。中文名称放在 `displayName`。资源的 `kind` 可取 `skill`、`prompt`、`agent`。以下是一个清单示例。

```json
{
  "format": "stodex-plugin-v1",
  "name": "release-notes",
  "displayName": "发布说明",
  "version": "1.0.0",
  "description": "把一组变更整理成面向用户的发布说明。",
  "resources": [
    {
      "kind": "prompt",
      "name": "release-notes",
      "description": "根据输入的变更编写发布说明。",
      "content": "按新增、改进、修复整理以下变更，省略空分类，并保留原始版本号。\n\n$ARGUMENTS"
    }
  ]
}
```

每个插件可包含 1 至 100 条资源。可以随清单附上 README 和 LICENSE。更新已有插件时提高版本号。索引由 `python scripts/catalog.py build` 生成，网页投稿只需提交自己的插件目录。

## 审核和发布

一个 PR 提交一个插件。自动检查会读取清单，核对目录、标识、重复项及允许的字段。维护者复核公开权限和客户端验收记录。合并到主分支后，发布工作流从清单生成公开索引。
