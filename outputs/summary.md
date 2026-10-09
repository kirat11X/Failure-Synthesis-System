# FSS verification summary

From `junit.xml` and `coverage.json` of the run these files were built from.

## Tests by catalogue category

| Category | Cases | Passed | Failed | Skipped |
|---|---|---|---|---|
| SPEC | 27 | 27 | 0 | 0 |
| P | 82 | 82 | 0 | 0 |
| S | 19 | 19 | 0 | 0 |
| E | 7 | 7 | 0 | 0 |
| ST | 5 | 5 | 0 | 0 |
| R | 14 | 14 | 0 | 0 |
| V | 11 | 11 | 0 | 0 |
| RAG | 18 | 18 | 0 | 0 |
| PI | 6 | 6 | 0 | 0 |
| Y | 25 | 25 | 0 | 0 |
| UI | 5 | 5 | 0 | 0 |
| G | 6 | 6 | 0 | 0 |
| ARCH | 1 | 1 | 0 | 0 |
| SC | 8 | 8 | 0 | 0 |
| B | 7 | 7 | 0 | 0 |
| K | 4 | 4 | 0 | 0 |
| supporting | 264 | 256 | 0 | 8 |
| **All** | **509** | **501** | **0** | **8** |

Skipped cases are the live-LLM tests (no `FSS_LLM_API_KEY`).

## Branch coverage

| Module | Line | Branch |
|---|---|---|
| decoder | 98.3% | 95.8% |
| schema | 93.0% | 87.5% |
| knowledge | 96.3% | 92.5% |
| evidence | 100.0% | 100.0% |
| context | 98.8% | 93.3% |
| validator | 98.0% | 92.1% |
| investigate | 94.9% | 93.8% |
| **total** | 96.2% | 91.5% |

## LLM-EVAL

Not run: no `FSS_LLM_API_KEY` was available. All LLM-EVAL cells are "not run".
