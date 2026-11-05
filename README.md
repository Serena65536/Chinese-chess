# 一起来下棋

电脑端中国象棋联机对弈程序。**不含人机对战**；两个人各装一份，连同一个服务器就能下。

- 客户端：Python 3.11 + PySide6（Qt6）
- 服务端：Python + aiohttp（可跑在自己电脑，也可丢云主机）
- 棋规内核：一份纯 Python 代码，客户端和服务端共用（服务端可以独立判棋，防改棋）

状态：**v1.4.0 已可发布**。客户端 + 服务端两个 exe，安装包 64.5 MB，
服务端不依赖 Python 和 Qt（19.4 MB）。**151 个测试全绿，发布自检 10/10**。
详见 [开发计划](docs/开发计划.md) 与 [M4 报告](docs/m4/验证报告.md)。

## 发布产物

| 文件 | 说明 |
|---|---|
| `release/一起来下棋-1.4.0-安装包.zip` | 发给别人就是这一个：解压 → 双击 `安装.cmd` |
| `dist/一起来下棋/` | 客户端（onedir，136 MB） |
| `dist/一起来下棋-服务端/` | 服务端（onedir，19.4 MB，可脱离 Python 运行） |

**异地联机**：服务端文件夹里的 `启动临时公网联机.cmd` 会用 Cloudflare 隧道给它一个公网地址，
把地址填进客户端即可，不需要公网 IP 或端口映射。详见 [异地联机指南](docs/异地联机-Cloudflare.md)。

---

## 目录

```
xiangqi_core/     棋规内核（纯 Python，零 Qt 依赖）
client/           PySide6 客户端：棋盘、素材、BGM、设置
server/           aiohttp 服务端：房间、消息中继（M2 会加权威判棋与计时）
tools/            M0 的验证脚本（spike_board/audio/net）+ M1 取证脚本（m1_shots）
tests/            pytest：棋盘、走法、服务端协议
build/            PyInstaller 配置
docs/             开发计划、决策记录、M0 验证报告与截图
launcher.py       程序入口 / 打包入口
```

## 环境

需要 Python 3.11+，且已装 PySide6 与 PyInstaller。用带 `--system-site-packages` 的虚拟环境，
可以直接复用系统里已经装好的 Qt，不用重下几百兆：

```powershell
python -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 中国大陆直连 PyPI 很慢，建议加清华镜像（上面已带）。要锁定版本就把 `requirements.txt` 里的 `>=` 改成 `==`。

## 跑起来

```powershell
# 服务端（打包版，不需要 Python）
dist\一起来下棋-服务端\一起来下棋-服务端.exe --port 8765

# 或者用源码跑（--base-minutes / --byo-seconds 可调计时）
.\.venv\Scripts\python.exe -m server.main --port 8765

# 客户端（不联机时就是本地双人对局）
.\.venv\Scripts\python.exe -m client.app
```

联机：两台机器各开客户端 → 菜单「联机 → 服务器地址…」填 `IP:端口` →
一台「创建房间」拿到 6 位码 → 另一台「加入房间」输码 → 双方点「准备」开局。

客户端菜单：

| 菜单 | 能做什么 |
|---|---|
| 对局 | 重新开始、翻转棋盘、认输、求和 |
| 联机 | 服务器地址、创建房间、加入房间、断开连接 |
| 设置（Ctrl+,） | 昵称、头像裁剪、服务器地址、背景图与暗化、音乐/音效音量 |
| 外观 | 选背景图、清除背景、背景更暗/更亮 |
| 音乐 | 选背景音乐（mp3/ogg/wav）、播放、暂停、停止 |
| 音效 | 落子/吃子/将军/胜利音效开关（音效为程序合成，无版权素材） |

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 阶段验证脚本

```powershell
.\.venv\Scripts\python.exe tools\spike_board.py   # 棋盘渲染 + 缩放不变形 + 背景图
.\.venv\Scripts\python.exe tools\spike_audio.py   # BGM 播放 + 音量淡入淡出
.\.venv\Scripts\python.exe tools\spike_net.py     # 两个客户端经 QWebSocket 互发一步棋
.\.venv\Scripts\python.exe tools\m1_shots.py      # M1：脚本化下棋 + 关键画面截图
.\.venv\Scripts\python.exe -m PyInstaller build\一起来下棋.spec --noconfirm --clean   # 打包
```

产物：`docs/m0/shots/*.png` 截图、`docs/m0/*.json` 数值报告。

## 打包

```powershell
.\.venv\Scripts\python.exe -m PyInstaller build\一起来下棋.spec --noconfirm --clean
```

输出 `dist\一起来下棋\一起来下棋.exe`（onedir，启动快；后续用 NSIS 做安装包）。
自检：`dist\一起来下棋\一起来下棋.exe --selftest`，会在 exe 同级目录生成 `selftest.png`。

## 素材与许可

- 棋子、棋盘、图标全部由程序绘制，不引用任何外部图片
- 程序**不内置任何音乐**，BGM 由用户自选本地文件
- 只用系统字体，不打包字体文件
- Qt / PySide6 为 LGPL：打包产物以独立 dll 形式附带 Qt，满足可替换要求
