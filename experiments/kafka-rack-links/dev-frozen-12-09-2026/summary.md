Stream columns count confirmed/ambiguous/failed-before-send writes by phase; 'Cut samples' counts successful/planned samples over all nodes during the cut.

## Executions

| Unit | Links a / b / c | Cut | Placement | Outcome | Stream before | Stream during cut | Stream after | ISR during cut | Controller epochs | Cut (s) | Cut samples | Duration (s) |
|---|---|---|---|---|---|---|---|---|---|---:|---|---:|
| seed-1-rep-1 | 11 / 12 / 12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.9 |
| seed-2-rep-1 | 10 / 10 / 11 | none | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 25/42 | 280.9 |
| seed-28-rep-1 | 10,11 / 10,12 / 11,12 | 10,12 | spread | pass | 8/0/0 | 57/3/0 | 32/0/0 | 2-2 | 1 | 60.0 | 35/42 | 170.0 |

## Seeds

| Seed | Formation predicted | Formed | Outcomes | Graph during cut | Cut removes a link | Prediction holds | Resolution matches plan |
|---:|---|---|---|---|---|---|---|
| 1 | impossible | 0/1 | precondition_failure 1 | all isolated | yes | yes | yes |
| 2 | certain | 1/1 | pass 1 | one link | no | yes | yes |
| 28 | certain | 1/1 | pass 1 | one link | yes | yes | yes |

## Decision checks

- D2 verdict seeds: 2 (minimum 15)
- D2 graph classes with a verdict: one link (minimum 3 of 4)
- D2 verdict seeds whose cut removes a link: 1 (minimum 5; null conclusion needs 10)
- D2 verdict seeds whose cut changes nothing: 1 (minimum 3)
- D6 predictions hold for every certain and impossible seed: yes
- Gate 'materialized' passes in every run past formation: yes
- Demonstration minimum met: no; null minimum met: no
- Contract violations (D3): none
- Source revisions: 9302faeec606ac0663c85c9f2c6243c930a48203; units on uncommitted code: 0; units without a recorded revision: 0; single clean revision: yes
- Lowest host MemAvailable during the campaign: 6964 MiB

Outcomes: pass 2, precondition_failure 1
