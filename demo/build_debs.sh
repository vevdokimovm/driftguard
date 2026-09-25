#!/bin/sh
# Собирает два крошечных пакета demo-tool (1.0 и 1.1) без сети: на них сценарий показывает дрейф версии пакета.
set -e
out=${1:-/opt/debs}
mkdir -p "$out"
for version in 1.0 1.1; do
  root=$(mktemp -d)
  mkdir -p "$root/DEBIAN" "$root/usr/local/bin"
  printf 'Package: demo-tool\nVersion: %s\nArchitecture: all\nMaintainer: DriftGuard demo\nDescription: demo package\n' \
    "$version" > "$root/DEBIAN/control"
  printf '#!/bin/sh\necho demo-tool %s\n' "$version" > "$root/usr/local/bin/demo-tool"
  chmod 0755 "$root/usr/local/bin/demo-tool"
  dpkg-deb --build --root-owner-group "$root" "$out/demo-tool_${version}_all.deb" >/dev/null
  rm -rf "$root"
done
