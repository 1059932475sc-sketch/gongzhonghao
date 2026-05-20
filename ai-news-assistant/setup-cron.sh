#!/bin/bash
# ============================================================
# AI 资讯情报官 - 每日定时任务安装脚本
# ============================================================
# 运行一次即可，之后每天自动执行
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.ai-news-assistant.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "=============================================="
echo "🤖 AI 资讯情报官 - 定时任务安装"
echo "=============================================="

# 1. 检查 API Key
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "⚠️  未检测到 .env 文件"
    echo "   请先配置 API Key："
    echo "   cp .env.example .env"
    echo "   然后编辑 .env 填入你的 API Key"
    echo ""
    echo "   推荐用 DeepSeek（便宜，中文好）："
    echo "   1. 注册 https://platform.deepseek.com/"
    echo "   2. 创建 API Key"
    echo "   3. 填入 .env 文件"
    echo ""
    read -p "按回车继续安装（API 生成会降级为模板模式）..."
fi

# 2. 确保 LaunchAgents 目录存在
mkdir -p "$HOME/Library/LaunchAgents"

# 3. 创建 plist 文件
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${SCRIPT_DIR}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/cron.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/cron.err</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
EOF

# 从 .env 读取变量添加进 plist
if [ -f "$SCRIPT_DIR/.env" ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        key=$(echo "$key" | tr -d ' ')
        value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        echo "        <key>$key</key>" >> "$PLIST_PATH"
        echo "        <string>$value</string>" >> "$PLIST_PATH"
    done < "$SCRIPT_DIR/.env"
fi

cat >> "$PLIST_PATH" << EOF
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

echo "📝  已创建 plist: $PLIST_PATH"

# 4. 加载定时任务
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "✅  定时任务已加载"

# 5. 验证
if launchctl list | grep -q "${PLIST_NAME}"; then
    echo "✅  验证成功！每天 9:00 自动运行"
else
    echo "⚠️  验证失败，请手动检查"
fi

echo ""
echo "=============================================="
echo "📋 常用命令："
echo "   手动运行:  cd $SCRIPT_DIR && python3 main.py"
echo "   查看日志:  cat $SCRIPT_DIR/cron.log"
echo "   查看错误:  cat $SCRIPT_DIR/cron.err"
echo "   停止定时:  launchctl unload $PLIST_PATH"
echo "=============================================="
