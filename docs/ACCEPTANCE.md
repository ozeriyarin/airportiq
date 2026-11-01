# Acceptance pass — 1.11.2026, HEAD `e4899f0` (batches 1–3); Round 2 addendum at HEAD `eee30c3`

Run in three batches (static, live conversation, rate limit). Every evidence cell is pasted from real output of that
run and names the command that produced it; nothing is summarized from memory. The live checks in batch 2 were first
run by a script that became `agent accept <url>` (cases in `evals/accept/cases.yaml`); batch 1 rows are git, gh and uv
commands as written in each cell. Live calls went to https://airportiq.onrender.com; the two local runs are
marked and ran on the same commit.

## Batch 1 — static

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Working tree clean, HEAD pushed | PASS | `git status --porcelain` → 0 lines; `## main...origin/main`; HEAD `e4899f0` |
| 2 | No `.env`, `*.db`, raw data, PDFs, zips or handoff tracked | PASS | `git ls-files` grep for `.env$ / .db$ / handoff / ^data/raw / .pdf$ / .zip$` → none |
| 3 | No key patterns in any tracked file | PASS | `git grep` for `sk-ant-`, `sk-or-`, `AIza…`, `ghp_`, `gho_`, `xoxb-`, private-key headers → none |
| 4 | CI green on HEAD | PASS | `gh run list` → `completed success e4899f0` |
| 5 | Fresh clone, README only: install | PASS | clone into a temp folder, `uv sync` → `+ websockets==17.3` (last line, no error) |
| 6 | Fresh clone: lint | PASS | `uv run ruff check src tests` → `All checks passed!` |
| 7 | Fresh clone: full test count | PASS | `uv run pytest -q` → `132 passed in 75.07s` |
| 8 | Fresh clone: one test chat | PASS | `agent chat --test "What can you help me with?"` → intro with the four questions, `answered · intro · 0.0000 USD` |
| 9 | Fresh clone: offline smoke | PASS | `agent eval --test` → `12/12 cases, exit code 0` |
| 10 | Every report in the README table | PASS | `evals/results/` holds ci-smoke, v3-baseline, v3-anthropic-down; each appears once in the README table |
| 11 | README numbers match the latest reports | PASS | JSON: baseline 23/23, 0.44885 USD, cache 0.467, ungrounded 0, prompt 0.3.0; down 21/23, 0.040237 USD; README lines 146–147 carry 23/23, 21/23, prompt 0.3.0, 0.4489, 0.0402. These are the 23-case baseline figures, superseded by R4 and R5 in the addendum (43 cases, prompt 0.3.1). |
| 12 | Prompt and config versions match | PASS | `PROMPT_VERSION = "0.3.0"`; agent.yaml 0.1.0, scoring.yaml 1.0.0, prices.yaml 0.3.0; both reports cite prompt 0.3.0 and config 0.1.0 |
| 13 | README numbers match config | PASS | weights 0.3 / 0.25 / 0.2 / 0.15 / 0.1, 3000 miles, 4000 hours, blend 0.7 / 0.2 / 0.1, RMSE 92,932 all present and equal to `scoring.yaml` and `agent score` |
| 14 | DESIGN complete | PASS | sections: System architecture; Where AI is used; Data layer; Scoring methodology (with worked SFO example); Repository structure; Key tradeoffs; Security and privacy; What the evals showed; What production would change |
| 15 | Static UI checks (served HTML) | PASS | `<title>airportiq</title>` ×1; the four example questions present; external `<script src>` ×0; `id="mic"` ×1, `id="speak"` ×1; footer "not investment advice"; `prefers-color-scheme`; input `maxlength="2000"` |
| 16 | Every spec criterion has a named test, `UNIMPLEMENTED` empty | PASS | `UNIMPLEMENTED: set[str] = set()`; six spec folders v0–v5; `tests/test_spec_coverage.py` → `1 passed` |
| 17 | Docs drift words | PASS | grep README, DESIGN, demo script, product docs for "still to come / pending / TODO / TBD / PLACEHOLDER" → none |
| 18 | Scheduled or side jobs, with and without force | N/A | this project has none: `.github/workflows/` holds only `ci.yml`, no cron, no alert or webhook module |

## Batch 2 — live conversation (deployed service unless marked local)

