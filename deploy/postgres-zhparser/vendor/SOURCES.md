# Vendored source provenance

The build host cannot reach GitHub or the SCWS project site directly, so these
two tarballs are vendored in this directory rather than fetched at build time
(see `../Dockerfile`). Checksums below were computed locally with
`shasum -a 256 <file>` and must match the files in this directory.

## scws-1.2.3.tar.bz2

- Upstream URL: http://www.xunsearch.com/scws/down/scws-1.2.3.tar.bz2
- SHA256: `60d50ac3dc42cff3c0b16cb1cfee47d8cb8c8baa142a58bc62854477b81f1af5`
- This is the official 1.2.3 release tarball, which ships a pre-generated
  `./configure` (avoids running `autoreconf` against a newer automake).

## zhparser.tar.gz

- Upstream URL: https://github.com/amutu/zhparser/archive/refs/heads/master.tar.gz
- SHA256: `0ab8b596c5e000002e9838077a7783a7bc97c4a8dbd1b7b9404435e27d62b181`
- This is an **undated `master` branch snapshot**, not a tagged release — the
  upstream project has no versioned releases, so the checksum above is the
  only way to verify which snapshot is vendored here and detect drift.
