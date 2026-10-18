#!/bin/bash
# Bloqueia comandos git destrutivos. git push não está aqui: ele pede confirmação pelo settings.json.
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')
DANGEROUS_PATTERNS=(
  "push --force" "push -f" "--force-with-lease"
  "reset --hard" "git clean -fd" "git clean -f"
  "git branch -D" "git checkout \." "git restore \."
  "rm -rf" "git filter-branch"
)
for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE -- "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented you from doing this." >&2
    exit 2
  fi
done
exit 0
