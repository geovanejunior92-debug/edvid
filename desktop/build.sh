#!/bin/bash
set -euo pipefail
source_dir="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$source_dir/build}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
bundle="$out/Edvid Studio.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
swiftc -module-cache-path "$out/swift-module-cache" "$source_dir/EdvidStudio.swift" -o "$bundle/Contents/MacOS/EdvidStudio" -framework Cocoa -framework WebKit
cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>EdvidStudio</string>
<key>CFBundleIdentifier</key><string>com.geovanejunior.edvidstudio</string>
<key>CFBundleName</key><string>Edvid Studio</string>
<key>CFBundleDisplayName</key><string>Edvid Studio</string>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
xattr -cr "$bundle"
codesign --force --sign - "$bundle"
codesign --verify --strict "$bundle"
echo "$bundle"
