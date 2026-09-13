# Official MaaFramework Runtime

MaaRoco uses the complete official `MaaXYZ/MaaFramework` v5.13.0 Windows
x86-64 release. `maaframework.lock.json` records its source commit, archive
digest and DLL hashes. CI verifies these before packaging. Do not overlay
individual DLLs from the previous custom runtime.

Throw tasks use official `LongPress` and `DoNothing` with fixed delays.
Interception relative mouse movement uses the bundled Python driver binding,
because the official Interception backend does not implement RelativeMoveInput.

The Interception keyboard selection fix is maintained separately on official
main in `MaaFramework`, branch `fix/official-interception-device-selection`.
It is not part of the official v5.13.0 binaries. The battle keyboard workaround
remains until an official release includes the framework fix.
