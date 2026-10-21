# Kindle 3 Kindlet Launcher

从 Kindle 原生书库直接启动 KOReader，退出后返回主页面，无需先打开 KUAL 或手动按 Back。

基于 [DenSwitch/kindle4-kindlet-launcher](https://github.com/DenSwitch/kindle4-kindlet-launcher)，针对 Kindle Keyboard / Kindle 3 的 Kindlet 生命周期交接进行了修复。

## 下载与安装

**[下载正式版 KOReader.azw2](https://github.com/W-874/kindle3-kindlet-launcher/releases/latest/download/KOReader.azw2)** · [所有 Release](https://github.com/W-874/kindle3-kindlet-launcher/releases)

1. Kindle 已有可用的越狱、MKK / 开发证书环境。
2. KOReader 已安装在 `/mnt/us/koreader/koreader.sh`。本项目只提供启动器，不包含 KOReader。
3. 将下载的 `KOReader.azw2` 复制到 Kindle 的 `documents/`，替换之前的测试启动器；避免留下多个同名书库条目。
4. 安全弹出 USB，在原生书库打开 **KOReader**；在 KOReader 中正常退出即可返回主页面。

保留原 KUAL 作为回退。无需替换 KUAL、修改 KOReader、系统服务或固件。

### 已验证范围

用户已实机确认：**Kindle 3 Wi-Fi（K3W）、固件 3.4.3、KOReader v2026.07.1** 可以自动启动并正常返回主页面。

其他 KDK 1.0 设备及特定长时间测试矩阵未在本 fork 中确认，不将此范围外兼容性写成已验证。

### 校验下载

Release 同时提供 `SHA256SUMS`。将它与 `KOReader.azw2` 放在同一目录后运行：

```fish
sha256sum --check SHA256SUMS
```

首个修复正式版：[v1.0.1](https://github.com/W-874/kindle3-kindlet-launcher/releases/tag/v1.0.1)。

## 修复内容

原独立启动器在 Kindlet 仍处于活动状态时直接启动 KOReader。K3 恢复 `cvm` 后可能触发 `KindletEventQueueMonitor` 并重启 Framework；仅添加 `--kual` 不能解决生命周期问题。

当前实现：

- 保存待启动命令，通过 KUAL 的原有正常退出机制离开 Kindlet；命令仍由模板的 `onStop()` 派发。
- 等待实际显示及键盘焦点事件后再请求自动退出，不靠新增固定延时或轮询，避免必须手动按 Back。
- 停止时取消尚未执行的自动退出任务，拒绝不支持、已修改或损坏的字节码模板。

本项目不关闭监视器，不重启 Framework 来掩盖问题，也不改动 KOReader 的框架暂停/恢复流程。

## 本地构建

以下终端示例使用 **fish**。普通构建只需要 Python 3 和签名依赖，无需 Java 编译器：

```fish
git clone git@github.com:W-874/kindle3-kindlet-launcher.git
cd kindle3-kindlet-launcher
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python make_launcher.py --config config.k3.json
```

输出：`dist/KOReader.azw2`。构建配置保留 `/mnt/us/koreader/koreader.sh --kual`，并记录启动/退出状态到 `/mnt/us/koreader-k3-launcher.log`。

### 从源码重新编译正式包

需要 JDK 17（`java`、`jarsigner`；回归测试还需 `javac`）：

```fish
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_release.py
```

正式构建会：

1. 下载固定版本及 SHA-256 校验的 ECJ 编译器与 KDK 编译接口。
2. 从 `src/AutoExit.java` 重新编译 Java 1.4 / class major 48 的助手；必须与实机验证过的 `template/AutoExit.class` 逐字节一致，否则停止。
3. 重新生成签名 `.azw2`，检查 ZIP、manifest、class 版本及 JAR 签名，输出 `dist/KOReader.azw2` 和 `dist/SHA256SUMS`。

GitHub Actions 在推送 `v*` 标签时执行上述全新构建并创建 Release；手动触发仅生成构建产物，不发布版本。ZIP 时间戳会使不同构建的整体文件哈希变化，以每次 Release 的 `SHA256SUMS` 为准。

社区开发证书的自签名、主机 CA 不信任及无时间戳警告不等于签名损坏；设备仍须具备相应开发证书环境。

### 自定义启动器

保留上游 CLI 基本用法：

```fish
.venv/bin/python make_launcher.py \
    --name 'My App' \
    --cmd '/mnt/us/my-app/start.sh' \
    --dir /mnt/us/my-app \
    --output dist/MyApp.azw2
.venv/bin/python make_launcher.py --help
```

可用选项包括 `--title`、`--timeout-msg`、`--exit-msg`、`--cover`、`--vendor` 及 `--config`，配置示例见 `config.example.json`。

可选 SSH 上传需另行安装 `paramiko`，再使用 `--upload` / `--ssh-pass`；USB 复制不需要 SSH 依赖。

## 源码与产物边界

- `make_launcher.py`：模板 class 修改及签名构建。
- `src/AutoExit.java`、`template/AutoExit.class`：同一焦点驱动退出助手的源码与必要预编译运行资源；后者支持普通 Python 构建，不是临时产物。
- `template/base.azw2`、`keys/`：继承自上游的必要模板及社区开发签名证书，不是设备 SSH 私钥。
- `tests/`：模板拒绝与真实助手字节码的焦点/异步/取消行为回归。主机 AWT 替身不等于设备事件路由验证。
- `.github/workflows/release.yml`、`scripts/build_release.py`：干净环境重编译、验包及发布。

`docs/` 调查资料、设备日志、虚拟环境、缓存、下载工具链、中间构建及生成的 `.azw2` 不提交。正式安装包从 Release 下载，不在源码根目录保存过时的预编译包。

## 故障与回退

若启动失败，保留对应时间的 `/mnt/us/koreader-k3-launcher.log`、`koreader/crash.log` 和 `;dm` 系统日志，避免把含设备信息的原始日志直接提交到公共仓库。

回退只需删除新启动器，继续使用原 KUAL；可选删除启动器日志。不需要恢复系统服务或 KOReader 文件。

## 致谢

- [DenSwitch/kindle4-kindlet-launcher](https://github.com/DenSwitch/kindle4-kindlet-launcher)：原生成器、模板和签名构建机制。
- [KUAL](https://github.com/coplate/KUAL_Booklet)：Kindlet 生命周期及退出机制。
- [KOReader](https://github.com/koreader/koreader)：阅读器及 Kindle 启动脚本。

保留上游资产及原始 Git 历史；本 fork 的工作集中在 K3 生命周期修复、回归和可追溯发布。
