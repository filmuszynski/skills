---
saved: 2026-09-09 23:38
status: saved
---

# Widget Sync Implementation Plan

**Goal:** Keep widgets in sync.
**Architecture:** Poller plus a cache.
**Tech Stack:** Python.

## Global Constraints

- Stay inside the project root.
- No new dependency.

---

### Task 1: Build the poller

**Files:** Create `poller.py`

- [ ] **Step 1: Failing test first**

```bash
python -m pytest tests/test_poller.py
```

- [ ] **Step 2: Implement the loop**

The loop reads the queue and yields batches.

### Task 2: Wire the cache

**Files:** Modify `cache.py`

- [ ] **Step 1: Add the write path**
- [ ] **Step 2: Add the read path**
- [ ] **Step 3: Commit**

### Task 3: Verify

- [ ] **Step 1: Run everything**
