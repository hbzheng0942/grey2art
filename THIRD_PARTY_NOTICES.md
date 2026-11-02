# Third-party notices

## Noto Sans CJK SC documentation font

The current Grey2Art overview uses a 46 KB WOFF2 subset of Noto Sans CJK SC
2.004, Copyright 2014–2021 Adobe, under the SIL Open Font License 1.1.
The subset covers both overview languages and printable ASCII, and its internal
family is renamed `Grey2Art Sans`. It contains the static regular weight;
headings use browser-synthesized semibold. The original font remains in its
owning game package rather than being copied into this repository.

The complete [copyright and license](docs/demo/fonts/NotoSansCJKsc-OFL.txt),
[source and hashes](docs/demo/fonts/noto-source.json), and
[subset character list](docs/demo/fonts/showcase-characters.txt) are retained.
This font is used for documentation artwork outside the installable Skill package.

## Departure Mono historical documentation font

Earlier Grey2Art overview revisions used Departure Mono 1.500 by Helena Zhang, licensed under
the SIL Open Font License 1.1. The unmodified font, full copyright/license and
pinned upstream source hashes are retained in [documentation fonts](docs/demo/fonts/OFL.txt)
and [source record](docs/demo/fonts/source.json). This font is used for documentation
artwork and is outside the installable Skill package.

## Aholo-Lux3D minimal runtime

- Upstream: https://github.com/manycore-research/Aholo-Lux3D
- Pinned commit: `81c495ad0f01784b3d86f8d5b4a97558e80a78ca`
- Upstream version: `1.2.0`
- License: MIT, Copyright (c) 2026 Manycore Research.
- Bundled license: [LICENSE](skills/greybox-to-multistyle-art/runtime/vendor/aholo-lux3d/LICENSE).
- Selected files, original paths and integrity hashes: [vendor manifest](skills/greybox-to-multistyle-art/runtime/vendor/manifest.json).

The vendored selection provides provider runtime/contracts and private runtime setup. It does not include credentials or grant authorization to invoke paid services. Provider services, engines and external tools retain their own applicable terms.

## Project materials and demonstrations

Original project code, Skill instructions and documentation are licensed under
the [MIT License](LICENSE). The installable package includes the same project
license in its root. The contributor attribution identifies this project's
contributions; it does not transfer ownership or replace upstream notices.

The pinned Lux selection retains its own MIT copyright notice and integrity
manifest. Engines, tools, service accounts and remotely generated outputs retain
their applicable licenses and service terms.

Demo game repositories and linked screenshots/videos are credited in
[demo provenance](docs/demo/PROVENANCE.md). This project's MIT license does not
grant additional rights to their models, textures, music, fonts or other media.
The maintainer has authorized this curated display in Grey2Art documentation. This grants no additional right to redistribute the games or reuse their media and assets.
