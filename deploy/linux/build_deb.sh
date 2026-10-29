#!/usr/bin/env bash
# ============================================================
# 快截OCR —— Linux/信创(UOS 20 / 银河麒麟V10, x86_64 & aarch64) 构建 deb 包
# 用法:
#   ./build_deb.sh                      # 构建 amd64 deb
#   ./build_deb.sh --arch arm64         # 在 aarch64 构建机/容器上出 arm64 包
# 前置:
#   python3 -m venv .venv && .venv/bin/pip install -r requirements-linux.txt
#   sudo apt-get install -y python3-dev build-essential dpkg-dev fakeroot
# 说明:
#   PyInstaller 不能跨 glibc/架构交叉打包，本脚本必须在目标同级系统上运行。
#   推荐在 Debian 10(buster)/UOS20 容器中执行，产物可覆盖 glibc>=2.28。
#   非 .venv 构建环境可用 PYINSTALLER=/path/to/pyinstaller 覆盖。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/../.."
ARCH="${2:-amd64}"
VERSION="1.0.0"
WORK="dist/linux-${ARCH}"
PKGDIR="${WORK}/snapocr_${VERSION}_${ARCH}"
PYINSTALLER="${PYINSTALLER:-.venv/bin/pyinstaller}"

echo "[1/5] PyInstaller 打包 (Linux)..."
"$PYINSTALLER" --noconfirm --clean deploy/snapocr-linux.spec

echo "[2/5] 组装 deb 目录..."
rm -rf "$PKGDIR"
mkdir -p "${PKGDIR}/opt/snapocr" "${PKGDIR}/DEBIAN" \
         "${PKGDIR}/usr/bin" "${PKGDIR}/usr/share/applications" \
         "${PKGDIR}/usr/share/icons/hicolor/scalable/apps"
cp -a dist/snapocr-linux64/. "${PKGDIR}/opt/snapocr/"

cat > "${PKGDIR}/DEBIAN/control" <<EOF
Package: snapocr
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: 中共枣庄市委组织部 <dev@local>
Depends: libgl1, libglib2.0-0, libdbus-1-3, libx11-6, libxcb1, libfontconfig1,
 libxkbcommon0, libxkbcommon-x11-0, libxcb-icccm4, libxcb-image0,
 libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0,
 libxcb-randr0, libxcb-render0, libxcb-shm0, libxcb-xfixes0, libice6, libsm6
Section: utils
Priority: optional
Homepage: http://www.zaozhuang.gov.cn
Installed-Size: $(du -sk "${PKGDIR}/opt" | cut -f1)
Description: 截图工具 - 离线截图OCR工具 (RapidOCR/PP-OCRv6)
 .
 开发单位：中共枣庄市委组织部
EOF

cat > "${PKGDIR}/usr/bin/snapocr" <<'EOF'
#!/bin/bash
exec /opt/snapocr/SnapOCR "$@"
EOF
chmod +x "${PKGDIR}/usr/bin/snapocr"

cat > "${PKGDIR}/usr/share/applications/snapocr.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=截图工具
Name[en]=SnapOCR
Comment=框选截屏并离线OCR识别
Exec=/opt/snapocr/SnapOCR
Icon=snapocr
Terminal=false
Categories=Utility;Graphics;
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF
# 托盘/菜单图标：从包内 resources 复制。
# 注意：PyInstaller 5.x 的 onedir 布局是 <dir>/resources，6.x 改为 <dir>/_internal/resources，
# 而 requirements-linux.txt 允许 5.13~6.x —— 必须两种都探测，否则 6.x 构建时图标会
# 静默缺失（下面的 if 会直接跳过，deb 里没有图标，开始菜单显示通用占位图）。
ICON_SRC=""
for cand in \
    "dist/snapocr-linux64/resources/app.png" \
    "dist/snapocr-linux64/_internal/resources/app.png"; do
  if [ -f "$cand" ]; then
    ICON_SRC="$cand"
    break
  fi
done
if [ -n "$ICON_SRC" ]; then
  cp "$ICON_SRC" "${PKGDIR}/usr/share/icons/hicolor/scalable/apps/snapocr.png"
else
  echo "[WARN] 未找到包内 resources/app.png（已探测 5.x/6.x 两种布局），deb 将不含图标" >&2
fi

echo "[3/5] 生成 DEBIAN 脚本..."
# preinst：升级/重装前先停掉旧常驻实例。否则内存看门狗的自愈重启可能在
# dpkg 解包期间启动新进程，读到半写入的 PyInstaller 归档，表现为
# zlib.error: incorrect header check（2026-10-29 用户反馈）。
cat > "${PKGDIR}/DEBIAN/preinst" <<'EOF'
#!/bin/sh
set -e
if [ -x /opt/snapocr/SnapOCR ]; then
  /opt/snapocr/SnapOCR --exit >/dev/null 2>&1 || true
fi
pkill -x SnapOCR >/dev/null 2>&1 || true
sleep 1
exit 0
EOF
chmod 755 "${PKGDIR}/DEBIAN/preinst"

cat > "${PKGDIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
# 依赖前置库由 apt 处理；给可执行文件加执行位
chmod +x /opt/snapocr/SnapOCR || true
# 信创 Wayland 会话需 org.freedesktop.portal.screenshot 授权，否则按热键"完全没反应"
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
  if command -v flatpak >/dev/null 2>&1; then
    flatpak permission Grant screenshot snapocr 2>/dev/null || true
  fi
  # 通过 xdg-permission-store 尽力预授予（无 DBus 会话时跳过，不阻塞安装）
  busctl --user call org.freedesktop.impl.portal.PermissionStore \
    /org/freedesktop/impl/portal/PermissionStore \
    org.freedesktop.impl.portal.PermissionStore Set \
    "s" "s" "u" "as" "screenshot" "snapocr" 0 "[]" 2>/dev/null || true
  echo "Wayland 会话：若首次截图无反应，请允许桌面弹出的截图授权，或运行：" >&2
  echo "  flatpak permission Grant screenshot snapocr" >&2
fi
exit 0
EOF
chmod 755 "${PKGDIR}/DEBIAN/postinst"

echo "[4/5] 构建 deb..."
mkdir -p dist
dpkg-deb --build --root-owner-group "$PKGDIR" "dist/snapocr_${VERSION}_${ARCH}.deb"

echo "[5/5] 完成: dist/snapocr_${VERSION}_${ARCH}.deb"
echo "安装: sudo apt install ./dist/snapocr_${VERSION}_${ARCH}.deb  或  sudo dpkg -i ..."
