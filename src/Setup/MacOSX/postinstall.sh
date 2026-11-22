#!/bin/bash

if !([ -e "/usr/local/lib/libfuse.2.dylib" ])
then
	ln -s /usr/local/lib/libosxfuse.2.dylib /usr/local/lib/libfuse.2.dylib
fi

chmod -R go-w /Applications/LambCrypt.app

# Create a symlink to LambCrypt binary in /usr/local/bin
if !([ -e "/usr/local/bin/lambcrypt" ])
then
    ln -s /Applications/LambCrypt.app/Contents/MacOS/LambCrypt /usr/local/bin/lambcrypt
fi

exit 0
