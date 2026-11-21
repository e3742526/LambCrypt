#!/bin/sh
#
# Copyright (c) 2013-2026 AM Crypto
# Governed by the Apache License 2.0 the full text of which is contained
# in the file License.txt included in VeraCrypt binary and source
# code distribution packages.
#
# Sourced by the build scripts. When wxWidgets is not found next to the
# checkout they fall back to PARENTDIR=/tmp, which every local user can write
# to. Another user could then plant a wxWidgets tree or build directory that
# is compiled into the release binaries, or a packaging directory whose
# contents end up in the packages. These helpers only accept /tmp entries that
# belong to the user running the build, and create the ones the build writes
# so nobody else can create them first.

# vc_private_dir DIR [create]
# DIR must be a real directory (not a symbolic link) owned by the current
# user and not writable by group or others. With "create", a missing DIR is
# created with mode 0755; mkdir fails rather than reuse anything another user
# creates in the meantime.
vc_private_dir() {
	vc_dir=$1
	if [ "$2" = "create" ] && [ ! -e "$vc_dir" ] && [ ! -L "$vc_dir" ]; then
		mkdir -m 0755 "$vc_dir" 2>/dev/null || true
	fi
	if [ -L "$vc_dir" ] || [ ! -d "$vc_dir" ]; then
		echo "Error: $vc_dir is not a directory." >&2
		return 1
	fi
	if [ ! -O "$vc_dir" ]; then
		echo "Error: $vc_dir is not owned by the current user." >&2
		return 1
	fi
	if [ -n "$(find "$vc_dir" -prune \( -perm -020 -o -perm -002 \) -print)" ]; then
		echo "Error: $vc_dir is writable by other users." >&2
		return 1
	fi
	return 0
}

# vc_secure_tmp_parentdir [--existing NAME...] [--create NAME...]
# Does nothing unless PARENTDIR is /tmp. --existing entries are checked only if
# present (wxWidgets sources the user extracted); --create entries are checked
# or created (directories the build writes to).
vc_secure_tmp_parentdir() {
	case "$PARENTDIR" in
		/tmp|/tmp/|/private/tmp|/private/tmp/) ;;
		*) return 0 ;;
	esac
	vc_mode=existing
	for vc_name in "$@"; do
		case "$vc_name" in
			--existing) vc_mode=existing ;;
			--create) vc_mode=create ;;
			*)
				if [ "$vc_mode" = "create" ]; then
					vc_private_dir "$PARENTDIR/$vc_name" create || return 1
				elif [ -e "$PARENTDIR/$vc_name" ] || [ -L "$PARENTDIR/$vc_name" ]; then
					vc_private_dir "$PARENTDIR/$vc_name" || return 1
				fi
				;;
		esac
	done
	return 0
}
