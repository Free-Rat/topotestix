Stream columns count confirmed/ambiguous/failed-before-send writes by phase.

| Seed | Links a / b / c | Links present | Cut | Placement | Outcome | Stream before | Stream during cut | Stream after | ISR during cut | Controller epochs | Pre-votes | Duration (s) |
|---:|---|---|---|---|---|---|---|---|---|---|---:|---:|
| 1 | 11 / 12 / 12 | 12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | 157.5 |
| 2 | 10 / 10 / 11 | 10 | none | concentrated | pass | 17/0/0 | 62/0/0 | 21/0/0 | 3-3 | 1 | 40 | 274.4 |
| 3 | 10 / 10 / 11 | 10 | 11,12 | concentrated | pass | 17/0/0 | 62/0/0 | 21/0/0 | 3-3 | 1 | 39 | 272.9 |
| 4 | 10,11 / 12 / 11,12 | 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | 156.3 |
| 5 | 10 / 12 / 12 | 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | 155.5 |
| 6 | 10 / 12 / 12 | 12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | 155.0 |
| 7 | 11 / 10,12 / 12 | 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | 154.2 |
| 8 | 11 / 10,12 / 12 | 12 | none | concentrated | precondition_failure | - | - | - | - | - | - | 154.7 |
| 9 | 10 / 10,12 / 12 | 10,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | 155.0 |
| 10 | 11 / 10,12 / 11 | 11 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | 155.3 |
| 11 | 10,11 / 10 / 11,12 | 10,11 | 10,11,12 | spread | pass | 16/1/0 | 4/59/0 | 20/0/0 | 3-3 | 1,3 | 75 | 163.3 |
| 12 | 10,11 / 10,12 / 12 | 10,12 | 12 | concentrated | pass | 16/0/0 | 84/0/0 | 0/0/0 | 3-3 | 1 | 28 | 170.7 |
| 13 | 10,11 / 12 / 12 | 12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | 153.7 |
| 14 | 10 / 12 / 11,12 | 12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | 155.5 |
| 15 | 10 / 12 / 11,12 | 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | 155.6 |
| 16 | 11 / 10,12 / 11,12 | 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | 151.9 |
| 17 | 10,11 / 10,12 / 11 | 10,11 | 10 | concentrated | pass | 16/1/0 | 60/3/0 | 20/0/0 | - | 1 | 19 | 162.2 |
| 18 | 10,11 / 10 / 11 | 10,11 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | 151.0 |
| 19 | 10,11 / 10,12 / 12 | 10,12 | 11,12 | concentrated | pass | 17/0/0 | 63/0/0 | 20/0/0 | 3-3 | 1 | 19 | 270.4 |
| 20 | 11 / 12 / 11,12 | 11,12 | 10 | spread | pass | 16/0/0 | 63/0/0 | 21/0/0 | 2-2 | 1 | 1 | 194.0 |
| 21 | 10 / 10,12 / 11,12 | 10,12 | 12 | concentrated | pass | 17/0/0 | 62/0/0 | 21/0/0 | 3-3 | 1 | 19 | 274.3 |
| 22 | 10,11 / 12 / 12 | 12 | 10,11,12 | concentrated | precondition_failure | - | - | - | - | - | - | 154.8 |
| 23 | 11 / 12 / 12 | 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | 154.5 |
| 24 | 10 / 10,12 / 11,12 | 10,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | 155.9 |
| 25 | 11 / 10,12 / 12 | 12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | 154.1 |
| 26 | 10,11 / 12 / 11 | 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | 154.4 |
| 27 | 10,11 / 12 / 11,12 | 11,12 | 11,12 | spread | pass | 16/1/0 | 0/83/0 | 0/0/0 | - | 1 | 112 | 199.3 |
| 28 | 10,11 / 10,12 / 11,12 | 10,11,12 | 10,12 | spread | pass | 16/1/0 | 68/3/0 | 12/0/0 | 2-3 | 1 | 23 | 160.9 |
| 29 | 10,11 / 10,12 / 11,12 | 10,11,12 | 10,11 | spread | pass | 16/1/0 | 4/59/0 | 20/0/0 | 3-3 | 1,2 | 41 | 162.0 |
| 30 | 11 / 12 / 11,12 | 11,12 | 10,12 | spread | pass | 17/0/0 | 66/0/0 | 17/0/0 | 2-2 | 1 | 22 | 197.8 |
| 31 | 10,11 / 10 / 11,12 | 10,11 | 10,11,12 | spread | precondition_failure | - | - | - | - | - | - | 154.6 |
| 32 | 10,11 / 12 / 11,12 | 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | 155.1 |
| 33 | 11 / 12 / 11 | 11 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | 154.7 |
| 34 | 11 / 10,12 / 11 | 11 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | 155.3 |
| 35 | 10,11 / 10,12 / 11 | 10,11 | 10,12 | concentrated | pass | 16/0/0 | 67/4/0 | 13/0/0 | 2-2 | 2 | 25 | 162.4 |
| 36 | 10 / 10 / 12 | 10 | 10 | spread | precondition_failure | - | - | - | - | - | - | 154.3 |
| 37 | 10 / 12 / 12 | 12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | 153.1 |
| 38 | 10 / 10 / 11 | 10 | 11 | concentrated | pass | 16/0/0 | 62/0/0 | 22/0/0 | 3-3 | 1 | 43 | 272.2 |
| 39 | 10,11 / 12 / 11 | 11 | 11 | spread | precondition_failure | - | - | - | - | - | - | 156.0 |
| 40 | 10,11 / 10,12 / 11 | 10,11 | none | spread | precondition_failure | - | - | - | - | - | - | 154.7 |

Outcomes: pass 14, precondition_failure 26
