#!/bin/sh
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
#
# Copyright (c) 2013-2026 AM Crypto
# Governed by the Apache License 2.0 the full text of which is contained
# in the file License.txt included in VeraCrypt binary and source
# code distribution packages.
#

# Errors should cause script to exit
set -e

# Deterministic umask: dpkg-deb records the mode of the temporary ar
# members (debian-binary, control.tar.gz, data.tar.gz) it creates, so a
# caller umask of 027 yields 0640 where 022 yields 0644 and the .deb is
# not reproducible. Pin it for the whole packaging run.
umask 022

# Absolute path to this script
export SCRIPT=$(readlink -f "$0")
# Absolute path this script is in
export SCRIPTPATH=$(dirname "$SCRIPT")
# Source directory which contains the Makefile
export SOURCEPATH=$(readlink -f "$SCRIPTPATH/..")
# Directory where the LambCrypt has been checked out
export PARENTDIR=$(readlink -f "$SCRIPTPATH/../../..")

# Compute and export SOURCE_DATE_EPOCH so cmake/cpack inherit it (they get
# an empty env from this shell otherwise). Precedence: caller, git HEAD,
# Common/Tcdefs.h release date.
if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
    SOURCE_DATE_EPOCH=$(sh "$SOURCEPATH/Build/Tools/source_date_epoch.sh" "$SOURCEPATH") || {
        echo "Error: SOURCE_DATE_EPOCH must be set, derivable from git, or derivable from Common/Tcdefs.h release date" >&2
        exit 1
    }
fi
case "$SOURCE_DATE_EPOCH" in
    ''|*[!0-9]*)
        echo "Error: SOURCE_DATE_EPOCH must be a non-negative Unix timestamp" >&2
        exit 1
        ;;
esac
export SOURCE_DATE_EPOCH

# Check the condition of wxBuildConsole and wxWidgets-3.2.5 in the original PARENTDIR
if [ -d "$PARENTDIR/wxBuildConsole" ]; then
    echo "Using existing PARENTDIR: $PARENTDIR, wxBuildConsole is present."
elif [ -d "$PARENTDIR/wxWidgets-3.2.5" ]; then
    echo "Using existing PARENTDIR: $PARENTDIR, wxWidgets-3.2.5 is present."
else
    # Change PARENTDIR to /tmp and check conditions again
    export PARENTDIR="/tmp"
    if [ -d "$PARENTDIR/wxBuildConsole" ]; then
        echo "Switched to PARENTDIR: /tmp, wxBuildConsole is present in /tmp."
    elif [ -d "$PARENTDIR/wxWidgets-3.2.5" ]; then
        echo "Switched to PARENTDIR: /tmp, wxWidgets-3.2.5 is present in /tmp."
    else
        echo "Error: Neither wxBuildConsole nor wxWidgets-3.2.5 found in /tmp. Exiting."
        exit 1
    fi
fi

# /tmp is shared with other users: accept only entries owned by this user and
# create the directories the build writes to before anyone else can.
. "$SCRIPTPATH/Tools/private_tmp_dir.sh"
vc_secure_tmp_parentdir --existing wxWidgets-3.2.5 --create wxBuildConsole wxBuildGUI LambCrypt_Setup LambCrypt_Packaging || exit 1

# The sources of wxWidgets 3.2.5 must be extracted to the parent directory
export WX_ROOT=$PARENTDIR/wxWidgets-3.2.5

cd $SOURCEPATH

# Detect requested FUSE version (defaults to FUSE2). Can be set via WITHFUSE3=1 or by passing FUSE3/--with-fuse3.
build_with_fuse3=0
if [ -n "$WITHFUSE3" ] && [ "$WITHFUSE3" != "0" ]; then
    build_with_fuse3=1
fi

preserved_args=""
while [ $# -gt 0 ]; do
    case "$1" in
        FUSE3|WITHFUSE3|--with-fuse3)
            build_with_fuse3=1
            ;;
        FUSE2|WITHFUSE2|--with-fuse2)
            build_with_fuse3=0
            ;;
        WXSTATIC|INDICATOR)
            if [ -z "$preserved_args" ]; then
                preserved_args="$1"
            else
                preserved_args="$preserved_args $1"
            fi
            ;;
        *)
            echo "Warning: Unrecognized option '$1' (ignored)" >&2
            ;;
    esac
    shift
done

set --
if [ -n "$preserved_args" ]; then
    for arg in $preserved_args; do
        set -- "$@" "$arg"
    done
