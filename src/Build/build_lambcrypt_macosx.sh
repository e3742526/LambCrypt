#!/usr/bin/env bash
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.

#
# Copyright (c) 2013-2026 AM Crypto
# Governed by the Apache License 2.0 the full text of which is contained
# in the file License.txt included in VeraCrypt binary and source
# code distribution packages.
#

# Exit immediately if a command exits with a non-zero status
set -e

# Absolute path this script is in
SCRIPTPATH=$(cd "$(dirname "$0")" && pwd)
# source directory which contains the Makefile
SOURCEPATH=$(cd "$(dirname "$SCRIPTPATH/../.")" && pwd)
# directory where the LambCrypt project has been checked out
PARENTDIR=$(cd "$(dirname "$SCRIPTPATH/../../../.")" && pwd)

# Default wxWidgets version
DEFAULT_WX_VERSION="3.2.10"
WX_VERSION="$DEFAULT_WX_VERSION"

# Default macOS deployment target for both build paths
DEFAULT_OSX_TARGET="26.0"
OSX_TARGET=""

# Initialize flags
brew=false
package=false
sign_app=false

# Function to display usage information
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -b           Use Homebrew to build with precompiled packages"
    echo "  -s           Sign the local FSKit app and extension"
    echo "  -p           Sign the app and create a local installer package"
    echo "  -t <target>  Set the macOS deployment target (default: $DEFAULT_OSX_TARGET)"
    echo "  -v <version> Specify wxWidgets version (default: $DEFAULT_WX_VERSION)"
    echo "  -h           Display this help message"
    exit 1
}

# Parse command-line options
while getopts "bspflt:v:h" flag
do
    case "${flag}" in
        b) brew=true;;
        s) sign_app=true;;
        p) package=true;;
        f) echo "The -f option is retired. macOS builds use FSKit." >&2; exit 2;;
        l) ;; # All macOS builds are native now.
        t)
            if [ -z "$OPTARG" ]; then
                echo "Error: -t requires a target argument."
                usage
            fi
            OSX_TARGET=${OPTARG}
            ;;
        v)
            if [ -z "$OPTARG" ]; then
                echo "Error: -v requires a version argument."
                usage
            fi
            WX_VERSION=${OPTARG}
            ;;
        h) usage;;
        *) usage;;
    esac
done

export VC_OSX_TARGET=${OSX_TARGET:-$DEFAULT_OSX_TARGET}
export LOCAL_DEVELOPMENT_BUILD=true
export VC_OSX_SDK=$(xcrun --sdk macosx --show-sdk-version)

target=bundle
if [ "$package" = true ]; then
    target=package
elif [ "$sign_app" = true ]; then
    target=prepare
fi

echo "Building LambCrypt with FSKit using macOS SDK $VC_OSX_SDK and deployment target $VC_OSX_TARGET"

if [ "$brew" = true ]; then
    if ! command -v brew &> /dev/null; then
        echo "Homebrew is not installed. Please install Homebrew or run without the -b flag."
        exit 1
    fi

    WX_CONFIG="$(brew --prefix wxwidgets)/bin/wx-config"
    if [ ! -x "$WX_CONFIG" ]; then
        echo "Homebrew wxWidgets is missing. Install it with brew install wxwidgets." >&2
        exit 1
    fi
    make -C "$SOURCEPATH" WX_CONFIG="$WX_CONFIG" clean
    exec make -C "$SOURCEPATH" WX_CONFIG="$WX_CONFIG" "$target"
fi

# Check the condition of wxBuildConsole and wxWidgets-$WX_VERSION in the original PARENTDIR
if [ -d "$PARENTDIR/wxBuildConsole" ]; then
    echo "Using existing PARENTDIR: $PARENTDIR, wxBuildConsole is present."
elif [ -d "$PARENTDIR/wxWidgets-$WX_VERSION" ]; then
    echo "Using existing PARENTDIR: $PARENTDIR, wxWidgets-$WX_VERSION is present."
else
    # Change PARENTDIR to /tmp and check conditions again
    export PARENTDIR="/tmp"
    if [ -d "$PARENTDIR/wxBuildConsole" ]; then
        echo "Switched to PARENTDIR: /tmp, wxBuildConsole is present in /tmp."
    elif [ -d "$PARENTDIR/wxWidgets-$WX_VERSION" ]; then
        echo "Switched to PARENTDIR: /tmp, wxWidgets-$WX_VERSION is present in /tmp."
    else
        echo "Error: Neither wxBuildConsole nor wxWidgets-$WX_VERSION found in /tmp. Exiting."
        exit 1
    fi
fi

# /tmp is shared with other users: accept only entries owned by this user and
# create the directories the build writes to before anyone else can.
. "$SCRIPTPATH/Tools/private_tmp_dir.sh"
vc_secure_tmp_parentdir --existing "wxWidgets-$WX_VERSION" wxBuildConsole --create "wxBuild-$WX_VERSION" || exit 1

# The sources of wxWidgets $WX_VERSION must be extracted to the parent directory
export WX_ROOT="$PARENTDIR/wxWidgets-$WX_VERSION"

# this will be the temporary wxWidgets directory
export WX_BUILD_DIR="$PARENTDIR/wxBuild-$WX_VERSION"

cd "$SOURCEPATH"

echo "Building LambCrypt"
# Check if wx-config exists in WX_BUILD_DIR
if [ -L "${WX_BUILD_DIR}/wx-config" ]; then
    echo "wx-config already exists in ${WX_BUILD_DIR}. Skipping wxbuild."
else
    echo "Using wxWidgets sources in $WX_ROOT"
    make WXSTATIC=FULL wxbuild
fi
make WXSTATIC=FULL clean
make WXSTATIC=FULL "$target"

echo "LambCrypt build completed successfully."
