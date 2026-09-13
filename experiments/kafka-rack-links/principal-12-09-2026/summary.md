Stream columns count confirmed/ambiguous/failed-before-send writes by phase; 'Cut samples' counts successful/planned samples over all nodes during the cut.

## Executions

| Unit | Links a / b / c | Cut | Placement | Outcome | Stream before | Stream during cut | Stream after | ISR during cut | Controller epochs | Cut (s) | Cut samples | Duration (s) |
|---|---|---|---|---|---|---|---|---|---|---:|---|---:|
| seed-42-rep-1 | 11 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 156.4 |
| seed-41-rep-1 | 10 / 10 / 12 | 11 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 25/42 | 284.9 |
| seed-43-rep-1 | 11 / 12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 157.3 |
| seed-45-rep-1 | 10 / 10,12 / 11,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 159.5 |
| seed-44-rep-1 | 10 / 10,12 / 12 | 10 | spread | pass | 8/1/0 | 58/2/0 | 31/0/0 | 2-2 | 1 | 60.0 | 34/42 | 207.6 |
| seed-46-rep-1 | 10 / 10,12 / 12 | 10 | concentrated | pass | 8/1/0 | 5/55/0 | 31/0/0 | 3-3 | 1,3 | 60.0 | 20/42 | 284.1 |
| seed-47-rep-1 | 10 / 10 / 11 | 11,12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 25/42 | 284.6 |
| seed-49-rep-1 | 10 / 12 / 11,12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.2 |
| seed-48-rep-1 | 10 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/1/0 | 3/57/0 | 31/0/0 | - | 1,3 | 60.0 | 20/42 | 284.0 |
| seed-50-rep-1 | 10 / 12 / 11,12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 157.5 |
| seed-51-rep-1 | 10,11 / 12 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 156.0 |
| seed-52-rep-1 | 11 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-53-rep-1 | 11 / 10,12 / 11 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.0 |
| seed-54-rep-1 | 10,11 / 10 / 11,12 | 12 | spread | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 36/42 | 173.0 |
| seed-55-rep-1 | 10 / 10,12 / 11 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-56-rep-1 | 10,11 / 12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.0 |
| seed-57-rep-1 | 10 / 10 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 155.5 |
| seed-58-rep-1 | 10 / 12 / 11,12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 156.0 |
| seed-59-rep-1 | 10 / 10,12 / 11,12 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 173.1 |
| seed-60-rep-1 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 159.0 |
| seed-61-rep-1 | 10 / 10,12 / 11,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 158.1 |
| seed-62-rep-1 | 10,11 / 10,12 / 11 | 10,11,12 | spread | pass | 8/1/0 | 4/56/0 | 31/0/0 | - | 1,3 | 60.0 | 31/42 | 174.6 |
| seed-63-rep-1 | 10,11 / 10,12 / 12 | none | spread | pass | 8/0/0 | 60/0/0 | 32/0/0 | 2-2 | 1 | 60.0 | 35/42 | 208.0 |
| seed-64-rep-1 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 155.0 |
| seed-65-rep-1 | 11 / 10 / 11 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.8 |
| seed-66-rep-1 | 10,11 / 12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 154.0 |
| seed-68-rep-1 | 10 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.8 |
| seed-67-rep-1 | 11 / 12 / 11,12 | 10,11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | - | 1 | 60.0 | 30/42 | 205.4 |
| seed-69-rep-1 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-70-rep-1 | 10 / 10,12 / 11,12 | 12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 284.3 |
| seed-71-rep-1 | 10,11 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/1/0 | 58/2/0 | 31/0/0 | 2-3 | 1 | 60.0 | 35/42 | 171.9 |
| seed-72-rep-1 | 10,11 / 10 / 11,12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.1 |
| seed-73-rep-1 | 10 / 10 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 156.2 |
| seed-74-rep-1 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-75-rep-1 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.3 |
| seed-76-rep-1 | 10 / 12 / 11,12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.0 |
| seed-77-rep-1 | 10,11 / 10,12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 158.1 |
| seed-78-rep-1 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.3 |
| seed-79-rep-1 | 10 / 12 / 12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 156.6 |
| seed-80-rep-1 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-81-rep-1 | 10 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.5 |
| seed-82-rep-1 | 11 / 10,12 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 158.5 |
| seed-83-rep-1 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 161.8 |
| seed-85-rep-1 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 158.4 |
| seed-84-rep-1 | 10 / 10,12 / 12 | 11,12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 35/42 | 173.7 |
| seed-86-rep-1 | 10,11 / 10,12 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.1 |
| seed-87-rep-1 | 11 / 10 / 11 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.2 |
| seed-89-rep-1 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.8 |
| seed-88-rep-1 | 11 / 10 / 12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 161.6 |
| seed-91-rep-1 | 10 / 10 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 154.0 |
| seed-90-rep-1 | 10 / 10 / 11 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 2 | 60.0 | 25/42 | 280.8 |
| seed-92-rep-1 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 161.6 |
| seed-93-rep-1 | 11 / 12 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 157.0 |
| seed-95-rep-1 | 11 / 12 / 11 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 155.8 |
| seed-94-rep-1 | 10,11 / 10 / 12 | 11,12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 25/42 | 285.3 |
| seed-96-rep-1 | 11 / 10 / 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.6 |
| seed-97-rep-1 | 11 / 10 / 11 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.1 |
| seed-98-rep-1 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-99-rep-1 | 11 / 10,12 / 11,12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-100-rep-1 | 11 / 10,12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.6 |
| seed-101-rep-1 | 11 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.7 |
| seed-102-rep-1 | 10 / 10,12 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 157.2 |
| seed-103-rep-1 | 11 / 10,12 / 11,12 | 10 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 2-2 | 1 | 60.0 | 39/42 | 205.3 |
| seed-104-rep-1 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 159.8 |
| seed-105-rep-1 | 10,11 / 10 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 156.4 |
| seed-106-rep-1 | 10 / 10,12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 156.5 |
| seed-108-rep-1 | 11 / 10,12 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.1 |
| seed-107-rep-1 | 10,11 / 10,12 / 12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 284.7 |
| seed-109-rep-1 | 11 / 12 / 11,12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 159.7 |
| seed-110-rep-1 | 10,11 / 10,12 / 11,12 | none | spread | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 35/42 | 173.3 |
| seed-111-rep-1 | 11 / 10 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 162.4 |
| seed-112-rep-1 | 10 / 10,12 / 11 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 156.1 |
| seed-113-rep-1 | 11 / 10 / 11,12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 154.2 |
| seed-114-rep-1 | 10,11 / 12 / 12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 155.5 |
| seed-115-rep-1 | 10 / 10 / 11 | none | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 282.5 |
| seed-116-rep-1 | 10 / 10,12 / 12 | 10,11 | concentrated | pass | 8/0/0 | 3/57/0 | 32/0/0 | 3-3 | 1,3 | 60.0 | 20/42 | 281.5 |
| seed-117-rep-1 | 10,11 / 10 / 11,12 | 10 | spread | pass | 8/0/0 | 52/8/0 | 32/0/0 | 2-2 | 1 | 60.0 | 35/42 | 170.8 |
| seed-118-rep-1 | 11 / 10 / 11 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 157.4 |
| seed-119-rep-1 | 11 / 10,12 / 11,12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.2 |
| seed-120-rep-1 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 159.6 |
| seed-42-rep-2 | 11 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 150.5 |
| seed-41-rep-2 | 10 / 10 / 12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 279.0 |
| seed-43-rep-2 | 11 / 12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.2 |
| seed-44-rep-2 | 10 / 10,12 / 12 | 10 | spread | pass | 8/0/0 | 0/60/0 | 32/0/0 | 2-2 | 1 | 60.0 | 32/42 | 200.8 |
| seed-45-rep-2 | 10 / 10,12 / 11,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 153.8 |
| seed-46-rep-2 | 10 / 10,12 / 12 | 10 | concentrated | pass | 8/1/0 | 5/55/0 | 31/0/0 | - | 1,3 | 60.0 | 20/42 | 281.4 |
| seed-47-rep-2 | 10 / 10 / 11 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 2 | 60.0 | 25/42 | 279.5 |
| seed-49-rep-2 | 10 / 12 / 11,12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.3 |
| seed-48-rep-2 | 10 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/1/0 | 6/54/0 | 31/0/0 | - | 1,3 | 60.0 | 33/42 | 171.3 |
| seed-50-rep-2 | 10 / 12 / 11,12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 151.0 |
| seed-51-rep-2 | 10,11 / 12 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 151.5 |
| seed-52-rep-2 | 11 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.6 |
| seed-53-rep-2 | 11 / 10,12 / 11 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.8 |
| seed-55-rep-2 | 10 / 10,12 / 11 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 153.7 |
| seed-54-rep-2 | 10,11 / 10 / 11,12 | 12 | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 171.5 |
| seed-56-rep-2 | 10,11 / 12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.5 |
| seed-57-rep-2 | 10 / 10 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-58-rep-2 | 10 / 12 / 11,12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-59-rep-2 | 10 / 10,12 / 11,12 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 31/42 | 170.5 |
| seed-60-rep-2 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-61-rep-2 | 10 / 10,12 / 11,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 153.0 |
| seed-62-rep-2 | 10,11 / 10,12 / 11 | 10,11,12 | spread | pass | 8/1/0 | 3/57/0 | 31/0/0 | 3-3 | 1,3 | 60.0 | 30/42 | 171.2 |
| seed-63-rep-2 | 10,11 / 10,12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 153.7 |
| seed-64-rep-2 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-65-rep-2 | 11 / 10 / 11 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-66-rep-2 | 10,11 / 12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 152.5 |
| seed-67-rep-2 | 11 / 12 / 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-68-rep-2 | 10 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-69-rep-2 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.2 |
| seed-71-rep-2 | 10,11 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/0/0 | 51/9/0 | 32/0/0 | 2-2 | 1,3 | 60.0 | 32/42 | 171.7 |
| seed-70-rep-2 | 10 / 10,12 / 11,12 | 12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 27/42 | 281.5 |
| seed-72-rep-2 | 10,11 / 10 / 11,12 | 11 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 33/42 | 170.2 |
| seed-73-rep-2 | 10 / 10 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 153.0 |
| seed-74-rep-2 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-75-rep-2 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.7 |
| seed-76-rep-2 | 10 / 12 / 11,12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.4 |
| seed-77-rep-2 | 10,11 / 10,12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 151.5 |
| seed-78-rep-2 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.3 |
| seed-79-rep-2 | 10 / 12 / 12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 151.5 |
| seed-80-rep-2 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.1 |
| seed-81-rep-2 | 10 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 153.5 |
| seed-82-rep-2 | 11 / 10,12 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.5 |
| seed-83-rep-2 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 156.4 |
| seed-85-rep-2 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 150.6 |
| seed-84-rep-2 | 10 / 10,12 / 12 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 280.7 |
| seed-86-rep-2 | 10,11 / 10,12 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.3 |
| seed-87-rep-2 | 11 / 10 / 11 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.8 |
| seed-88-rep-2 | 11 / 10 / 12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 156.6 |
| seed-89-rep-2 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.7 |
| seed-91-rep-2 | 10 / 10 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 154.3 |
| seed-90-rep-2 | 10 / 10 / 11 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 278.5 |
| seed-92-rep-2 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 157.0 |
| seed-93-rep-2 | 11 / 12 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.3 |
| seed-95-rep-2 | 11 / 12 / 11 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.1 |
| seed-94-rep-2 | 10,11 / 10 / 12 | 11,12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 26/42 | 279.5 |
| seed-96-rep-2 | 11 / 10 / 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.7 |
| seed-97-rep-2 | 11 / 10 / 11 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.6 |
| seed-98-rep-2 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.7 |
| seed-99-rep-2 | 11 / 10,12 / 11,12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 154.0 |
| seed-100-rep-2 | 11 / 10,12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.4 |
| seed-101-rep-2 | 11 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.3 |
| seed-102-rep-2 | 10 / 10,12 / 12 | 10 | spread | pass | 8/0/0 | 57/3/0 | 32/0/0 | 2-2 | 1 | 60.0 | 33/42 | 201.1 |
| seed-103-rep-2 | 11 / 10,12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 154.5 |
| seed-105-rep-2 | 10,11 / 10 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 151.3 |
| seed-104-rep-2 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 156.1 |
| seed-106-rep-2 | 10 / 10,12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 154.5 |
| seed-107-rep-2 | 10,11 / 10,12 / 12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 171.7 |
| seed-108-rep-2 | 11 / 10,12 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 154.2 |
| seed-109-rep-2 | 11 / 12 / 11,12 | none | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 2-2 | 1 | 60.0 | 35/42 | 202.3 |
| seed-110-rep-2 | 10,11 / 10,12 / 11,12 | none | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 171.2 |
| seed-111-rep-2 | 11 / 10 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 158.4 |
| seed-112-rep-2 | 10 / 10,12 / 11 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 150.8 |
| seed-113-rep-2 | 11 / 10 / 11,12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.5 |
| seed-114-rep-2 | 10,11 / 12 / 12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.2 |
| seed-116-rep-2 | 10 / 10,12 / 12 | 10,11 | concentrated | pass | 8/1/0 | 3/57/0 | 31/0/0 | 1-1 | 1 | 60.0 | 33/42 | 169.1 |
| seed-115-rep-2 | 10 / 10 / 11 | none | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 25/42 | 281.4 |
| seed-117-rep-2 | 10,11 / 10 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.9 |
| seed-118-rep-2 | 11 / 10 / 11 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.6 |
| seed-120-rep-2 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 158.4 |
| seed-119-rep-2 | 11 / 10,12 / 11,12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 2-2 | 2 | 60.0 | 31/42 | 203.8 |
| seed-42-rep-3 | 11 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 151.6 |
| seed-41-rep-3 | 10 / 10 / 12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 29/42 | 280.0 |
| seed-43-rep-3 | 11 / 12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 153.6 |
| seed-44-rep-3 | 10 / 10,12 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.9 |
| seed-45-rep-3 | 10 / 10,12 / 11,12 | 12 | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 2-2 | 1 | 60.0 | 35/42 | 201.9 |
| seed-46-rep-3 | 10 / 10,12 / 12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.0 |
| seed-47-rep-3 | 10 / 10 / 11 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 279.9 |
| seed-48-rep-3 | 10 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/0/0 | 3/57/0 | 32/0/0 | - | 1,3 | 60.0 | 20/42 | 279.8 |
| seed-49-rep-3 | 10 / 12 / 11,12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.2 |
| seed-50-rep-3 | 10 / 12 / 11,12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 151.2 |
| seed-51-rep-3 | 10,11 / 12 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 153.1 |
| seed-52-rep-3 | 11 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.2 |
| seed-53-rep-3 | 11 / 10,12 / 11 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.1 |
| seed-54-rep-3 | 10,11 / 10 / 11,12 | 12 | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 169.0 |
| seed-55-rep-3 | 10 / 10,12 / 11 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 153.4 |
| seed-56-rep-3 | 10,11 / 12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 153.2 |
| seed-57-rep-3 | 10 / 10 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 151.4 |
| seed-58-rep-3 | 10 / 12 / 11,12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 152.2 |
| seed-60-rep-3 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.2 |
| seed-59-rep-3 | 10 / 10,12 / 11,12 | 11,12 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 28/42 | 280.2 |
| seed-61-rep-3 | 10 / 10,12 / 11,12 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 154.2 |
| seed-62-rep-3 | 10,11 / 10,12 / 11 | 10,11,12 | spread | pass | 8/0/0 | 1/59/0 | 32/0/0 | 3-3 | 1,3 | 60.0 | 30/42 | 170.1 |
| seed-63-rep-3 | 10,11 / 10,12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 153.4 |
| seed-64-rep-3 | 10,11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.7 |
| seed-65-rep-3 | 11 / 10 / 11 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.9 |
| seed-66-rep-3 | 10,11 / 12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 152.5 |
| seed-67-rep-3 | 11 / 12 / 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.7 |
| seed-68-rep-3 | 10 / 12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.2 |
| seed-69-rep-3 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 150.7 |
| seed-71-rep-3 | 10,11 / 10,12 / 11,12 | 10,12 | concentrated | pass | 8/0/0 | 50/10/0 | 32/0/0 | 2-2 | 1,3 | 60.0 | 30/42 | 169.8 |
| seed-70-rep-3 | 10 / 10,12 / 11,12 | 12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 280.4 |
| seed-72-rep-3 | 10,11 / 10 / 11,12 | 11 | concentrated | pass | 8/0/0 | 60/0/0 | 32/0/0 | 3-3 | 1 | 60.0 | 35/42 | 170.1 |
| seed-73-rep-3 | 10 / 10 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.1 |
| seed-74-rep-3 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.1 |
| seed-75-rep-3 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.1 |
| seed-76-rep-3 | 10 / 12 / 11,12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.6 |
| seed-78-rep-3 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.6 |
| seed-77-rep-3 | 10,11 / 10,12 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 153.4 |
| seed-79-rep-3 | 10 / 12 / 12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 151.4 |
| seed-80-rep-3 | 11 / 12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 151.7 |
| seed-81-rep-3 | 10 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 151.8 |
| seed-82-rep-3 | 11 / 10,12 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.3 |
| seed-83-rep-3 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 157.1 |
| seed-84-rep-3 | 10 / 10,12 / 12 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 281.2 |
| seed-85-rep-3 | 10,11 / 12 / 11 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-86-rep-3 | 10,11 / 10,12 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 154.6 |
| seed-87-rep-3 | 11 / 10 / 11 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 154.3 |
| seed-88-rep-3 | 11 / 10 / 12 | 11,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 158.9 |
| seed-89-rep-3 | 11 / 12 / 12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.2 |
| seed-90-rep-3 | 10 / 10 / 11 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 281.0 |
| seed-91-rep-3 | 10 / 10 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-92-rep-3 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 158.9 |
| seed-93-rep-3 | 11 / 12 / 11,12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 152.9 |
| seed-94-rep-3 | 10,11 / 10 / 12 | 11,12 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 280.4 |
| seed-95-rep-3 | 11 / 12 / 11 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 149.1 |
| seed-96-rep-3 | 11 / 10 / 11,12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 150.6 |
| seed-97-rep-3 | 11 / 10 / 11 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 150.3 |
| seed-98-rep-3 | 10,11 / 12 / 11 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 154.2 |
| seed-99-rep-3 | 11 / 10,12 / 11,12 | 11,12 | spread | precondition_failure | - | - | - | - | - | - | - | 154.8 |
| seed-100-rep-3 | 11 / 10,12 / 12 | 10,11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-101-rep-3 | 11 / 10,12 / 12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 152.0 |
| seed-102-rep-3 | 10 / 10,12 / 12 | 10 | spread | pass | 8/1/0 | 57/3/0 | 31/0/0 | 2-2 | 1 | 60.0 | 33/42 | 199.2 |
| seed-103-rep-3 | 11 / 10,12 / 11,12 | 10 | concentrated | precondition_failure | - | - | - | - | - | - | - | 154.0 |
| seed-104-rep-3 | 11 / 10 / 12 | 11 | spread | precondition_failure | - | - | - | - | - | - | - | 158.7 |
| seed-105-rep-3 | 10,11 / 10 / 12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-106-rep-3 | 10 / 10,12 / 12 | 10,12 | spread | precondition_failure | - | - | - | - | - | - | - | 153.5 |
| seed-107-rep-3 | 10,11 / 10,12 / 12 | 11 | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 281.5 |
| seed-108-rep-3 | 11 / 10,12 / 11,12 | 10,11 | spread | precondition_failure | - | - | - | - | - | - | - | 153.1 |
| seed-109-rep-3 | 11 / 12 / 11,12 | none | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 2-2 | 1 | 60.0 | 39/42 | 199.7 |
| seed-110-rep-3 | 10,11 / 10,12 / 11,12 | none | spread | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 35/42 | 168.1 |
| seed-111-rep-3 | 11 / 10 / 12 | none | spread | precondition_failure | - | - | - | - | - | - | - | 157.1 |
| seed-112-rep-3 | 10 / 10,12 / 11 | 12 | spread | precondition_failure | - | - | - | - | - | - | - | 151.8 |
| seed-113-rep-3 | 11 / 10 / 11,12 | 12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.4 |
| seed-114-rep-3 | 10,11 / 12 / 12 | 10,12 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.9 |
| seed-115-rep-3 | 10 / 10 / 11 | none | concentrated | pass | 9/0/0 | 60/0/0 | 31/0/0 | 3-3 | 1 | 60.0 | 25/42 | 279.5 |
| seed-116-rep-3 | 10 / 10,12 / 12 | 10,11 | concentrated | pass | 8/1/0 | 0/60/0 | 31/0/0 | 1-1 | 1 | 60.0 | 33/42 | 167.8 |
| seed-117-rep-3 | 10,11 / 10 / 11,12 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 152.6 |
| seed-118-rep-3 | 11 / 10 / 11 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 152.5 |
| seed-119-rep-3 | 11 / 10,12 / 11,12 | 11 | concentrated | precondition_failure | - | - | - | - | - | - | - | 153.6 |
| seed-120-rep-3 | 10 / 12 / 11 | 10 | spread | precondition_failure | - | - | - | - | - | - | - | 157.3 |

