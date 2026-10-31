# Docker deployment

This application has previously been deployed on AWS EC2 according to its owner. Current infrastructure was not inspected during repository migration.

Use the [root setup guide](../README.md#docker-build-and-compose), [deployment compatibility notes](../deployment/README.md) and [asset provisioning](ASSETS.md). The supplied Compose retains the original local build, CPU limits, read-only mounts, healthcheck and results volume behavior.

Use `package_deploy.py --live` when a self-contained raw-imagery bundle is needed. The bundle is large, ignored by Git and must be written to a new path. It contains no private .env. `--live` means new inference over prepared imagery, not live acquisition. Legacy prediction-only bundles cannot serve the current interactive application.

Oracle ARM64 and registry/CI/CD instructions will be implemented and verified separately; see [branch plan](BRANCHING.md).
