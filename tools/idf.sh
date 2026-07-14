#!/usr/bin/env bash
# ESP-IDF 构建/烧录/监视封装脚本(Linux 版),对应 tools/idf.ps1。
# 统一把构建产物放在 build/idf、sdkconfig 放在 build/sdkconfig,和 CI 保持一致。
#
# 用法:
#   tools/idf.sh build                       # 构建固件
#   tools/idf.sh package                     # 构建并打包 OTA/整机镜像到 build/dist
#   tools/idf.sh flash -p /dev/ttyACM0      # 烧录(不带 -p 时自动探测串口)
#   tools/idf.sh monitor -p /dev/ttyACM0    # 打开串口日志,Ctrl+] 退出
#   tools/idf.sh flash-monitor               # 烧录后直接打开串口日志
#   tools/idf.sh set-target                  # 首次或切换芯片时显式设为 esp32c3
#   tools/idf.sh reconfigure|clean|fullclean
#
# 环境变量:
#   IDF_PATH        ESP-IDF 安装目录,默认 ~/esp/esp-idf-v5.5.4
#   IDF_TOOLS_PATH  工具链目录,默认 ~/.espressif

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$REPO_ROOT/build/idf"
SDKCONFIG="$REPO_ROOT/build/sdkconfig"

IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.5.4}"
export IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$HOME/.espressif}"

# 解析参数:首个非选项参数作为动作,-p/--port 指定串口,-j/--jobs 指定并行度
ACTION=""
PORT=""
JOBS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--port)  PORT="$2"; shift 2 ;;
        -j|--jobs)  JOBS="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*)
            echo "未知选项:$1" >&2; exit 2 ;;
        *)
            if [[ -z "$ACTION" ]]; then ACTION="$1"; else echo "多余参数:$1" >&2; exit 2; fi
            shift ;;
    esac
done
ACTION="${ACTION:-build}"

EXPORT_SCRIPT="$IDF_PATH/export.sh"
if [[ ! -f "$EXPORT_SCRIPT" ]]; then
    echo "找不到 ESP-IDF export 脚本:$EXPORT_SCRIPT" >&2
    echo "请先按 dev_doc/linux_build_flash.md 安装 ESP-IDF v5.5.4,或用 IDF_PATH 指定安装目录。" >&2
    exit 1
fi

mkdir -p "$BUILD_DIR"

# 加载 ESP-IDF 环境;export.sh 不适配 set -e/-u,先普通模式加载,失败再终止
# shellcheck disable=SC1090
. "$EXPORT_SCRIPT"
if ! command -v idf.py >/dev/null 2>&1; then
    echo "加载 ESP-IDF 环境失败(idf.py 不可用),请检查 $EXPORT_SCRIPT 输出。" >&2
    exit 1
fi
set -eo pipefail

IDF_ARGS=(-B "$BUILD_DIR" -D "SDKCONFIG=$SDKCONFIG")

# 未显式指定端口时探测常见串口;探测不到则不传 -p,交给 idf.py 自行查找
PORT_ARGS=()
resolve_port() {
    if [[ -z "$PORT" ]]; then
        local dev
        for dev in /dev/ttyACM* /dev/ttyUSB*; do
            if [[ -e "$dev" ]]; then PORT="$dev"; echo "自动选择串口:$PORT"; break; fi
        done
    fi
    if [[ -n "$PORT" ]]; then
        if [[ ! -w "$PORT" ]]; then
            echo "警告:当前用户对 $PORT 无写权限,烧录可能失败。" >&2
            echo "执行 sudo usermod -aG dialout \$USER 后注销重登即可。" >&2
        fi
        PORT_ARGS=(-p "$PORT")
    else
        echo "未检测到 /dev/ttyACM*、/dev/ttyUSB* 串口,交给 idf.py 自动探测。"
    fi
}

do_build() {
    idf.py "${IDF_ARGS[@]}" reconfigure
    if [[ -n "$JOBS" ]]; then
        ninja -C "$BUILD_DIR" -j "$JOBS"
    else
        ninja -C "$BUILD_DIR"
    fi
}

case "$ACTION" in
    build)
        do_build
        ;;
    package)
        # 与 CI(.github/workflows/build.yml)的发布打包保持一致,产物按仓库约定放 build/dist:
        #   sms_forwarder_ota_v<版本>.bin   网页「固件升级」直接上传(仅 app 分区镜像)
        #   sms_forwarder_full_v<版本>.bin  整机烧录包,esptool 从 0x0 写入
        do_build
        VERSION="$(grep -oP 'IDF_FW_VERSION = "\K[0-9A-Za-z.\-]+' \
            "$REPO_ROOT/components/idf_config/include/idf_config.h")"
        if [[ -z "$VERSION" ]]; then
            echo "无法从 components/idf_config/include/idf_config.h 解析 IDF_FW_VERSION,打包终止。" >&2
            exit 1
        fi
        DIST_DIR="$REPO_ROOT/build/dist"
        mkdir -p "$DIST_DIR"
        cp "$BUILD_DIR/sms_forwarding_idf.bin" "$DIST_DIR/sms_forwarder_ota_v${VERSION}.bin"
        esptool.py --chip esp32c3 merge_bin -o "$DIST_DIR/sms_forwarder_full_v${VERSION}.bin" \
            0x0 "$BUILD_DIR/bootloader/bootloader.bin" \
            0x8000 "$BUILD_DIR/partition_table/partition-table.bin" \
            0x10000 "$BUILD_DIR/sms_forwarding_idf.bin"
        echo "打包完成(固件 v${VERSION}):"
        ls -l "$DIST_DIR"
        ;;
    flash)
        resolve_port
        idf.py "${IDF_ARGS[@]}" "${PORT_ARGS[@]}" flash
        ;;
    monitor)
        resolve_port
        idf.py "${IDF_ARGS[@]}" "${PORT_ARGS[@]}" monitor
        ;;
    flash-monitor)
        resolve_port
        idf.py "${IDF_ARGS[@]}" "${PORT_ARGS[@]}" flash monitor
        ;;
    set-target)
        idf.py "${IDF_ARGS[@]}" set-target esp32c3
        ;;
    reconfigure|clean|fullclean)
        idf.py "${IDF_ARGS[@]}" "$ACTION"
        ;;
    *)
        echo "未知动作:$ACTION(可用:build/flash/monitor/flash-monitor/set-target/reconfigure/clean/fullclean)" >&2
        exit 2
        ;;
esac
