Stream columns count confirmed/ambiguous/failed-before-send writes by phase; 'Cut samples' counts successful/planned samples over all nodes during the cut.

## Executions

| Unit | Links a / b / c | Cut | Placement | Outcome | Stream before | Stream during cut | Stream after | ISR during cut | Controller epochs | Cut (s) | Cut samples | Duration (s) |
|---|---|---|---|---|---|---|---|---|---|---:|---|---:|
| seed-1-rep-1 | 11 / 12 / 12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 162.0 |
| seed-11-rep-1 | 10,11 / 10 / 11,12 | 10,11,12 | spread | pass | 8/1/0 | 0/60/0 | 31/0/0 | 3-3 | 1,3 | 60.0 | 37/42 | 176.6 |
| seed-28-rep-1 | 10,11 / 10,12 / 11,12 | 10,12 | spread | pass | 8/1/0 | 52/8/0 | 31/0/0 | 2-3 | 1 | 60.0 | 39/42 | 176.0 |
| seed-12-rep-1 | 10,11 / 10,12 / 12 | 12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 30/42 | 287.1 |
| seed-29-rep-1 | 10,11 / 10,12 / 11,12 | 10,11 | spread | pass | 8/0/0 | 50/10/0 | 32/0/0 | 2-3 | 1,2 | 60.0 | 38/42 | 173.2 |

## Seeds

| Seed | Formation predicted | Formed | Outcomes | Graph during cut | Cut removes a link | Prediction holds | Resolution matches plan |
|---:|---|---|---|---|---|---|---|
| 1 | impossible | 0/1 | precondition_failure 1 | all isolated | yes | yes | yes |
| 11 | election | 1/1 | pass 1 | all isolated | yes | yes | yes |
| 12 | election | 1/1 | pass 1 | one link | yes | yes | yes |
| 28 | certain | 1/1 | pass 1 | one link | yes | yes | yes |
| 29 | certain | 1/1 | pass 1 | one link | yes | yes | yes |

## Decision checks

- D2 verdict seeds: 4 (minimum 15)
- D2 graph classes with a verdict: all isolated, one link (minimum 3 of 4)
- D2 verdict seeds whose cut removes a link: 4 (minimum 5; null conclusion needs 10)
- D2 verdict seeds whose cut changes nothing: 0 (minimum 3)
- D6 predictions hold for every certain and impossible seed: yes
- Gate 'materialized' passes in every run past formation: yes
- Demonstration minimum met: no; null minimum met: no
- Contract violations (D3): none
- Lowest host MemAvailable during the campaign: 6945 MiB

Outcomes: pass 4, precondition_failure 1
