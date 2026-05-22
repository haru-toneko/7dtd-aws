#!/bin/bash
# Lambdaパッケージをビルドするスクリプト
# 実行: bash build.sh
# 前提: python3, pip3 がWSL/Linux環境にインストール済みであること

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/.build"

echo "==> .build ディレクトリをクリーン..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# ─── discord_bot ─────────────────────────────────────────────────────────────
echo "==> discord_bot をビルド..."
mkdir -p "$BUILD_DIR/discord_bot"

# discord_bot は pure Python Ed25519 実装のため外部ライブラリ不要

cp "$SCRIPT_DIR/lambda/discord_bot/index.py" "$BUILD_DIR/discord_bot/index.py"

echo "  discord_bot: OK ($(du -sh "$BUILD_DIR/discord_bot" | cut -f1))"

# ─── discord_worker ──────────────────────────────────────────────────────────
echo "==> discord_worker をビルド..."
mkdir -p "$BUILD_DIR/discord_worker"
cp "$SCRIPT_DIR/lambda/discord_worker/index.py" "$BUILD_DIR/discord_worker/index.py"
echo "  discord_worker: OK"

# ─── auto_stop ───────────────────────────────────────────────────────────────
echo "==> auto_stop をビルド..."
mkdir -p "$BUILD_DIR/auto_stop"
cp "$SCRIPT_DIR/lambda/auto_stop/index.py" "$BUILD_DIR/auto_stop/index.py"
echo "  auto_stop: OK"

# ─── game_ready_notifier ─────────────────────────────────────────────────────
echo "==> game_ready_notifier をビルド..."
mkdir -p "$BUILD_DIR/game_ready_notifier"
cp "$SCRIPT_DIR/lambda/game_ready_notifier/index.py" "$BUILD_DIR/game_ready_notifier/index.py"
echo "  game_ready_notifier: OK"

echo ""
echo "==> ビルド完了。次のコマンドでTerraformを適用してください:"
echo "  cd terraform && terraform init && terraform apply"
