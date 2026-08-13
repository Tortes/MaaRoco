# Pinned MaaFramework Runtime

The complete Windows x86-64 runtime is published from
`Tortes/MaaFramework@d6381bd76171647463d62358f6fed01f2a613d79` as release
`maaroco-d6381bd7`. The commit is based on MaaFramework v5.11.0 and adds
`RandomDelay`, configurable click duration, Interception keyboard input, and
Interception `RelativeMoveInput` support.

The archive and key DLL SHA-256 values are recorded in
`maaframework.lock.json`. The release workflow verifies all of them before
packaging so an official MaaFramework core cannot be mixed with the custom
control unit. `win-x86_64/MaaWin32ControlUnit.dll` is retained only as a local
reference copy; release packaging uses the complete pinned runtime archive.
