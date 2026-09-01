# Third-party notices

## keycloak-js 26.2.4

The browser adapter expected at `/assets/keycloak.js` is **keycloak-js 26.2.4**,
from the Keycloak project, licensed under Apache License 2.0. Its source,
license, and release materials are available from the official Keycloak project:

- https://www.keycloak.org/downloads
- https://github.com/keycloak/keycloak-js
- https://www.apache.org/licenses/LICENSE-2.0

This repository intentionally does not redistribute the bundle. Follow
[`keycloak-js.manifest`](./keycloak-js.manifest) to download the pinned package
from an official Keycloak release, compare its SHA-256 with the published
checksum, and retain upstream notices when placing the verified browser module
at `web/assets/keycloak.js`.
