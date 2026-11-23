#!/bin/bash

# Never continue to an upload after a failed build or signing command.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" # Directory where the script is located
VARIANT=LambCrypt
DRY_RUN=false
if [[ "${1:-}" == --fskit ]]; then
    VARIANT=LambCrypt-FSKit
    shift
    if [[ "${1:-}" == --dry-run ]]; then
        DRY_RUN=true
        shift
    fi
fi
if [ "$#" -ne 0 ]; then
    echo "Usage: ${0##*/} [--fskit [--dry-run]]" >&2
    exit 2
fi

BUNDLE_PATH="${SCRIPT_DIR}/../../Main/$VARIANT.app"
TEAM_ID="${VC_SIGN_TEAM_ID:?Set VC_SIGN_TEAM_ID to your Apple signing team ID}"
SIGNING_ID="${VC_APP_SIGN_IDENTITY:?Set VC_APP_SIGN_IDENTITY to your Developer ID Application identity}"
INSTALLER_SIGNING_ID="${VC_INSTALLER_SIGN_IDENTITY:?Set VC_INSTALLER_SIGN_IDENTITY to your Developer ID Installer identity}"

# Set up credentials once: xcrun notarytool store-credentials "LambCrypt"
# Enter the Apple ID, app-specific password, and team ID at the interactive prompts.
# Credentials stay in Keychain; only the profile name is passed to notarytool.
# VC_NOTARY_KEYCHAIN optionally selects a custom Keychain containing the profile.
NOTARY_PROFILE="${VC_NOTARY_PROFILE:-LambCrypt}"
NOTARY_AUTH_ARGS=(--keychain-profile "$NOTARY_PROFILE")
if [ -n "${VC_NOTARY_KEYCHAIN:-}" ]; then
    NOTARY_AUTH_ARGS+=(--keychain "$VC_NOTARY_KEYCHAIN")
fi

fail() {
    echo "Error: $*" >&2
    exit 1
}

# Check every architecture, including the executables actually placed in the pkg.
verify_signature() {
    local bundle="$1"
    local executable="$2"
    local architectures architecture signature
    architectures=$(lipo -archs "$bundle/Contents/MacOS/$executable")
    [ -n "$architectures" ] || fail "No architectures found in $bundle"
    for architecture in $architectures; do
        signature=$(codesign --display --verbose=4 --arch "$architecture" "$bundle" 2>&1)
        if ! grep -Eq '^CodeDirectory .*flags=.*[(,]runtime[),]' <<< "$signature"; then
            fail "Hardened runtime is missing for $architecture in $bundle"
        fi
        if ! grep -Fxq "TeamIdentifier=$TEAM_ID" <<< "$signature"; then
            fail "Unexpected signing team for $architecture in $bundle"
        fi
        if ! grep -q '^Timestamp=' <<< "$signature"; then
            fail "Secure timestamp is missing for $architecture in $bundle"
        fi
        if ! grep -q '^Authority=Developer ID Application:' <<< "$signature"; then
            fail "Developer ID Application signature is missing for $architecture in $bundle"
        fi
    done
}

FSKIT_EXTENSION=Contents/Extensions/LambCryptFSKit.appex
FSKIT_PROFILE="$FSKIT_EXTENSION/Contents/embedded.provisionprofile"

verify_app() {
    local bundle="$1"
    if [[ "$VARIANT" == LambCrypt-FSKit ]]; then
        /bin/bash "$SCRIPT_DIR/verify_fskit_bundle.sh" --distribution "$bundle"
    else
        codesign --verify --deep --strict --verbose=2 "$bundle"
    fi
    verify_signature "$bundle" "$VARIANT"
    if [[ "$VARIANT" == LambCrypt-FSKit ]]; then
        verify_signature "$bundle/$FSKIT_EXTENSION" LambCryptFSKit
    fi
}

VC_BINARY="$BUNDLE_PATH/Contents/MacOS/$VARIANT"
[ -f "$VC_BINARY" ] || fail "LambCrypt executable not found: $VC_BINARY"

# Retrieve the version of LambCrypt from Info.plist
VC_VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "${BUNDLE_PATH}/Contents/Info.plist")
[ -n "$VC_VERSION" ] || fail "The app bundle has no version. Rebuild LambCrypt first."

