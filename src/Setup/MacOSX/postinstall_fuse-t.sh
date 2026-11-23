#!/bin/bash
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.

chmod -R go-w /Applications/LambCrypt.app

# Create a symlink to LambCrypt binary in /usr/local/bin
if !([ -e "/usr/local/bin/lambcrypt" ])
then
    ln -s /Applications/LambCrypt.app/Contents/MacOS/LambCrypt /usr/local/bin/lambcrypt
fi

exit 0
