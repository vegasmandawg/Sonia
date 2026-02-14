"""Convert SONIA_FINAL_BUILD_GUIDE.md to plain text."""
import re

with open(r"S:\docs\SONIA_FINAL_BUILD_GUIDE.md", "r", encoding="utf-8") as f:
    content = f.read()

# Remove heading markers
content = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
# Remove bold markers
content = content.replace("**", "")
# Remove inline code backticks
content = re.sub(r"`([^`]+)`", r"\1", content)
# Remove code block markers
content = re.sub(r"^```\w*\s*$", "", content, flags=re.MULTILINE)
# Remove horizontal rules
content = re.sub(r"^---+\s*$", "", content, flags=re.MULTILINE)

# Process table rows
lines = content.split("\n")
cleaned = []
for line in lines:
    stripped = line.strip()
    # Skip table separator lines (only pipes and dashes)
    if stripped and all(c in "-| " for c in stripped):
        continue
    # Convert table rows to tab-separated
    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [c.strip() for c in stripped.split("|") if c.strip()]
        cleaned.append("  ".join(cells))
    else:
        cleaned.append(line)

content = "\n".join(cleaned)

# Collapse triple+ newlines to single
content = re.sub(r"\n{3,}", "\n", content)

with open(r"S:\docs\SONIA_FINAL_BUILD_GUIDE.txt", "w", encoding="utf-8") as f:
    f.write(content)

print(f"Done. Written to SONIA_FINAL_BUILD_GUIDE.txt")
# Count words
words = len(content.split())
lines_count = len(content.split("\n"))
print(f"Words: {words}, Lines: {lines_count}")
