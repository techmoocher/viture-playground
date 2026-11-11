#!/bin/sh
# Build native/build/capture_shim.dll with MinGW-w64 (run inside WSL).
#
#   From the repository root in Windows:  wsl sh native/build_shim.sh
#   Inside WSL:                          sh native/build_shim.sh
#
# Requires (one-time, in WSL): sudo apt install gcc-mingw-w64-x86-64
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/build"
CC=${CC:-x86_64-w64-mingw32-gcc}
mkdir -p "$OUT"
"$CC" -std=c11 -O2 -Wall -Wextra -Werror -shared "$HERE/capture_shim.c" -o "$OUT/capture_shim.dll" -static-libgcc
{
  echo "compiler: $("$CC" --version | head -n 1)"
  echo "flags: -std=c11 -O2 -Wall -Wextra -Werror -shared -static-libgcc"
  echo "source_sha256: $(sha256sum "$HERE/capture_shim.c" | cut -d' ' -f1)"
  echo "dll_sha256: $(sha256sum "$OUT/capture_shim.dll" | cut -d' ' -f1)"
  echo "imports: $(x86_64-w64-mingw32-objdump -p "$OUT/capture_shim.dll" | sed -n 's/.*DLL Name: //p' | tr '\n' ' ')"
} > "$OUT/BUILDINFO.txt"
cat "$OUT/BUILDINFO.txt"
