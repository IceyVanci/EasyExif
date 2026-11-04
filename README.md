# EasyExif

EasyExif 是一个独立的开源 EXIF / XMP 元数据编辑器，使用 Python 实现。
它专注于无损读写 JPEG/TIFF 元数据，并提供 WebView2 桌面界面、命令行工具、
批量处理和带 13 项检查的原图可信度报告。

当前版本：0.1.0。

- 像素零改动：只替换或增删 JPEG 元数据段，扫描数据按字节保留
- 未知标签保留：未修改的 TIFF 条目原样写回
- 本地优先：桌面界面只连接 127.0.0.1，不访问网络
- 不包含任何私有特征库、设备库或第三方编辑器代码

## 功能

### 元数据

- JPEG / TIFF 的 IFD0、ExifIFD、GPS、Interop、IFD1 读取与写回
- 未知标签、未知 XMP 属性、未知厂商注释的无损保留
- JPEG 段查看、添加、删除和十六进制查看
- XMP 读写，保留未知命名空间与 Alt/Seq/Bag 结构
- IPTC / Photoshop APP13 常用字段只读展示
- 常用厂商注释解析：Canon、Nikon、Sony、Olympus、Fujifilm、Pentax、
  Apple、Samsung、Panasonic、DJI
- GPS 经纬度、海拔、时间；WGS-84 / GCJ-02 / BD-09 转换
- 缩略图读取与替换
- 元数据模板、文字戳、时间平移与同步

### 桌面界面

- pywebview + 系统 WebView2，真正的原生窗口
- 左中右三栏：文件信息、图像预览/直方图、元数据检查器
- 顶部 `编辑 / 预览` 滑块：预览模式保留完整布局，只禁用编辑操作
- 同时打开两张图像，文件名标签或 `Ctrl+Tab` 快速切换
- 编辑元数据时显示当前标签专属的说明、输入格式、常用值和实时解析预览
- 光圈/快门按自然值编辑：F 数（f/3.5）、快门时间（1/500）；APEX 技术字段只读
- 支持把 JPEG/TIFF 拖入窗口打开
- 关闭有未保存修改的文件时询问保存、不保存或取消

### 校验

13 项检查覆盖 EXIF 结构、第三方软件痕迹、厂商注释、压缩指纹、
内部/外部一致性、MPF、FlashPix、其他编辑器痕迹、直方图、
长宽比、内嵌图和图像尺寸。

- 评分 1–5 仅表示证据强弱，不是司法鉴定结论
- 文件没有 EXIF/TIFF 数据时报告为“未知”，不给出等级
- 检查结果会列出具体原因，便于复核
- 相机固件、手机系统、社交平台写入的正常字段可能造成误报

> 本报告是启发式检查，不能证明图像未经编辑，也不能作为司法鉴定或取证结论。
> 文件可能被有意清洗或伪造；5 级不代表绝对原图，1 级也不代表一定篡改。

### 批处理

- 递归扫描并导出 CSV
- 按拍摄日期、相机、镜头、月份分拣
- 按模板重命名
- 批量套用元数据模板
- 所有写操作默认先干跑预览

## 安装

要求 Python 3.10+。核心功能无第三方依赖；图像预览、直方图需要 Pillow。

~~~bash
python -m pip install -e .
~~~

WebView2 桌面界面：

~~~bash
python -m pip install -e ".[webui]"
~~~

Windows 10/11 需要系统自带的 Microsoft Edge WebView2 Runtime 和
.NET Framework 4.8。

## 单文件便携版

构建单个 exe：

~~~powershell
.\packaging\build.ps1 -Python python
~~~

产物为 `dist/EasyExif.exe`。首次启动会解压内置运行时到 exe 同目录的
`.easyexif-runtime`，请把 exe 放在可写目录。数据目录优先
`%LOCALAPPDATA%\EasyExif`，不可写时回退到 exe 同目录或其他可写位置。

## 命令行

~~~bash
easyexif info photo.jpg
easyexif dump photo.jpg --json
easyexif get photo.jpg Model DateTimeOriginal GPSLatitude
easyexif set photo.jpg Artist="Zhang San" Copyright="(c) 2026"
easyexif gps photo.jpg --set 39.9087,116.3975,43.8
easyexif validate photo.jpg
easyexif validate photo.jpg --json
easyexif segments photo.jpg
easyexif strip photo.jpg --out clean.jpg
~~~

批量处理：

~~~bash
easyexif batch photos/ --csv report.csv --profile detailed
easyexif batch photos/ --rename "{date}_{seq:03d}.{ext}"
easyexif batch photos/ --sort-by date --sort-root sorted/
easyexif batch photos/ --template examples/copyright.template.json
~~~

## Python API

~~~python
from easyexif import Metadata, validate

meta = Metadata.read("photo.jpg")
print(meta.get_text("Model"))
print(meta.get_text("ExposureTime"), meta.get_text("FNumber"))

meta.set("Artist", "Zhang San")
meta.set("DateTimeOriginal", "2026:01:02 15:30:00")
meta.set_gps(39.9087, 116.3975, alt=43.8)
meta.save("out.jpg", backup=True)

report = validate("out.jpg")
print(report.score, report.rating, report.summary)
for check in report.checks:
    print(check.title, check.status, check.detail)
~~~

底层对象：

~~~python
from easyexif.jpeg import Jpeg
from easyexif.tiff import Tiff

jpeg = Jpeg.parse(open("photo.jpg", "rb").read())
tiff = Tiff.parse(jpeg.exif_payload())
tiff.set("EXIF", 0xA434, "RF70-200mm F2.8 L IS USM")
jpeg.set_exif_payload(tiff.to_bytes())
open("out.jpg", "wb").write(jpeg.to_bytes())
~~~

## 测试

~~~bash
set PYTHONPATH=src
python -m unittest discover -s tests -v
~~~

共 53 个测试，覆盖 TIFF 大小端往返、未知标签保留、JPEG 扫描段逐字节
保留、EXIF/XMP 注入、厂商注释偏移重编码、GPS 转换、模板、校验、
批量处理以及 Web UI 接口；包含 MPF 内联值、相机固件识别和自然值同步回归。

## 设计说明

~~~text
src/easyexif/
  tags.py       标签字典、类型与显示格式化
  tiff.py       TIFF/EXIF 解析与重建
  jpeg.py       JPEG 段解析与重建
  xmp.py        XMP 包解析与定点写入
  makernote.py  厂商注释识别与字段解码
  metadata.py   统一元数据门面
  gps.py        坐标转换与地图链接
  validate.py   13 项一致性与原始性检查
  template.py   元数据模板、文字戳
  batch.py      CSV、重命名、分拣
  cli.py        命令行
  webui/        WebView2 桌面界面
~~~

保存策略：

1. 先写同目录临时文件，再用原子替换写入目标文件
2. JPEG 只改动元数据段，不重新编码像素
3. 未修改的 TIFF 条目沿用原始字节
4. 需要重算的厂商注释偏移在重建时更新

## 限制

- 校验是基于结构与常见软件痕迹的启发式规则，可以被清洗或伪造绕过
- 厂商注释只覆盖常用字段，未知字段仍会保留但可能不显示名称
- 不支持 RAW 像素结构（CR2/NEF/ARW 等），仅支持 JPEG 与 TIFF 容器
- IPTC 为只读，写回尚未实现
- 地图功能只生成外部链接，不抓取瓦片、不默认联网
- XMP 写入是定点替换，极端嵌套或重复属性建议在 XMP 面板中复核

## 许可

MIT，见 [LICENSE](LICENSE)。
