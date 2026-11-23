#!/bin/sh
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
V="$(mount | grep veracrypt_aux_mnt)"
if [ ! -z "$V" ]
then
	echo "Error: All LambCrypt volumes must be unmounted first." >&2
	exit 1
else
	exit 0
fi 