# EasyExif WebView2 前端方案 v4（Windows Only，地图暂缓）

日期：2026-11-03
状态：已完成首版 WebView2 界面与单 exe 打包

## 1. 最终决定

采用 **pywebview 6.2.1 + 系统 WebView2** 作为唯一主界面：

- 真正的原生窗口，内嵌 WebView2，不经过 Edge 浏览器
- 没有 Edge 账户同步、扩展、AdBlock 等弹窗
- 前端为本地 HTTP + JSON，pywebview 只负责窗口
- 代码中不再保留 Edge --app 路径，避免误把浏览器配置带进桌面工具

早期调试曾用 Edge --app，出现的“同步浏览数据”弹窗已确认是 Edge 自身 UI，与 EasyExif 无关。该调试路径已经删除；当前实现只有 pywebview / WebView2。

## 2. 架构

~~~text
┌──────────────────────────────────────────────┐
│ pywebview 原生窗口                            │
│  WebView2 加载 http://127.0.0.1:<port>/?token │
└──────────────────┬───────────────────────────┘
                   │ HTTP + JSON
┌──────────────────▼───────────────────────────┐
│ webui 服务（Python 标准库）                    │
│  静态文件 / REST / 会话 / 撤销 / 批量          │
│  原生文件对话框（Tk 子进程线程）               │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│ easyexif 核心                                 │
└──────────────────────────────────────────────┘
~~~

启动流程：

1. 找空闲端口，启动 127.0.0.1 服务，生成随机 token
2. 打开 pywebview 窗口，加载带 token 的本地 URL
3. 关闭窗口时检查 dirty，必要时弹确认框
4. 服务随窗口退出而停止

## 3. 依赖

运行时：

| 组件 | 版本/说明 |
| --- | --- |
| Windows | 10/11 |
| WebView2 Runtime | 系统已安装（本机 156.0.4314.58） |
| .NET Framework | 4.8（Windows 自带） |
| Python | 内置到 exe，用户无需安装 |
| pywebview | 6.2.1 |
| pythonnet | 3.2.1（netfx 模式） |
| clr_loader / cffi | 0.3.1 / 2.1.1 |
| bottle / proxy_tools / typing_extensions | pywebview 依赖 |

开发依赖安装：

~~~powershell
$env:HTTP_PROXY='http://127.0.0.1:7897'
$env:HTTPS_PROXY='http://127.0.0.1:7897'
python -m pip install -r requirements-webui.txt
~~~

pywebview 自带 WebView2 托管 DLL 与 x64/x86/arm64 Loader；系统只需要 WebView2 Runtime。

## 4. 界面

宽松现代风格，三栏工作台：

~~~text
┌ 顶栏：品牌 / 文件名 / 打开 保存 撤销 重做 校验 批处理 / 主题 ┐
├─────────────┬───────────────────────────────┬─────────────┤
│ 左栏 250px  │ 画布                           │ 右栏 430px  │
│ 文件卡片    │ 图像预览 / 直方图               │ 元数据      │
│ 文件信息    │ 缩放、适应窗口                 │ XMP         │
│ 快捷操作    │                               │ JPEG 段     │
│ 提示        │                               │ GPS         │
│             │                               │ 校验        │
├─────────────┴───────────────────────────────┴─────────────┤
│ 状态栏：路径 / 操作结果 / 警告                              │
└───────────────────────────────────────────────────────────┘
~~~

已实现的交互：

- 打开：原生文件对话框，加载 JPEG/TIFF/EXI
- 元数据树：按 IFD 分组、搜索、选中、双击编辑、添加、删除、撤销
- XMP：原始包编辑与应用
- JPEG 段：列表、十六进制查看、添加 COM、删除
- GPS：十进制显示、写入、移除、WGS-84/GCJ-02/BD-09 选择、外部地图链接
- 校验：13 项报告、1–5 级评分、状态色块
- 批处理：扫描目录、CSV 导出、重命名、分拣、模板套用、干跑
- 直方图：256 bins 绘制与均值
- 深色/浅色主题，本地持久化
- 关闭前未保存确认