if [[ "$VARIANT" == LambCrypt-FSKit ]]; then
    # The FSKit build signs the extension and app with different entitlements.
    # Preserve those signatures when packaging.
    verify_app "$BUNDLE_PATH"
    DMG_LABEL="LambCrypt-FSKit_${VC_VERSION}.dmg"
else
    DEPENDENCY_OUTPUT=$(otool -L "$VC_BINARY")
    PKGPROJ_FILE="${SCRIPT_DIR}/lambcrypt.pkgproj"
    DMG_LABEL="LambCrypt_${VC_VERSION}.dmg"
    if [[ "$DEPENDENCY_OUTPUT" == *libfuse-t.dylib* ]]; then
        echo "LambCrypt is linked against FUSE-T."
        PKGPROJ_FILE="${SCRIPT_DIR}/lambcrypt_fuse-t.pkgproj"
        DMG_LABEL="LambCrypt_FUSE-T_${VC_VERSION}.dmg"
    else
        echo "LambCrypt is linked against standard MacFUSE."
    fi

    PKG_VERSION=$(/usr/libexec/PlistBuddy -c "Print :PACKAGES:0:PACKAGE_SETTINGS:VERSION" "$PKGPROJ_FILE")
    PKG_NAME=$(/usr/libexec/PlistBuddy -c "Print :PROJECT:PROJECT_SETTINGS:NAME" "$PKGPROJ_FILE")
    if [ "$PKG_VERSION" != "$VC_VERSION" ] || [ "$PKG_NAME" != "LambCrypt $VC_VERSION" ]; then
        fail "Version mismatch: app is $VC_VERSION, package is $PKG_VERSION ($PKG_NAME). Rebuild LambCrypt and update the package project before notarizing."
    fi
fi

# Check credentials before modifying the app or building the installer.
if ! $DRY_RUN; then
    echo "Checking notarization credentials in Keychain profile: $NOTARY_PROFILE"
    if ! xcrun notarytool history "${NOTARY_AUTH_ARGS[@]}" --output-format json > /dev/null; then
        fail "Cannot authenticate with Keychain profile '$NOTARY_PROFILE'. Set it up using 'xcrun notarytool store-credentials', or check Keychain access and network connectivity."
    fi
fi

# Isolate all generated files so that an earlier installer can never be submitted.
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/lambcrypt-notarize.XXXXXX")
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -eq 0 ]; then
        rm -rf "$WORK_DIR"
    else
        echo "Notarization failed. Working files and logs retained in: $WORK_DIR" >&2
    fi
    exit "$status"
}
trap cleanup EXIT

if [[ "$VARIANT" == LambCrypt-FSKit ]]; then
    UNSIGNED_PKG_PATH="$WORK_DIR/unsigned.pkg"
    productbuild --component "$BUNDLE_PATH" /Applications "$UNSIGNED_PKG_PATH"
else
    xattr -rc "$BUNDLE_PATH"
    codesign --timestamp --options runtime --deep --force --entitlements "${SCRIPT_DIR}/LambCrypt.entitlements.plist" --sign "$SIGNING_ID" "$BUNDLE_PATH"
    verify_app "$BUNDLE_PATH"
    /usr/local/bin/packagesbuild --build-folder "$WORK_DIR" "$PKGPROJ_FILE"
    UNSIGNED_PKG_PATH="$WORK_DIR/$PKG_NAME.pkg"
fi
[ -f "$UNSIGNED_PKG_PATH" ] || fail "Package build did not produce $UNSIGNED_PKG_PATH"
PKG_PATH="$WORK_DIR/${VARIANT}_${VC_VERSION}.pkg"
productsign --sign "$INSTALLER_SIGNING_ID" --timestamp "$UNSIGNED_PKG_PATH" "$PKG_PATH"
pkgutil --check-signature "$PKG_PATH"

