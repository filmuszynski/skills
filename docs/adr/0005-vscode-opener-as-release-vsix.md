# ADR 0005: VS Code opener shipped as a `.vsix` on each release

**Status:** Accepted (30.09.2026)

## Context
Opening pages inside VS Code needs an extension. The Marketplace needs a Microsoft publisher account and a yearly token.

## Decision
Build the `.vsix` in the release workflow and attach it to the GitHub release. The skill offers to install it once, from a VS Code terminal.

## Consequences
No accounts needed; non-VS Code users are never asked. No automatic extension updates.

## Alternatives
VS Code Marketplace, possibly later without other changes.
