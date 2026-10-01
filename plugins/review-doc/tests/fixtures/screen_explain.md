---
kind: explain
title: How the hook gets round plan mode
---

## The restriction

Plan mode forbids Claude from writing **any** file except the plan itself.

## The way through

A `PostToolUse` hook is run by the harness, not by Claude, so it fires anyway.

<svg viewBox="0 0 260 70" width="260" height="70" role="img" aria-label="Flow">
  <text x="0" y="16" font-size="10">Claude writes plan.md</text>
  <line x1="10" y1="24" x2="10" y2="44" stroke="currentColor"/>
  <text x="18" y="40" font-size="9">PostToolUse</text>
  <text x="0" y="58" font-size="10">renderer emits the page</text>
</svg>

## Why it matters

Without it, a plan page could never be generated while the plan was being written.