fi

if [ "$build_with_fuse3" = "1" ]; then
    FUSE3_MAKE_FLAG="WITHFUSE3=1"
    FUSE3_CMAKE_FLAG="-DVC_WITH_FUSE3=TRUE"
    echo "Building LambCrypt packages against FUSE3"
else
    FUSE3_MAKE_FLAG=""
    FUSE3_CMAKE_FLAG="-DVC_WITH_FUSE3=FALSE"
    echo "Building LambCrypt packages against FUSE2"
fi

build_and_install() {
    target=$1
    wxstatic=$2
    indicator=$3
    nogui=""

    # Determine wxWidgets build directory based on target
    if [ "$target" = "Console" ]; then
        export WX_BUILD_DIR="$PARENTDIR/wxBuildConsole"
        nogui="NOGUI=1"
    else
        export WX_BUILD_DIR="$PARENTDIR/wxBuildGUI"
    fi

    wxstatic_value=""
    if [ "$wxstatic" = "WXSTATIC" ]; then
        wxstatic_value="WXSTATIC=1"
        # Check if wx-config exists in WX_BUILD_DIR
        if [ -L "${WX_BUILD_DIR}/wx-config" ]; then
            echo "wx-config already exists in ${WX_BUILD_DIR}. Skipping wxbuild."
        else
            echo "Using wxWidgets sources in $WX_ROOT"
            make $wxstatic_value $nogui $FUSE3_MAKE_FLAG wxbuild || exit 1
        fi
    fi

    indicator_value=""
    if [ "$indicator" = "INDICATOR" ]; then
        indicator_value="INDICATOR=1"
    fi

    rm -rf "$PARENTDIR/LambCrypt_Setup/$target"
    make $wxstatic_value $indicator_value $nogui $FUSE3_MAKE_FLAG clean || exit 1
    make $wxstatic_value $indicator_value $nogui $FUSE3_MAKE_FLAG || exit 1
    make $wxstatic_value $indicator_value $nogui $FUSE3_MAKE_FLAG install DESTDIR="$PARENTDIR/LambCrypt_Setup/$target" || exit 1
}

# Handle arguments
case "$1$2" in
"WXSTATIC")
    echo "Building GUI version of LambCrypt for DEB using wxWidgets static libraries"
    build_and_install "GUI" "WXSTATIC" ""
    ;;
"INDICATOR")
    echo "Building GUI version of LambCrypt for DEB using system wxWidgets and indicator"
    build_and_install "GUI" "" "INDICATOR"
    ;;
"WXSTATICINDICATOR"|"INDICATORWXSTATIC")
    echo "Building GUI version of LambCrypt for DEB using wxWidgets static libraries and indicator"
    build_and_install "GUI" "WXSTATIC" "INDICATOR"
    ;;
*)
    echo "Building GUI version of LambCrypt for DEB using system wxWidgets"
    build_and_install "GUI" "" ""
    ;;
esac

echo "Building console version of LambCrypt for DEB using wxWidgets static libraries"
build_and_install "Console" "WXSTATIC" ""

echo "Creating LambCrypt DEB packages"

# -DCPACK_RPM_PACKAGE_DEBUG=TRUE for debugging cpack DEB
# -DCPACK_RPM_PACKAGE_DEBUG=TRUE for debugging cpack DEB

# remove old packages
rm -rf "$PARENTDIR/LambCrypt_Packaging"
vc_secure_tmp_parentdir --create LambCrypt_Packaging || exit 1

mkdir -p $PARENTDIR/LambCrypt_Packaging/GUI
mkdir -p $PARENTDIR/LambCrypt_Packaging/Console

cmake -H$SCRIPTPATH -B$PARENTDIR/LambCrypt_Packaging/GUI -DLAMBCRYPT_BUILD_DIR="$PARENTDIR/LambCrypt_Setup/GUI" -DNOGUI=FALSE -DSOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH $FUSE3_CMAKE_FLAG || exit 1
cpack --config $PARENTDIR/LambCrypt_Packaging/GUI/CPackConfig.cmake || exit 1

cmake -H$SCRIPTPATH -B$PARENTDIR/LambCrypt_Packaging/Console -DLAMBCRYPT_BUILD_DIR="$PARENTDIR/LambCrypt_Setup/Console" -DNOGUI=TRUE -DSOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH $FUSE3_CMAKE_FLAG || exit 1
cpack --config $PARENTDIR/LambCrypt_Packaging/Console/CPackConfig.cmake || exit 1