## Seeds

| Seed | Formation predicted | Formed | Outcomes | Graph during cut | Cut removes a link | Prediction holds | Resolution matches plan |
|---:|---|---|---|---|---|---|---|
| 41 | certain | 3/3 | pass 3 | one link | no | yes | yes |
| 42 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 43 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 44 | election | 2/3 | pass 2, precondition_failure 1 | one link | yes | yes | yes |
| 45 | election | 1/3 | pass 1, precondition_failure 2 | one link | yes | yes | yes |
| 46 | election | 2/3 | pass 2, precondition_failure 1 | one link | yes | yes | yes |
| 47 | certain | 3/3 | pass 3 | one link | no | yes | yes |
| 48 | election | 3/3 | pass 3 | all isolated | yes | yes | yes |
| 49 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 50 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 51 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 52 | election | 0/3 | precondition_failure 3 | path | no | yes | yes |
| 53 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 54 | election | 3/3 | pass 3 | path | no | yes | yes |
| 55 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 56 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 57 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 58 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 59 | election | 3/3 | pass 3 | one link | yes | yes | yes |
| 60 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 61 | election | 0/3 | precondition_failure 3 | one link | yes | yes | yes |
| 62 | election | 3/3 | pass 3 | all isolated | yes | yes | yes |
| 63 | election | 1/3 | pass 1, precondition_failure 2 | path | no | yes | yes |
| 64 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 65 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 66 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 67 | election | 1/3 | pass 1, precondition_failure 2 | one link | yes | yes | yes |
| 68 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 69 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 70 | election | 3/3 | pass 3 | one link | yes | yes | yes |
| 71 | certain | 3/3 | pass 3 | one link | yes | yes | yes |
| 72 | election | 2/3 | pass 2, precondition_failure 1 | one link | yes | yes | yes |
| 73 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 74 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 75 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 76 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 77 | election | 0/3 | precondition_failure 3 | path | no | yes | yes |
| 78 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 79 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 80 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 81 | election | 0/3 | precondition_failure 3 | one link | yes | yes | yes |
| 82 | election | 0/3 | precondition_failure 3 | path | no | yes | yes |
| 83 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |
| 84 | election | 3/3 | pass 3 | one link | yes | yes | yes |
| 85 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 86 | election | 0/3 | precondition_failure 3 | path | no | yes | yes |
| 87 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 88 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |
| 89 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 90 | certain | 3/3 | pass 3 | one link | no | yes | yes |
| 91 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 92 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |
| 93 | election | 0/3 | precondition_failure 3 | one link | yes | yes | yes |
| 94 | certain | 3/3 | pass 3 | one link | no | yes | yes |
| 95 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 96 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 97 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 98 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 99 | election | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 100 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 101 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 102 | election | 2/3 | pass 2, precondition_failure 1 | one link | yes | yes | yes |
| 103 | election | 1/3 | pass 1, precondition_failure 2 | path | no | yes | yes |
| 104 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |
| 105 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 106 | election | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 107 | election | 3/3 | pass 3 | path | no | yes | yes |
| 108 | election | 0/3 | precondition_failure 3 | one link | yes | yes | yes |
| 109 | election | 2/3 | pass 2, precondition_failure 1 | path | no | yes | yes |
| 110 | certain | 3/3 | pass 3 | triangle | no | yes | yes |
| 111 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |
| 112 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 113 | impossible | 0/3 | precondition_failure 3 | one link | no | yes | yes |
| 114 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 115 | certain | 3/3 | pass 3 | one link | no | yes | yes |
| 116 | election | 3/3 | pass 3 | one link | yes | yes | yes |
| 117 | election | 1/3 | pass 1, precondition_failure 2 | one link | yes | yes | yes |
| 118 | impossible | 0/3 | precondition_failure 3 | all isolated | yes | yes | yes |
| 119 | election | 1/3 | pass 1, precondition_failure 2 | one link | yes | yes | yes |
| 120 | impossible | 0/3 | precondition_failure 3 | all isolated | no | yes | yes |

## Decision checks

- D2 verdict seeds: 26 (minimum 15)
- D2 graph classes with a verdict: all isolated, one link, path, triangle (minimum 3 of 4)
- D2 verdict seeds whose cut removes a link: 15 (minimum 5; null conclusion needs 10)
- D2 verdict seeds whose cut changes nothing: 11 (minimum 3)
- D6 predictions hold for every certain and impossible seed: yes
- Gate 'materialized' passes in every run past formation: yes
- Demonstration minimum met: yes; null minimum met: yes
- Contract violations (D3): none
- Source revisions: 634f463a37ae6c1c0c5c115c79bc84ad53d5a7a5; units on uncommitted code: 0; units without a recorded revision: 0; single clean revision: yes
- Lowest host MemAvailable during the campaign: 5048 MiB

Outcomes: pass 61, precondition_failure 179
