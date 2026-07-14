# Linux 环境搭建与构建烧录指南

本文是 `README.md` 烧录教程(Windows/PowerShell)的 Linux 对应版本。Linux 下使用 `tools/idf.sh`(对应 `tools/idf.ps1`),构建产物同样落在 `build/idf`、配置落在 `build/sdkconfig`,与 CI 一致。

## 一、一次性环境安装

### 1. 系统依赖(需要 sudo,可选)

```bash
sudo apt-get install git wget flex bison gperf python3 python3-pip python3-venv \
    cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0
```

说明:这是官方推荐依赖,但**实测非必需**——只要系统有 git、python3、python3-venv、libusb,配合第 3 步用 ESP-IDF 自带的 cmake/ninja,即可完成完整构建(已在 Python 3.14 + ESP-IDF v5.5.4 环境验证)。构建报错缺什么再补装即可。

### 2. 串口权限(需要 sudo,一次性)

```bash
sudo usermod -aG dialout $USER
```

执行后**注销并重新登录**才生效。不加组会在烧录时报 `Permission denied: /dev/ttyACM0`。

### 3. 安装 ESP-IDF v5.5.4(不需要 sudo)

```bash
mkdir -p ~/esp
git clone -b v5.5.4 --depth 1 --recursive --shallow-submodules \
    https://github.com/espressif/esp-idf.git ~/esp/esp-idf-v5.5.4
cd ~/esp/esp-idf-v5.5.4
./install.sh esp32c3
# 系统没有 cmake/ninja 时,用 ESP-IDF 自带版本补齐:
python3 tools/idf_tools.py install cmake ninja
```

工具链默认安装到 `~/.espressif`(可用 `IDF_TOOLS_PATH` 覆盖)。国内网络下载工具链慢时,可在安装前 `export IDF_GITHUB_ASSETS="dl.espressif.com/github_assets"` 使用官方镜像。

安装位置约定:`tools/idf.sh` 默认查找 `~/esp/esp-idf-v5.5.4`,装在其他位置时通过 `IDF_PATH` 环境变量指定。

## 二、日常构建 / 烧录 / 日志

### 方式一:烧录 TUI(推荐,可视化选串口)

```bash
tools/flash_tui.py          # 打开交互界面
tools/flash_tui.py --list   # 仅打印串口设备列表
```

界面会列出所有 `/dev/ttyACM*`、`/dev/ttyUSB*` 设备,识别 USB 芯片(如 Espressif 原生 USB、CH34x、CP210x)并标注权限状态。按键:

- `↑↓` / `j k` 选择串口,`r` 刷新列表;
- `Enter` / `f` 烧录,`g` 烧录并打开日志,`m` 仅看串口日志(`Ctrl+]` 退出);
- `b` 仅构建,`p` 构建并打包 OTA/整机镜像(产物在 `build/dist/`),`q` 退出。

TUI 底层复用下面的 `tools/idf.sh`,零第三方依赖(仅用 Python3 标准库)。

### 方式二:命令行 idf.sh

仓库封装脚本会自动 source `export.sh`,不需要手动激活环境:

```bash
tools/idf.sh build                      # 构建固件
tools/idf.sh package                    # 构建并打包 OTA/整机镜像到 build/dist
tools/idf.sh flash -p /dev/ttyACM0     # 烧录
tools/idf.sh flash-monitor -p /dev/ttyACM0  # 烧录后直接看日志
tools/idf.sh monitor -p /dev/ttyACM0   # 串口日志,Ctrl+] 退出
```

- 不带 `-p` 时脚本自动探测第一个 `/dev/ttyACM*`、`/dev/ttyUSB*` 设备。带原生 USB 的 ESP32-C3(如 Super Mini)是 `ttyACM0`,CH340/CP2102 转串口的板子是 `ttyUSB0`;插上设备后 `ls /dev/ttyACM* /dev/ttyUSB*` 可确认。
- `package` 打包内容与 CI Release 一致,版本号取自 `components/idf_config/include/idf_config.h` 的 `IDF_FW_VERSION`:`sms_forwarder_ota_v<版本>.bin` 在网页「固件升级」页直接上传(仅 app 镜像);`sms_forwarder_full_v<版本>.bin` 整机烧录,`esptool.py --chip esp32c3 write_flash 0x0 <文件>`。
- 其他动作:`set-target`(首次配置芯片,可选,`sdkconfig.defaults` 已默认 esp32c3)、`reconfigure`、`clean`、`fullclean`;`-j N` 控制并行度。
- 改过 `code/web_src/` 后,构建前先重新生成静态资源:

```bash
python3 tools/build_web_assets.py
python3 tools/build_web_assets.py --check
```

也可以不用封装脚本,手动执行(与 CI 命令一致):

```bash
source ~/esp/esp-idf-v5.5.4/export.sh
idf.py -B build/idf -D SDKCONFIG=build/sdkconfig build
idf.py -B build/idf -D SDKCONFIG=build/sdkconfig -p /dev/ttyACM0 flash monitor
```

## 三、不装 ESP-IDF,直接烧录 Release 固件

CI 在每次推送 master 后自动发布 Release,附两种固件包:

- `sms_forwarder_full_v*.bin`:整机包(bootloader+分区表+app 合并),线刷从 `0x0` 写入;
- `sms_forwarder_ota_v*.bin`:OTA 包,设备已运行本固件时在 Web「固件升级」页直接上传,无需数据线。

线刷只需要 esptool:

```bash
pipx install esptool    # 或 pip install --user esptool
esptool.py --chip esp32c3 -p /dev/ttyACM0 -b 460800 write_flash 0x0 sms_forwarder_full_v1.0.9.bin
```

## 四、首次启动

设备无已保存 WiFi 时开热点 `SMS-Forwarder-XXXX`,连接后访问 `http://192.168.1.1` 配网;入网后通过串口日志中的 IP 或 `http://sms.local` 打开 Web UI。默认账号 `admin` / `admin123`,首次登录立即修改。

## 五、常见问题

| 现象 | 处理 |
| --- | --- |
| 烧录时 `Permission denied` | `sudo usermod -aG dialout $USER` 后注销重登 |
| 无法自动进入下载模式 | 按住 `BOOT`,轻点 `RST/EN`,烧录开始后松开 `BOOT` |
| 找不到串口设备 | 换用数据线(非充电线);`dmesg -w` 观察插拔时内核是否识别 |
| 提示找不到 export.sh | 确认 ESP-IDF 装在 `~/esp/esp-idf-v5.5.4`,或设置 `IDF_PATH` |
| 构建报 cmake/ninja 缺失 | `python3 $IDF_PATH/tools/idf_tools.py install cmake ninja` 或 apt 安装 |
