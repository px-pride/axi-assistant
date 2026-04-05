# DAG-Based Full Auto Development System

This document explains the new DAG-based autonomous development system as an alternative to the wave-based system.

## Overview

Instead of breaking features into large waves of 40-80 features, this system uses a **Directed Acyclic Graph (DAG)** to track feature dependencies and prioritizes features dynamically based on their value and readiness.

## Key Concepts

### Feature DAG
- Each feature has explicit parent dependencies (features that must be completed first)
- Features are organized in a DAG structure to prevent circular dependencies
- The first feature is always a "Hello World" proof-of-concept

### Scoring System

**Vertical Score (1-10):** Direct value to end-users
- 10 = Critical core functionality users expect immediately
- 7-9 = Important features users will want soon
- 4-6 = Nice-to-have features that enhance the experience
- 1-3 = Polish, minor improvements, edge cases

**Effective Value:** Computed as `max(vertical_score, max(effective_values of all children))`
- Ensures features that unlock high-value features are themselves high-value
- Computed recursively starting from leaf nodes

### Batch Selection

Each iteration selects the **top 5** incomplete features where:
1. All parent dependencies are complete
2. The feature itself is incomplete
3. Ranked by effective value (ties broken by vertical score, then alphabetically)

This ensures we always work on the most valuable features that are ready to be implemented.

## File Structure

### Input Files
- **DESIGN_DOC.md** - User-created design document (not modified by system)
- **ARCHITECTURE.md** - Generated architecture and tech stack specification
- **FEATURE_LIST_FULL.md** - Line-by-line list of all features with tags
- **FEATURE_DAG.md** - DAG structure with dependencies, descriptions, and scores

### Runtime Files
- **FEATURE_COMPLETION.md** - Tracks which features have been completed
- **CURRENT_BATCH.md** - Lists the 5 features currently being worked on
- **SETUP_AUDIT.md** - Audit results from setup validation

## Flowchart Structure

### Main Flowchart: `full-auto-dag.json`
Entry point that orchestrates the entire process:
1. Create DAG (calls `create-dag`)
2. Iterate through DAG (calls `iterate-dag`)

### Setup: `create-dag.json`
Creates the initial planning documents:
1. Generate ARCHITECTURE.md, FEATURE_LIST_FULL.md, FEATURE_DAG.md
2. Run auto-validation
3. If validation fails, fix and retry
4. Run human audit
5. If audit finds problems, fix and retry
6. Complete when all documents are validated and audited

### Iteration: `iterate-dag.json`
Main development loop:
1. Initialize FEATURE_COMPLETION.md if needed
2. Select next batch of 5 features (top effective value with complete parents)
   - **Uses deterministic script:** `scripts/select-next-batch.py`
   - Algorithm: parse DAG, calculate effective values, filter candidates, sort and select
   - No LLM calls required - fully deterministic
3. If batch is empty, we're done
4. Process batch (calls `mini-wave`)
5. Mark batch as complete
6. Loop back to step 2

### Batch Processing: `mini-wave.json`
Processes ~5 features at a time:
1. Make tests (calls `mini-wave-make-tests`)
2. Develop features (calls `mini-wave-dev`)
3. Run tests and fix failures (calls `mini-wave-run-tests`)

### Sub-Commands

**`mini-wave-make-tests.json`**
- Reads CURRENT_BATCH.md to see which features need tests
- Creates comprehensive tests following ARCHITECTURE.md patterns
- Sets up testing infrastructure on first batch (Hello World)

**`mini-wave-dev.json`**
- Implements all features in CURRENT_BATCH.md
- Follows architecture from ARCHITECTURE.md
- Integrates with existing code
- Sets up project structure on first batch (Hello World)

**`mini-wave-run-tests.json`**
- Runs full test suite
- If tests fail, analyzes failures and fixes them
- Loops until all tests pass

## Advantages Over Wave System

### 1. **Smaller, More Manageable Chunks**
- 5 features per batch vs 40-80 per wave
- Faster feedback cycles
- Easier to debug and fix issues

### 2. **Value-Driven Prioritization**
- Always working on the highest-value features that are ready
- Effective value ensures infrastructure features get built when needed
- No manual wave planning required

### 3. **Dynamic Adaptation**
- If a feature becomes available (parents complete), it can be selected immediately
- No need to wait for the next predefined wave
- Automatically handles complex dependency graphs

### 4. **Better Dependency Management**
- Explicit DAG prevents circular dependencies
- Clear parent-child relationships
- Ensures features are built in the right order

### 5. **Transparent Progress Tracking**
- FEATURE_COMPLETION.md shows exactly what's done
- CURRENT_BATCH.md shows what's in progress
- Easy to understand project status at any time

## Usage

To use this system instead of the wave-based system:

```bash
# Instead of /full-auto-waves, use:
/full-auto-dag
```

The system will:
1. Read DESIGN_DOC.md
2. Create ARCHITECTURE.md, FEATURE_LIST_FULL.md, and FEATURE_DAG.md
3. Iteratively select and implement batches of 5 features
4. Continue until all features are complete

## Validation Scripts

The system expects these validation scripts (same as wave system):
- `./auto-validation/validate-feature-list-format.sh` - Validates FEATURE_LIST_FULL.md format
- `./auto-validation/validate-feature-dag-format.sh` - Validates FEATURE_DAG.md format
- `./auto-validation/validate-dag-coverage.sh` - Ensures all features are in the DAG

## Comparison with Wave System

| Aspect | Wave System | DAG System |
|--------|-------------|------------|
| Batch Size | 40-80 features | ~5 features |
| Planning | Manual wave breakdown | Automatic from DAG |
| Prioritization | Wave order | Effective value score |
| Dependencies | Implicit in wave order | Explicit parent links |
| Flexibility | Fixed waves | Dynamic selection |
| Progress Tracking | Wave number | Completion tracking |
| Iteration Speed | Slow (large batches) | Fast (small batches) |

## Example FEATURE_DAG.md Format

```markdown
# Hello World

[hello-world] Minimal proof-of-concept that validates the tech stack

# Feature DAG

## [user-authentication]
Description: Users can create accounts and log in securely
Parents: none
Vertical Score: 10

## [user-profile]
Description: Users can view and edit their profile information
Parents: [user-authentication]
Vertical Score: 7

## [profile-avatar]
Description: Users can upload and display profile avatars
Parents: [user-profile]
Vertical Score: 4
```

In this example:
- Hello World is implemented first
- Then user-authentication (score 10, no parents)
- Then user-profile (score 7, depends on authentication)
- Then profile-avatar (score 4, depends on profile)

The effective value of user-profile would be max(7, 4) = 7
The effective value of user-authentication would be max(10, 7) = 10

So the batch order would be: [hello-world] → [user-authentication] → [user-profile] → [profile-avatar]

## Implementation Details

### Script-Based Feature Selection

The batch selection algorithm is implemented as a deterministic Python script (`scripts/select-next-batch.py`) rather than an LLM prompt. This provides:

**Advantages:**
- ✅ **Deterministic**: Same input always produces same output
- ✅ **Fast**: No LLM API calls, executes in <1 second
- ✅ **Cost-effective**: No token usage for selection
- ✅ **Testable**: Standard unit tests verify correctness
- ✅ **Debuggable**: Standard programming tools work

**Technical Details:**
- Input: `FEATURE_DAG.md`, `FEATURE_COMPLETION.md`
- Output: `CURRENT_BATCH.md`, JSON with batch size
- Algorithm: Graph traversal with effective value calculation
- Dependencies: Python 3 standard library only

See `scripts/README.md` for detailed documentation and testing information.
