#!/bin/sh
set -eu

SRC_DIR="$1"
BUILD_TARGET="$2"

# Import project into workspace
stm32cubeide --launcher.suppressErrors -nosplash -application org.eclipse.cdt.managedbuilder.core.headlessbuild -data /tmp/stm-workspace -importAll "$SRC_DIR"

# Build with Bear to generate compile_commands.json
CCDB_OUT="$SRC_DIR/compile_commands.json"
echo "Building with Bear to generate compile_commands.json..."
bear --append --output "$CCDB_OUT" -- headless-build.sh -data /tmp/stm-workspace -build "$BUILD_TARGET"

if [ -f "$CCDB_OUT" ]; then
  echo "✅ Generated compile_commands.json at: $CCDB_OUT"
else
  echo "⚠️ compile_commands.json was not generated"
fi