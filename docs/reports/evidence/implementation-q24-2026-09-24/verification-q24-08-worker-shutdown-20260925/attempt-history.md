# Preserved attempts and environment limits

1. `process-red.log`: seven original subprocess tests failed before the process
   drain hook existed. This is known-bad behavior, not a passing result.
2. `focused-green.log`: initial launcher/process/package scope passed 34 tests.
   `docker-regression.log` separately passed 27 tests at that earlier snapshot.
3. Initial concurrent global-Python regression did not complete. The parent
   runner reported a 180-second timeout for make api16-worker. The partial
   worker and API logs remain in their original files; they are not PASS.
4. `testclient-diagnostic.log`: a bounded test under the project API dependency
   environment also stalled in the TestClient/AnyIO boundary inside the sandbox
   and exited 124. The trace is retained; a precise root cause was not proven.
5. The authorized outside-sandbox retry settled with exit 0: `runtime-regression.log`
   records 129 passed and one deprecation warning in 3.50 seconds. It uses the
   existing `/tmp/q24-api-deps-env/bin/python` and synthetic local components.
6. Sartre's independent read-only review passed the original scoped candidate
   with a LOW finding: process timing tolerance alone would permit a larger
   drain argument. The exact-budget and operational-outcome regression addresses
   this without changing the two-second production hook.
7. `final-docker-observability.log`: an attempted combined static/package run
   under the API runtime environment failed collection with missing PyYAML.
   Inspection confirmed YAML is intentionally absent from the runtime lock,
   while the previously used Docker-test interpreter provides PyYAML 6.0.1.
   No dependency or lock was changed. `final-docker-observability-host.log`
   records the corrected interpreter run: 46 passed in 4.08 seconds, exit 0.
8. An initial in-memory mutation probe rejected all nine changed-budget cases
   but its additional runner assertion expected the text `call(...)` instead
   of unittest's actual `mock(...)` formatting. That probe exited 1; it is not
   counted as PASS. The checked-in `verify_budget_contract.py` uses the actual
   outcome count and budget values instead of the mock's display name. Its
   execution exits 0 and `budget-mutation.log` records nine expected rejections
   of a 3.0-second in-memory mutation, with source bytes unchanged.

9. The first final controller validation at revision 379 failed two metadata
   rules: the local review event used the global task's action ID, and the
   review record's observed_at was a few microseconds after its recording
   timestamp. The unchanged checker validates these raw fields globally;
   its CORRECTION mechanism applies only to status transitions. The two newly
   authored rejected rows were archived byte-for-byte, then only their action
   scope and recording timestamp were normalized. The failed validation and
   explicit recovery were appended to the ledgers. Every byte of both ledgers
   predating this continuation still matches its recorded prefix hash. No
   test/review outcome, gate, authority or earlier record was changed.
   `control-metadata-repair.json` records the exact changes and archives;
   `control-final.log` retains the rejection. At revision 380, the final
   unchanged `make validate` and diff check exited 0; results are in
   `final-control-repaired-results.json`.

These environment, probe and controller failures remain separate from the passing final
checks. Neither a stalled test nor a missing static-test dependency established
a product defect or justified changing the application dependencies.
