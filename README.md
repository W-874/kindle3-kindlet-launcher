# Kindle 3 / Kindle 4 Kindlet Launcher

从 Kindle 原生书库直接启动 KOReader，正常退出后返回主页面，无需先打开 KUAL 或手动按 Back。

已在 Kindle 3 和 Kindle 4 上测试通过，也可为其他脚本或应用生成自定义启动入口。本项目只提供启动器，KOReader 需要单独安装。

## 下载与安装

**[下载 KOReader.azw2](https://github.com/W-874/kindle3-kindlet-launcher/releases/latest/download/KOReader.azw2)** · [所有版本](https://github.com/W-874/kindle3-kindlet-launcher/releases)

安装前，请确认 Kindle 已越狱，并已配置 MKK / 开发证书环境，KOReader 已安装在 `/mnt/us/koreader/koreader.sh`。

1. 将 `KOReader.azw2` 复制到 Kindle 的 `documents/` 目录。更新时替换旧文件，避免出现多个同名条目。
2. 安全弹出 USB，在原生书库打开 **KOReader**。
3. 在 KOReader 中正常退出，即可返回 Kindle 主页面。

建议保留 KUAL 作为备用入口。卸载时删除 `documents/KOReader.azw2` 即可。

### 校验下载

将 Release 中的 `SHA256SUMS` 与 `KOReader.azw2` 放在同一目录，运行：

```fish
sha256sum --check SHA256SUMS
```

## 本地构建

需要 Python 3。以下命令在电脑上运行：

```fish
git clone https://github.com/W-874/kindle3-kindlet-launcher.git
cd kindle3-kindlet-launcher
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python make_launcher.py --config config.k3.json
```

输出为 `dist/KOReader.azw2`。`config.k3.json` 同时适用于 Kindle 3 和 Kindle 4。

### 自定义启动器

```fish
.venv/bin/python make_launcher.py \
    --name 'My App' \
    --cmd '/mnt/us/my-app/start.sh' \
    --dir /mnt/us/my-app \
    --output dist/MyApp.azw2
```

支持自定义名称、命令、工作目录、封面和提示文字。配置示例见 [config.example.json](config.example.json)，完整选项可通过 `--help` 查看。命令行参数优先于配置文件。

### 测试与完整构建

如需重新编译 Java 助手并校验安装包，另外安装 JDK 17，然后运行：

```fish
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_release.py
```

构建脚本会下载所需编译依赖，生成 `dist/KOReader.azw2` 和 `dist/SHA256SUMS`。

## 常见问题

**打开启动器后没有进入 KOReader？**

检查 KOReader 安装路径及 MKK / 开发证书环境，并尝试通过 KUAL 启动 KOReader。使用默认配置时，启动日志位于 `/mnt/us/koreader-k3-launcher.log`，Kindle 4 也使用此路径。

反馈问题时，请提供设备型号、固件、KOReader 版本、启动器版本和相关日志；分享日志前请去除设备个人信息。

## 致谢

- [DenSwitch/kindle4-kindlet-launcher](https://github.com/DenSwitch/kindle4-kindlet-launcher)
- [KUAL](https://github.com/coplate/KUAL_Booklet)
- [KOReader](https://github.com/koreader/koreader)
