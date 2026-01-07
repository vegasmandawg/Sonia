#!/bin/bash

# Backup Script
# Creates backups of critical files and data

set -e

BACKUP_DIR="backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="sonia-backup-${TIMESTAMP}"

echo "Creating backup: $BACKUP_NAME"

# Create backup directory
mkdir -p "$BACKUP_DIR/$BACKUP_NAME"

# Backup build artifacts
if [ -d "dist" ]; then
    echo "Backing up build artifacts..."
    cp -r dist "$BACKUP_DIR/$BACKUP_NAME/"
fi

# Backup environment (without secrets)
if [ -f ".env.local" ]; then
    echo "Backing up environment template..."
    grep -v "GEMINI_API_KEY\|API_KEY\|SECRET\|PASSWORD" .env.local > "$BACKUP_DIR/$BACKUP_NAME/.env.template" || true
fi

# Backup configuration files
echo "Backing up configuration..."
cp package.json "$BACKUP_DIR/$BACKUP_NAME/" 2>/dev/null || true
cp vite.config.ts "$BACKUP_DIR/$BACKUP_NAME/" 2>/dev/null || true
cp tsconfig.json "$BACKUP_DIR/$BACKUP_NAME/" 2>/dev/null || true

# Create archive
echo "Creating archive..."
tar -czf "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" -C "$BACKUP_DIR" "$BACKUP_NAME"

# Cleanup temporary directory
rm -rf "$BACKUP_DIR/$BACKUP_NAME"

# Keep only last 5 backups
echo "Cleaning old backups..."
ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +6 | xargs rm -f 2>/dev/null || true

echo "✅ Backup created: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"

# List all backups
echo ""
echo "Available backups:"
ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null || echo "No backups found"