| # | Check | Result | Evidence |
|---|---|---|---|
| 19 | `GET /health` | PASS | `agent accept`: 200; models Sonnet 5.5 → Haiku 5.5 → Gemini 2.5 Flash; guard `typesafe:jev-latest → anthropic:claude-haiku-5-5`; 144 airports |
| 20 | `GET /api/docs` | PASS | `agent accept`: 200, Swagger UI |
| 21 | `GET /` | PASS | `agent accept`: 200, title present, 9,195 bytes |
| 22 | `GET /api/stats` without / with wrong token | PASS | `agent accept`: 401 `admin token required`; 401 |
| 23 | `DELETE /api/sessions/{id}` | PASS | `agent accept`: 204 |
| 24 | Empty body / no message | PASS | `agent accept`: 422; 422 |
| 25 | Q1 "Which airports in New England are strong candidates for terminal expansion?" | PASS | `agent accept` (case brief-1): answered, Sonnet 5.5, tools `rank_airports, about, airport_score`, 0.0326 USD, 200 words; BOS CPS 76.9 first, BTV second |
| 26 | Follow-up "Why is the first one on top?" (same session) | PASS | `agent accept` (case fu-ne-why-first): answered from prior context, tools `[]`, 0.0085 USD, 106 words; utilization 99.6% of 412,000 adds 26.4 points |
| 27 | Q2 "Compare LA and Santa Ana airport congestion levels." | PASS | `agent accept` (case brief-2): answered, `compare_airports`, 0.0137 USD, 152 words; SNA 70.3 vs LAX 61.3 on the congestion lens; "I took LA to mean LAX" |
| 28 | Follow-up "Where do their capacity numbers come from?" | PASS | `agent accept` (case fu-compare-then-capacity): answered, tools `[]`, 0.0083 USD, 117 words; FAA service volume 675,000 and 355,000, 2014 profiles 163.8/h → 655,200 and 55.2/h → 220,800 as cross-check |
| 29 | Q3 "What is the percentage of long haul flights out of Anchorage airport?" | PASS | `agent accept` (case brief-3): answered, `traffic_mix`, 0.0087 USD, 71 words; 31.0% = 27,305 of 87,988 departures in 2025 |
| 30 | Follow-up "And the year before?" | PASS | `agent accept` (case fu-anc-year-before): answered, `traffic_mix`, 0.0090 USD, 51 words; 29.9% = 28,080 of 93,961 in 2024 |
| 31 | Q4 "What is the unmet flight demand in SFO airport and why?" | PASS | `agent accept` (case brief-4): answered, `unmet_demand`, 0.0129 USD, 150 words; lens 64.4, "inferred, not a count of flights", load factor 0.8231 (86.5th pct) main driver, 18.93% of 143,415 delayed |
| 32 | Greeting costs nothing | PASS | `agent accept` (case greet-hi): "hi" → answered, guardrail `intro`, cost 0.0, latency 0 ms |
| 33 | Off-topic refusal names the scope | PASS | `agent accept` (case off-poem): poem → `refused_off_topic` by `jev-1.14.0`, cost 0.0; text starts "I can only help with capacity pressure at US hub airports: ranking and comparing airports, congestion, unmet demand, traffic mix and current FAA status" |
| 34 | Injection stopped by the regex layer, no model call | PASS | `agent accept` (case inj-ignore): → `refused_injection`, guardrail `regex`, cost 0.0, latency 0 ms |
| 35 | False positive answered normally (local, commit e4899f0; live hit the IP limit, see 40) | PASS | `agent chat` locally (case fp-ignore-west): "Ignore the West Coast airports; which New England airport is most congested?" → answered, Sonnet 5.5, BOS and BTV named, 0.0447 USD |
| 36 | One question in the other product language (local) | PASS | `agent chat` locally (case hebrew-new-england): Hebrew question → answered in Hebrew by Sonnet 5.5, 0.0129 USD: Boston and Burlington lead, capacity is the FAA service volume (measured) |
| 37 | Grounding spot check against the engine | PASS | `agent eval --cases evals/accept/cases.yaml` (7/7, ungrounded 0) + `agent score BOS`: utilization 0.9964 / `utilization_pct` 99.6, `delayed15_pct` 22.72, `load_factor_pct` 81.7, `long_haul_pct` 7.2, contributions 26.4 and 20.38 — every figure in answers 25–26 is a tool field, no model-computed sum; local eval of the 4 brief + 3 follow-up cases: 7/7, `ungrounded runs: 0` |
| 38 | Fallback: vendor 1 down, vendor 2 answers | PASS | `agent eval --down anthropic` on the ANC case: models `google-gla:gemini-2.5-flash`, 1/1, served by gemini-2.5-flash, 0.0015 USD; plus the committed `v3-anthropic-down` report 21/23 all served by Gemini |
| 39 | Fallback: all vendors down, clean unavailable, no crash | PASS | `agent chat` with invalid vendor keys in the environment: invalid keys for all vendors at runtime → log `all models failed: FallbackExceptionGroup(…401…, ConnectionError)`; reply "All model providers are unavailable right now. Please try again in a minute." status `unavailable`, 0.0000 USD, exit 0 |

## Batch 3 — rate limit (last; blocks this IP for the window)

| # | Check | Result | Evidence |
|---|---|---|---|
| 40 | 429 with Retry-After using free turns | PASS | `curl -X POST /api/chat` with a greeting: `POST /api/chat {"message":"hi"}` → `HTTP/1.1 429 Too Many Requests`, `retry-after: 2678`, body `Too many requests from your address. Try again later.` The window had been consumed by the live checks above together with browser use from the same network during the session, which is why checks 35–36 moved to a local run. |

