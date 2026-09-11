# End-to-End Test Report

Repository: `wayanvota/kindora-chatgpt-mcp`  
Branch: `test/e2e-harness-2026-09-11`  
Date: 2026-09-11  
Environment: macOS, Python 3.12.14, FastMCP 4.0.3

## Result

PASS. All 20 required end-to-end categories passed. The complete repository
suite passed 27 of 27 tests. Python compilation and dependency consistency
checks also passed.

Before this change, seven offline unit tests inspected the server in-process.
They did not start the command-line entry point, negotiate an MCP connection,
or exercise tools across the stdio protocol boundary.

## Test boundary

The harness launches `tests/fixture_server.py` as a separate process and uses
the real FastMCP stdio transport, initialization handshake, tool discovery,
schema validation, dispatch, response serialization, and shutdown behavior.
Only the external Kindora endpoint is replaced by a deterministic fixture.
The suite does not need network access or credentials.

## User-behavior categories

| ID | Behavior | Final |
| --- | --- | --- |
| U01 | Start the stdio process and discover the complete nine-tool surface | PASS |
| U02 | Expose descriptions and read-only annotations for every tool | PASS |
| U03 | Search funders through the public MCP protocol | PASS |
| U04 | Omit optional null values before the upstream call | PASS |
| U05 | Preserve Unicode and punctuation through the round trip | PASS |
| U06 | Apply documented open-grant defaults | PASS |
| U07 | Route all four EIN drilldown tools correctly | PASS |
| U08 | Call the NTEE reference tool with no arguments | PASS |
| U09 | Complete the health check through stdio | PASS |
| U10 | Keep repeated requests independent in one session | PASS |

## Adversarial categories

| ID | Behavior | Final |
| --- | --- | --- |
| A01 | Reject an unknown tool | PASS |
| A02 | Reject a missing required EIN | PASS |
| A03 | Reject a type-confused limit | PASS |
| A04 | Reject an out-of-range limit | PASS |
| A05 | Preserve hostile HTML as inert structured data | PASS |
| A06 | Preserve an interpreter-style payload as inert structured data | PASS |
| A07 | Reject a query over 500 characters | PASS |
| A08 | Reject an EIN list over 100 entries | PASS |
| A09 | Redact an upstream exception and return a generic failure | PASS |
| A10 | Keep configured credentials out of discovery and error output | PASS |

## Failures found and fixed

1. FastMCP attempted an unrelated package update check during stdio startup.
   In environments with restricted networking or proxy configuration, the MCP
   server could fail before accepting a client connection. The server now
   suppresses the stdio banner and disables automatic update checks.
2. FastMCP 4's client first probes an experimental 2026 protocol that this
   server does not advertise. The test client now follows the stable MCP
   handshake used by deployed clients.
3. Tool arguments had no explicit upper bounds. Limits, deadline windows,
   filing years, short text, EIN format, and EIN-list size now have validated
   schemas.
4. Raw upstream exception chains could disclose internal service details. Tool
   calls now return a generic client-safe message while preserving the original
   exception only as the internal cause.
5. The original module-scoped asynchronous fixture could retain a subprocess
   across incompatible event-loop lifetimes. Each test now owns and closes its
   process deterministically.

## Verification evidence

```text
$ python -m compileall -q server.py test_server.py tests
exit 0

$ python -m pip check
No broken requirements found.

$ pytest -q tests/test_e2e.py
20 passed in 13.79s

$ pytest -q --junitxml=test-results/e2e/pytest.xml
27 passed in 13.74s
```

GitHub Actions runs the same compile, dependency, unit, and end-to-end checks on
Python 3.10 and 3.12. It retains the JUnit result for each matrix job even when
a test fails.

## Known boundary

The deterministic suite proves the wrapper's process and protocol boundary. It
does not prove current availability or data quality of the external Kindora
service. A live smoke test would be network-dependent and is intentionally kept
out of pull-request CI.
