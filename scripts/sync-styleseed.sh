#!/usr/bin/env bash
# Sync styleseed engine + linear skin into web/
set -e
STYLESEED="/home/pi/app/jupyterLab/notebooks/styleseed"
WEB="$(dirname "$0")/../web"

mkdir -p "$WEB/engine/components/ui" "$WEB/engine/components/patterns" \
         "$WEB/engine/css" "$WEB/engine/utils" "$WEB/skins/linear"

cp -r "$STYLESEED/engine/css/"*.css         "$WEB/engine/css/"
cp    "$STYLESEED/engine/tokens.ts"          "$WEB/engine/"
cp -r "$STYLESEED/engine/components/ui/"    "$WEB/engine/components/ui/"
cp -r "$STYLESEED/engine/components/patterns/" "$WEB/engine/components/patterns/"
cp -r "$STYLESEED/engine/utils/"*           "$WEB/engine/utils/" 2>/dev/null || true
cp    "$STYLESEED/skins/linear/theme.css"   "$WEB/skins/linear/"
cp    "$STYLESEED/skins/linear/skin.json"   "$WEB/skins/linear/" 2>/dev/null || true

echo "styleseed synced to $WEB"