# Validate the payload, not just the source bundle or the installer signature.
pkgutil --expand-full "$PKG_PATH" "$WORK_DIR/expanded"
if [[ "$VARIANT" == LambCrypt-FSKit ]]; then
    BUNDLE_ID=$(plutil -extract CFBundleIdentifier raw -o - "$BUNDLE_PATH/Contents/Info.plist")
    PACKAGED_BUNDLE="$WORK_DIR/expanded/$BUNDLE_ID.pkg/Payload/$VARIANT.app"
    for file in "$FSKIT_PROFILE" "$FSKIT_EXTENSION/Contents/Info.plist" "$FSKIT_EXTENSION/Contents/MacOS/LambCryptFSKit"; do
        cmp "$BUNDLE_PATH/$file" "$PACKAGED_BUNDLE/$file" ||
            fail "The packaged FSKit extension differs from the signed extension at $file."
    done
else
    PACKAGED_BUNDLE="$WORK_DIR/expanded/lambcrypt.pkg/Payload/Applications/LambCrypt.app"
fi
cmp "$VC_BINARY" "$PACKAGED_BUNDLE/Contents/MacOS/$VARIANT" || fail "The packaged executable differs from the signed app."
cmp "$BUNDLE_PATH/Contents/Info.plist" "$PACKAGED_BUNDLE/Contents/Info.plist" || fail "The packaged Info.plist differs from the signed app."
verify_app "$PACKAGED_BUNDLE"

if $DRY_RUN; then
    echo "Verified the signed FSKit installer and its payload. Dry run complete."
    exit 0
fi

# Upload only the newly built, verified package.
RESULT_PATH="$WORK_DIR/notarization_result.json"
STATUS_PATH="$WORK_DIR/notarization_status.json"
LOG_PATH="$WORK_DIR/notarization_log.json"
echo "Uploading PKG to Apple for notarization..."
if ! xcrun notarytool submit "$PKG_PATH" "${NOTARY_AUTH_ARGS[@]}" --wait --output-format json > "$RESULT_PATH"; then
    cat "$RESULT_PATH"
    fail "Failed to submit PKG for notarization."
fi

REQUEST_UUID=$(plutil -extract id raw -expect string -o - "$RESULT_PATH")
STATUS=$(plutil -extract status raw -expect string -o - "$RESULT_PATH")
[ -n "$REQUEST_UUID" ] || fail "Notarization returned an empty request UUID."
echo "Notarization Request UUID: $REQUEST_UUID"
echo "Initial status: $STATUS"

while [[ "$STATUS" == [Ii]n\ [Pp]rogress ]]; do
    sleep 30
    xcrun notarytool info "$REQUEST_UUID" "${NOTARY_AUTH_ARGS[@]}" --output-format json > "$STATUS_PATH"
    STATUS=$(plutil -extract status raw -expect string -o - "$STATUS_PATH")
    echo "Current status: $STATUS"
done

if [ "$STATUS" != "Accepted" ]; then
    echo "Notarization failed. Retrieving log for more details..."
    if xcrun notarytool log "$REQUEST_UUID" "${NOTARY_AUTH_ARGS[@]}" --output-format json > "$LOG_PATH"; then
        cat "$LOG_PATH"
    fi
    fail "Notarization status: $STATUS"
fi

echo "Stapling the notarization ticket to the pkg..."
xcrun stapler staple "$PKG_PATH"
xcrun stapler validate "$PKG_PATH"

echo "Creating the distribution DMG..."
mkdir "$WORK_DIR/dmg"
cp "$PKG_PATH" "$WORK_DIR/dmg/LambCrypt_Installer.pkg"
hdiutil create -quiet -format UDZO -imagekey zlib-level=9 -volname LambCrypt \
    -srcfolder "$WORK_DIR/dmg" "$WORK_DIR/$DMG_LABEL"
codesign -s "$SIGNING_ID" --timestamp "$WORK_DIR/$DMG_LABEL"
codesign --verify --verbose=2 "$WORK_DIR/$DMG_LABEL"

# Replace release outputs only after notarization and DMG creation both succeed.
mv -f "$PKG_PATH" "$SCRIPT_DIR/${VARIANT}_${VC_VERSION}.pkg"
mv -f "$WORK_DIR/$DMG_LABEL" "$SCRIPT_DIR/$DMG_LABEL"
echo "Notarization completed: $SCRIPT_DIR/$DMG_LABEL"

exit 0
