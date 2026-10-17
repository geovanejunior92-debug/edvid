#!/bin/bash
set -euo pipefail
source_dir="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$source_dir/build}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
bundle="$out/Edvid Studio.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
# alvo fixo: sem ele o swiftc de uma Xcode beta marca "minos" mais novo que o
# macOS instalado e o Finder recusa abrir (erro -10825, visto em 2026-10-17)
min_macos="${EDVID_MIN_MACOS:-14.0}"
swiftc -target "$(uname -m)-apple-macos$min_macos" -module-cache-path "$out/swift-module-cache" "$source_dir/EdvidStudio.swift" -o "$bundle/Contents/MacOS/EdvidStudio" -framework Cocoa -framework WebKit
cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>EdvidStudio</string>
<key>CFBundleIdentifier</key><string>com.geovanejunior.edvidstudio</string>
<key>CFBundleName</key><string>Edvid Studio</string>
<key>CFBundleDisplayName</key><string>Edvid Studio</string>
<key>CFBundleVersion</key><string>3</string>
<key>CFBundleShortVersionString</key><string>0.3.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
xattr -cr "$bundle"
codesign --force --sign - "$bundle"
codesign --verify --strict "$bundle"
echo "$bundle"
