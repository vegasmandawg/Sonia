#!/bin/bash

# Restore from Backup Script

set -e

BACKUP_DIR="backups"

if [ -z "$1" ]; then
    echo "Usage: $0 <backup-file>"
    echo ""
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null || echo "No backups found"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "⚠️  WARNING: This will restore from backup and overwrite current files!"
read -p "Are you sure? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

echo "Restoring from $BACKUP_FILE..."

# Extract backup
TEMP_DIR=$(mktemp -d)
tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"

# Find extracted directory
EXTRACTED_DIR=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)

if [ -z "$EXTRACTED_DIR" ]; then
    echo "Error: Could not find extracted backup"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Restore files
if [ -d "$EXTRACTED_DIR/dist" ]; then
    echo "Restoring build artifacts..."
    rm -rf dist
    cp -r "$EXTRACTED_DIR/dist" .
fi

if [ -f "$EXTRACTED_DIR/.env.template" ]; then
    echo "Note: Environment template available at $EXTRACTED_DIR/.env.template"
    echo "Please review and update .env.local manually"
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo "✅ Restore completed!"
echo ""
echo "Next steps:"
echo "1. Review .env.local configuration"
echo "2. Test the application: npm run preview"
