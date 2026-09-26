# Lunar OS

Arch Linux's official ISO profile (`releng`), with Lunar OS branding and the
`lunaros-setup` installer. Nothing else.

    lunar/apply.sh      every change made to the upstream profile, numbered
    lunar-setup/        the installer
    .github/workflows/  builds the ISO and publishes it as a release

Changes are added to `lunar/apply.sh` one at a time. Each build is tested on
real hardware before the next change goes in, so a failure always points at
the most recent step.