地图嵌入仍 hold，只保留外部链接。

## 5. 代码结构

~~~text
src/easyexif/webui/
  __init__.py
  __main__.py      模块入口
  launch.py        启动参数、服务、窗口生命周期
  server.py        127.0.0.1 HTTP 服务、token、静态文件
  api.py           REST 路由与批处理
  session.py       文档会话、快照撤销、预览、校验
  shell.py         pywebview / WebView2 窗口（唯一窗口实现）
  dialogs.py       原生打开/保存对话框
  paths.py         源码/单文件 exe 的静态目录、数据目录
  static/
    index.html
    css/app.css
    js/api.js
    js/ui.js
    js/app.js
~~~

服务只监听 127.0.0.1，token 必填，静态文件白名单，路径穿越防护。

## 6. 单 exe 打包

构建脚本：packaging/build.ps1（或 packaging/build.cmd，后者绕过 PowerShell 执行策略）

~~~powershell
# 开发机先安装依赖
python -m pip install -r requirements-webui.txt

# 构建无控制台版本
.\packaging\build.ps1

# 构建调试版（有控制台）
.\packaging\build.ps1 -Console
~~~

产物：

~~~text
dist/EasyExif.exe       约 32 MB，单文件
dist/EasyExifDebug.exe  调试版
~~~

打包要点：

- --onefile --windowed
- --runtime-tmpdir .easyexif-runtime：不依赖系统 TEMP，避免 Could not create temporary directory!；运行时目录位于 exe 同目录，需可写
- 收集 webview / pythonnet / clr_loader / cffi 的数据与子模块
- 收集 Python.Runtime.dll、WebView2 Core/WinForms DLL、WebView2Loader.dll
- 静态文件通过 --add-data 嵌入
- 旁加载 sitecustomize/temp 目录不属于发布形态
- 目标机需 WebView2 Runtime；缺失时启动应提示安装（后续补）

## 7. 验证记录

- 单元测试：44 个全部通过（含 POST body 与 keep-alive 回归），包含 Web UI 的鉴权、打开/编辑/撤销/保存、预览、直方图、段、校验、批量
- CDP 交互测试：标签新增、撤销、校验、批处理弹窗、主题切换均通过，无 JS 异常
- pywebview 嵌入测试：document.title、53 行元数据、预览 naturalWidth=1600
- 单 exe 测试：窗口标题 EasyExif、服务监听、关闭窗口后进程与端口释放
- 将 TEMP 指向无效路径后，单 exe 仍可启动（runtime 目录 .easyexif-runtime）
- 将 LOCALAPPDATA/APPDATA/USERPROFILE/PUBLIC/TEMP 全部指向无效路径后，程序回退到 exe 同目录 EasyExifData 并正常启动
- Edge 方案的同步弹窗已确认与本项目无关，并已从发布路径移除

## 8. 已知限制

- WebView2 Runtime 是硬依赖；极少数精简 Windows 需要手动安装
- 单文件 exe 首次启动会解压运行时，约 1–3 秒
- .NET Framework 4.8 为 pythonnet 的运行基础
- 地图嵌入仍 hold
- IPTC 写回、MPF 写回、模板可视化编辑、批量进度条、图像旋转/缩放/加噪尚未完成
- 校验是启发式规则，不是司法取证

## 9. 后续里程碑

| 阶段 | 内容 |
| --- | --- |
| M1 | IPTC 写回、MPF 修复、EOF 编辑 |
| M2 | 模板可视化编辑器、批量进度/取消、导出预览 |
| M3 | 图像旋转/缩放/裁剪黑边、对比工具 |
| M4 | 打包安装器/便携 zip、WebView2 缺失检测、自动更新检查（可选） |
| M5 | 厂商注释字典扩充、预览图提取 |
