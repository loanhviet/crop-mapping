# Optional native THEIA/GEODES acquisition

The default deployment uses prepared local imagery. Optional native `CROP_SOURCE=geodes` uses `imagery.GeodesProvider`, requires your own GEODES API key and authorized product access, and can download large complete scene ZIPs.

Set the key in a private .env or process environment; never commit it. Export native path/device settings before application import. Consult [.env.example](.env.example) and [architecture](docs/ARCHITECTURE.md).

The supplied Compose is not a live acquisition profile: source/device are explicitly prepared/cpu, data is mounted read-only, and /tmp is only 64 MiB. Merely editing CROP_SOURCE in .env does not change it. Source quotas, availability and acquisition latency were not checked during migration. GEODES tests use mocked HTTP and generated raster fixtures; they do not demonstrate successful current upstream acquisition.
