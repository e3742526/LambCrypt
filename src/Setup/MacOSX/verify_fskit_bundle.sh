#!/bin/bash
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0, the full text of which is contained in
# the file License.txt included in LambCrypt binary and source code
# distribution packages.

set -euo pipefail

distribution=false
if [[ "${1:-}" == --distribution ]]; then
    distribution=true
    shift
fi
if [[ "$#" -ne 1 ]]; then
    echo "Usage: ${0##*/} [--distribution] /path/to/LambCrypt-FSKit.app" >&2
    exit 2
fi

fail() {
    echo "Error: $*" >&2
    exit 1
}

plist_value() {
    plutil -extract "$1" raw -o - "$2"
}

entitlement() {
    /usr/libexec/PlistBuddy -c "Print :$1" "$2"
}

bundle="$1"
extension="$bundle/Contents/Extensions/LambCryptFSKit.appex"
app_info="$bundle/Contents/Info.plist"
extension_info="$extension/Contents/Info.plist"
profile="$extension/Contents/embedded.provisionprofile"
app_id=io.github.e3742526.LambCrypt.fskit
extension_id="$app_id.module"
[[ -f "$profile" ]] || fail "The FSKit extension is missing its provisioning profile."
[[ "$(plist_value CFBundleIdentifier "$app_info")" == "$app_id" &&
   "$(plist_value CFBundleIdentifier "$extension_info")" == "$extension_id" ]] ||
    fail "Unexpected FSKit app or extension bundle identifier."
[[ "$(plist_value CFBundleDocumentTypes.0.LSHandlerRank "$app_info")" == Alternate ]] ||
    fail "The FSKit bundle must use the Alternate document handler rank for side-by-side installs."
[[ "$(plist_value EXAppExtensionAttributes.EXExtensionPointIdentifier "$extension_info")" == com.apple.fskit.fsmodule &&
   "$(plist_value EXAppExtensionAttributes.FSShortName "$extension_info")" == lambcryptfs &&
   "$(plist_value EXAppExtensionAttributes.FSSupportsPathURLs "$extension_info")" == true &&
   "$(plist_value EXAppExtensionAttributes.FSSupportsBlockResources "$extension_info")" == false &&
   "$(plist_value EXAppExtensionAttributes.FSRequiresSecurityScopedPathURLResources "$extension_info")" == true ]] ||
    fail "The FSKit extension has incorrect path-resource declarations."

for key in CFBundleVersion CFBundleShortVersionString LSMinimumSystemVersion; do
    expected=$(plist_value "$key" "$app_info")
    [[ -n "$expected" && "$(plist_value "$key" "$extension_info")" == "$expected" ]] ||
        fail "The FSKit app and extension must agree on $key."
done
minimum=$(plist_value LSMinimumSystemVersion "$app_info")
[[ "$minimum" =~ ^([0-9]+)\.[0-9]+(\.[0-9]+)?$ ]] && (( 10#${BASH_REMATCH[1]} >= 26 )) ||
    fail "The FSKit minimum deployment target must be macOS 26 or later."
for executable in "$bundle/Contents/MacOS/LambCrypt-FSKit" "$extension/Contents/MacOS/LambCryptFSKit"; do
    [[ "$(lipo -archs "$executable")" == arm64 ]] ||
        fail "The FSKit app and extension must be native arm64."
    target=$(xcrun vtool -show-build "$executable" |
        awk '$1 == "platform" {platform = $2} $1 == "minos" && platform == "MACOS" {print $2}')
    [[ "$target" == "$minimum" || "$target.0" == "$minimum" || "$target" == "$minimum.0" ]] ||
        fail "The FSKit executable deployment target differs from its bundle metadata."
    dependencies=$(otool -L "$executable")
    if grep -Eiq '/(lib(fuse|osxfuse|macfuse)[^/[:space:]]*\.dylib|(fuse-t|macfuse|osxfuse)\.framework/)' <<< "$dependencies"; then
        fail "The FSKit executable links a third-party FUSE library: $executable"
    fi
done

codesign --verify --deep --strict "$bundle"
work=$(mktemp -d "${TMPDIR:-/tmp}/lambcrypt-verify-fskit.XXXXXX")
trap 'rm -f "$work/profile.plist" "$work/entitlements.plist"; rmdir "$work"' EXIT
security cms -D -i "$profile" -o "$work/profile.plist" 2>/dev/null ||
    fail "The embedded FSKit profile could not be decoded."
if $distribution && [[ "$(plist_value ProvisionsAllDevices "$work/profile.plist" 2>/dev/null)" != true ]]; then
    fail "Prepare the FSKit app with a Developer ID distribution profile."
fi
team=$(entitlement Entitlements:com.apple.developer.team-identifier "$work/profile.plist" 2>/dev/null || true)
profile_id=$(entitlement Entitlements:com.apple.application-identifier "$work/profile.plist" 2>/dev/null || true)
[[ -n "$team" && "${profile_id#*.}" == "$extension_id" &&
   "$(entitlement Entitlements:com.apple.developer.fskit.fsmodule "$work/profile.plist" 2>/dev/null)" == true ]] ||
    fail "The profile must authorize the exact FSKit module identifier."

for component in "$bundle" "$extension"; do
    signature=$(codesign --display --verbose=4 "$component" 2>&1)
    grep -Fxq "TeamIdentifier=$team" <<< "$signature" ||
        fail "The FSKit code-signing team differs from the embedded profile."
    codesign --display --entitlements - --xml "$component" > "$work/entitlements.plist" 2>/dev/null
    [[ "$(entitlement com.apple.security.application-groups:0 "$work/entitlements.plist" 2>/dev/null)" == "$team.lambcrypt-fskit" ]] ||
        fail "The app and extension must use the provisioned FSKit App Group."
done
[[ "$(entitlement com.apple.application-identifier "$work/entitlements.plist" 2>/dev/null)" == "$profile_id" &&
   "$(entitlement com.apple.developer.fskit.fsmodule "$work/entitlements.plist" 2>/dev/null)" == true &&
   "$(entitlement com.apple.security.app-sandbox "$work/entitlements.plist" 2>/dev/null)" == true &&
   "$(plist_value LambCryptFSKitIPCGroup "$app_info")" == "$team.lambcrypt-fskit" ]] ||
    fail "The app or extension FSKit metadata and entitlements disagree with its profile."

echo "Verified FSKit arm64 bundle metadata, FUSE-free linkage, signatures, App Group and provisioning."
