#!/usr/bin/env bash
# 将内部反馈日报安装为 systemd oneshot 服务和每日定时器。

set -euo pipefail

SERVICE_NAME="ops-feedback-report"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/systemd"
UNIT_DIR="/etc/systemd/system"

usage() {
    printf '%s\n' \
        "用法: sudo bash install_systemd.sh --project-root <项目目录> --venv <虚拟环境目录> --user <服务账号> [--group <服务组>] [--insight-config <模型配置文件>]"
}

fail() {
    printf '安装失败: %s\n' "$1" >&2
    exit 1
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "${value}" && "${value}" != --* ]] || fail "${option} 缺少参数值"
}

validate_path() {
    local label="$1"
    local value="$2"
    # 限制路径字符，避免 systemd 说明符和模板替换产生歧义。
    [[ "${value}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "${label} 必须是仅含字母、数字、点、下划线、横线和斜杠的绝对路径"
}

project_root=""
venv_dir=""
service_user=""
service_group=""
insight_config=""
while (($#)); do
    case "$1" in
        --project-root)
            require_value "$1" "${2:-}"
            project_root="$2"
            shift 2
            ;;
        --venv)
            require_value "$1" "${2:-}"
            venv_dir="$2"
            shift 2
            ;;
        --user)
            require_value "$1" "${2:-}"
            service_user="$2"
            shift 2
            ;;
        --group)
            require_value "$1" "${2:-}"
            service_group="$2"
            shift 2
            ;;
        --insight-config)
            require_value "$1" "${2:-}"
            insight_config="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "未知参数: $1"
            ;;
    esac
done

[[ "${EUID}" -eq 0 ]] || fail "请使用 root 权限执行"
[[ -n "${project_root}" ]] || fail "必须传入 --project-root"
[[ -n "${venv_dir}" ]] || fail "必须传入 --venv"
[[ -n "${service_user}" ]] || fail "必须传入 --user"
[[ "${service_user}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || fail "服务账号格式无效"
id "${service_user}" >/dev/null 2>&1 || fail "服务账号不存在: ${service_user}"
service_group="${service_group:-$(id -gn "${service_user}")}"
[[ "${service_group}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || fail "服务组格式无效"
getent group "${service_group}" >/dev/null 2>&1 || fail "服务组不存在: ${service_group}"

[[ -d "${project_root}" ]] || fail "项目目录不存在: ${project_root}"
[[ -d "${venv_dir}" ]] || fail "虚拟环境目录不存在: ${venv_dir}"
command -v realpath >/dev/null 2>&1 || fail "当前系统未安装 realpath"
project_root="$(realpath -- "${project_root}")"
venv_dir="$(realpath -- "${venv_dir}")"
validate_path "项目目录" "${project_root}"
validate_path "虚拟环境目录" "${venv_dir}"
if [[ -n "${insight_config}" ]]; then
    [[ -f "${insight_config}" ]] || fail "模型配置文件不存在: ${insight_config}"
    insight_config="$(realpath -- "${insight_config}")"
    validate_path "模型配置文件" "${insight_config}"
fi

report_script="${project_root}/opscli/skills/templates/ops-feedback-query/scripts/daily_feedback_report.py"
credentials_file="${project_root}/opscli/skills/templates/ops-feedback-query/data/credentials.json"
python_bin="${venv_dir}/bin/python"
opscli_bin="${venv_dir}/bin/opscli"
output_dir="${project_root}/output/feedback-query"
service_template="${TEMPLATE_DIR}/${SERVICE_NAME}.service.in"
timer_template="${TEMPLATE_DIR}/${SERVICE_NAME}.timer"

[[ -d "${project_root}/.git" ]] || fail "项目目录不是 Git 工作区: ${project_root}"
[[ -f "${report_script}" ]] || fail "未找到反馈日报脚本: ${report_script}"
[[ -f "${credentials_file}" ]] || fail "未找到反馈凭据文件: ${credentials_file}"
[[ -x "${python_bin}" ]] || fail "虚拟环境 Python 不可执行: ${python_bin}"
[[ -x "${opscli_bin}" ]] || fail "虚拟环境 opscli 不可执行: ${opscli_bin}"
"${python_bin}" - "${credentials_file}" <<'PY' || fail "反馈密钥或企业微信 Webhook 尚未配置"
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
for field in ("feedback_api_key", "wecom_webhook_url"):
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip() or value.startswith("REPLACE_WITH_"):
        raise SystemExit(1)
PY
insight_args=""
if [[ -n "${insight_config}" ]]; then
    "${python_bin}" - "${insight_config}" <<'PY' || fail "模型配置缺少 endpoint、api_key 或 model"
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
for field in ("endpoint", "api_key", "model"):
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip() or "REPLACE_WITH_" in value:
        raise SystemExit(1)
PY
    chown "${service_user}:${service_group}" "${insight_config}"
    chmod 0600 "${insight_config}"
    insight_args="--insight --insight-config ${insight_config}"
fi
[[ -f "${service_template}" ]] || fail "未找到 systemd 服务模板"
[[ -f "${timer_template}" ]] || fail "未找到 systemd 定时器模板"
command -v systemctl >/dev/null 2>&1 || fail "当前系统未安装 systemctl"
command -v systemd-analyze >/dev/null 2>&1 || fail "当前系统未安装 systemd-analyze"

# 输出目录和凭据只授权给专用服务账号，避免日报与机器人地址被其他账号读取。
install -d -o "${service_user}" -g "${service_group}" -m 0700 "${output_dir}"
chown "${service_user}:${service_group}" "${credentials_file}"
chmod 0600 "${credentials_file}"

rendered_service="$(mktemp)"
trap 'rm -f "${rendered_service}"' EXIT
sed \
    -e "s|@SERVICE_USER@|${service_user}|g" \
    -e "s|@SERVICE_GROUP@|${service_group}|g" \
    -e "s|@PROJECT_ROOT@|${project_root}|g" \
    -e "s|@VENV_BIN@|${venv_dir}/bin|g" \
    -e "s|@PYTHON_BIN@|${python_bin}|g" \
    -e "s|@REPORT_SCRIPT@|${report_script}|g" \
    -e "s|@OUTPUT_DIR@|${output_dir}|g" \
    -e "s|@INSIGHT_ARGS@|${insight_args}|g" \
    "${service_template}" >"${rendered_service}"

install -m 0644 "${rendered_service}" "${UNIT_DIR}/${SERVICE_NAME}.service"
install -m 0644 "${timer_template}" "${UNIT_DIR}/${SERVICE_NAME}.timer"
systemctl daemon-reload
systemd-analyze verify \
    "${UNIT_DIR}/${SERVICE_NAME}.service" \
    "${UNIT_DIR}/${SERVICE_NAME}.timer"
systemctl enable --now "${SERVICE_NAME}.timer"

printf '%s\n' \
    "安装完成: ${SERVICE_NAME}.timer 已启用" \
    "查看计划: systemctl list-timers ${SERVICE_NAME}.timer" \
    "首次验证: systemctl start ${SERVICE_NAME}.service"
