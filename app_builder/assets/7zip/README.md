# Vendored 7-Zip runtime

This directory contains the 7-Zip console runtime used when
`installer.payload_format: 7z` is selected.

The files were carried forward from the app-builder `0.x` branch:

- `7z.exe`
  - SHA256: `6B95E76BBE2147BDC6B0DEBBD28FD45EF160175FA22762F64FFDB0025E75E9E6`
- `7z.dll`
  - SHA256: `84D2BCF774ABA77E938D3F36BFE020E0D49CFB3074AD9DE69B5AF78054602B7E`

They are included in generated installer top layers only for 7z payload
installers. ZIP payload installers do not carry these files.

7-Zip is distributed under the 7-Zip license. If these binaries are replaced,
record the source version, hashes, and run the 7z asset and installer tests.
