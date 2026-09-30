# Gitee 镜像与发行版同步

GitHub 为源仓库，镜像地址为 <https://gitee.com/tortes/maa-roco>。

`Sync Gitee` 工作流在 main / 版本标签推送、Release 发布或编辑，以及
`install` / `macOS preview` 构建成功后执行。构建完成事件确保由
`GITHUB_TOKEN` 发布的 Release 也会同步，而且等待二进制附件上传完成。
每次检查全部已发布版本；已完成的附件不会重复下载。

Gitee 仓库附件总配额为 1 GB。镜像保留按发布时间确定的最新正式版和最新
预览版附件，其余版本保留标题、说明、预发布标记，以及 GitHub 原始附件
下载链接。上传新版前自动清理旧版镜像附件以释放配额，不删除旧 Release、
标签、GitHub 原包或 Gitee 上与镜像无关的附件。

仓库的 Actions Secret `GITEE_TOKEN` 保存具有目标仓库推送、发行版和附件
写入权限的 Gitee Token。Token 不写入 Git 配置、仓库文件或同步报告。
更换 Token 时只需更新此 Secret。

同步 main 和全部版本标签时不使用强制推送，也不删除 Gitee 上额外的引用。
如果镜像端有独立提交导致分叉，工作流会失败，需先处理分叉。

## 下载大文件

Gitee 当前返回的单附件上限为 100 MB。超过 95 MB 的原始文件按字节拆为
`文件名.001`、`文件名.002` 等分卷，其他附件保留原文件名。
每个 Release 附带 `GITEE_DOWNLOAD.md` 合并步骤和 `SHA256SUMS-Gitee.txt`
校验值。合并后的原始文件与 GitHub 发布文件完全一致。

源 Release 的标题、说明和预发布标记会保留，说明末尾补充 Gitee 下载提示。
只有远端附件名称和大小全部核对通过，才写入同步完成标记。
下载时验证 GitHub 提供的 SHA-256；分卷和原始文件均另外生成 SHA-256。
源站替换同一版本的附件时会停止并报错，避免把旧安装包误认为已同步。

## 手动补同步

在 GitHub Actions 中运行 `Sync Gitee`；`tag` 留空检查全部发布版本，
填写例如 `v0.2.16` 则只补传该版本的附件，但仍执行整个仓库的旧镜像清理策略。
只有当前最新正式版或最新预览版会保留镜像附件。
运行报告保留为 Actions Artifact。

本地需要 Python、`requests`、已认证的 `gh` 和环境变量 `GITEE_TOKEN`：

```sh
python tools/sync_gitee.py --tag v0.2.16 --cache-dir /path/to/release-cache
```

本地命令同步发行版，运行前需要确保对应标签已推送到 Gitee。
失败后重跑会复用已下载文件和已上传的同名同大小附件。
如果以后扩容了 Gitee 附件配额，可以加 `--all-assets` 同步所有历史附件；
该模式不清理旧版本附件。