## Round 2 addendum — capacity precedence and the extended eval set

After the pass above, a data check showed the FAA service volume is stale for the largest hubs (16 airports ran
above it in FY2024, Denver at 1.96 times) and that the docs' claim that the profiles agree with it "within a few
percent" was false (median ratio 1.23, range 0.62 to 2.96). Scoring 1.1.0 restores the approved precedence,
profile first, service volume second, runway model last, and adds a limitation whenever operations exceed the
capacity figure (11 airports). The eval set grew from 23 to 43 cases. Re-verification evidence:

| # | Check | Result | Evidence |
|---|---|---|---|
| R1 | Capacity precedence switched, worked example refreshed | PASS | `agent score SFO`: capacity 402,400 from `faa_profile`, utilization 0.9476 (pct 90.8), CPS 74.3; DESIGN table and README carry the same figures, asserted by `test_criterion_14` |
| R2 | False sentence removed | PASS | grep "within a few percent" in README and DESIGN → 0 |
| R3 | Eval set size and coverage | PASS | 43 cases: 26 in scope, 4 off topic, 4 injection, 4 false positive, 5 follow-up; all eight tools asserted; XNA (modelled), GUM (no capacity), bad year, bad area, Hebrew |
| R4 | Baseline (repeat 2, prompt 0.3.1) | PASS with flakes | 40/43, no failed case, exit 2, ungrounded runs 0, 0.9335 USD; flaky: sfo-long-haul-2023 and fu-anc-year-before (tool-call loop hit the 16-request ceiling in 2 of 86 runs), fp-override (honest "cannot confirm" once) |
| R5 | Gemini alone (`--down anthropic`) | PASS, recorded | 40/43 served by gemini-2.5-flash, 0.0713 USD; misses are formatting (31% for 31.0) and two self-computed numbers caught by grounding |
| R6 | Offline suite after the switch | PASS | ruff clean; `132 passed` |
| R7 | Live service after redeploy (commit `eee30c3`, CI green) | PASS | `agent verify`: /health ok, three models, Jev guard, 144 airports; /api/chat answered by claude-sonnet-5-5 with rank_airports, about, airport_score, 12529 ms, 0.0277 USD; a live SFO capacity question names the FAA profile and 402,400 |

## Structure pass — `agent accept` against the live service

| # | Check | Result | Evidence |
|---|---|---|---|
| S1 | `agent accept https://airportiq.onrender.com` at commit `cc83641` | 17/18, exit 1 | six endpoint rows PASS (200, 200, 200, 401/401, 204, 422/422); the brief's four questions, three follow-ups, greeting (intro, 0.0000 USD), off-topic (jev), injection (regex), false positive and the Hebrew question PASS; brief-3 (ANC) came back as a non-200 from the service. Re-asking it twice reproduced the intermittent tool loop (second run `cannot_answer` after 20 s, 0 USD). |
| S2 | Loop traced and fixed | PASS | `capture_run_messages` on a limit-exceeded turn: `traffic_mix` called 15 times with identical arguments; fix: every tool wrapped so a repeated identical call returns `Repeated` (commit `cbe743d`), offline test with a scripted model that repeats a call |
| S3 | `agent accept https://airportiq.onrender.com` after the redeploy of `cbe743d` | PASS | 18/18 checks, exit 0; brief-3 (ANC): answered, claude-sonnet-5-5, tools traffic_mix + about, 0.0108 USD, 6904 ms, 65 words; every other row as in S1 |

| S4 | `agent accept` after the v6 redeploy (`9ec7341`) | 16/18 | the ANC question looped again (cannot_answer, 0 USD, 24 s) and its follow-up therefore lacked context; everything else PASS. The repeat guard stops the tool from re-running but not the model from re-asking, so the 16-request ceiling still ends the turn. Render now logs the call sequence of such a turn; owner to read it. |
| S5 | `aircraft_now` on Render without credentials | FAIL, fixed | anonymous call from Render's shared egress address returned 429 and the validating client raised before the quota branch; fixed so the 429 and its Retry-After are reported (offline test added); with `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` set in Render the registered quota (4,000 a day) applies |

## Left to the owner

- Phone pass on https://airportiq.onrender.com: keyboard does not cover the input, last bubble clears the sticky bar, example placeholder rotates, dark mode follows the system.
- Voice: press the mic in Chrome or Edge, ask one of the four questions, hear the answer read back; toggle the speaker and confirm the preference survives a reload.
- Render: set `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` in the service environment (v6); until then the aircraft tool runs anonymously from a shared address and usually reports the quota as exhausted.
- Render logs: when a turn ends with "I had to stop before finishing", the log line `turn stopped by usage limit ...; tool calls: [...]` shows what the model repeated; paste it into the next session to close the loop issue.
- Provider consoles: confirm the caps recorded as set on 1.11.2026 in Anthropic Limits, Google Cloud budget and the TypeSafe dashboard match `BUDGET_USD` (15 USD since 1.11.2026).
