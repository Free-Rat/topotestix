| Unit | Seed | Outcome | Probe | Probe = oracle | ISR during | Duration (s) |
|---|---:|---|---|---|---|---:|
| T1-no-fault-rep-1 | 9 | pass | confirmed | yes | [1, 3, 5] | 120.2 |
| T1-leader-kill-rep-1 | 9 | pass | confirmed | yes | [3, 5] | 130.8 |
| T1-rack-kill-rep-1 | 9 | pass | confirmed | yes | [3, 5] | 133.4 |
| T2-no-fault-rep-1 | 3 | pass | confirmed | yes | [1, 3, 5] | 123.9 |
| T2-leader-kill-rep-1 | 3 | pass | confirmed | yes | [3, 5] | 133.2 |
| T2-rack-kill-rep-1 | 3 | pass | confirmed | yes | [3, 5] | 137.3 |
| T3-no-fault-rep-1 | 1 | pass | confirmed | yes | [1, 2, 3] | 122.9 |
| T3-leader-kill-rep-1 | 1 | pass | confirmed | yes | [2, 3] | 134.0 |
| T3-rack-kill-rep-1 | 1 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 137.8 |
| T4-no-fault-rep-1 | 2 | pass | confirmed | yes | [1, 2, 3] | 122.8 |
| T4-leader-kill-rep-1 | 2 | pass | confirmed | yes | [2, 3] | 132.8 |
| T4-rack-kill-rep-1 | 2 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 134.5 |
| T1-no-fault-rep-2 | 9 | pass | confirmed | yes | [1, 3, 5] | 119.6 |
| T1-leader-kill-rep-2 | 9 | pass | confirmed | yes | [3, 5] | 130.5 |
| T1-rack-kill-rep-2 | 9 | pass | confirmed | yes | [3, 5] | 132.6 |
| T2-no-fault-rep-2 | 3 | pass | confirmed | yes | [1, 3, 5] | 119.6 |
| T2-leader-kill-rep-2 | 3 | pass | confirmed | yes | [3, 5] | 130.5 |
| T2-rack-kill-rep-2 | 3 | pass | confirmed | yes | [3, 5] | 133.4 |
| T3-no-fault-rep-2 | 1 | pass | confirmed | yes | [1, 2, 3] | 118.9 |
| T3-leader-kill-rep-2 | 1 | pass | confirmed | yes | [2, 3] | 130.6 |
| T3-rack-kill-rep-2 | 1 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 134.7 |
| T4-no-fault-rep-2 | 2 | pass | confirmed | yes | [1, 2, 3] | 119.9 |
| T4-leader-kill-rep-2 | 2 | pass | confirmed | yes | [2, 3] | 130.3 |
| T4-rack-kill-rep-2 | 2 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 133.8 |
| T1-no-fault-rep-3 | 9 | pass | confirmed | yes | [1, 3, 5] | 119.9 |
| T1-leader-kill-rep-3 | 9 | pass | confirmed | yes | [3, 5] | 129.9 |
| T1-rack-kill-rep-3 | 9 | pass | confirmed | yes | [3, 5] | 132.4 |
| T2-no-fault-rep-3 | 3 | pass | confirmed | yes | [1, 3, 5] | 119.7 |
| T2-leader-kill-rep-3 | 3 | pass | confirmed | yes | [3, 5] | 130.0 |
| T2-rack-kill-rep-3 | 3 | pass | confirmed | yes | [3, 5] | 132.7 |
| T3-no-fault-rep-3 | 1 | pass | confirmed | yes | [1, 2, 3] | 119.4 |
| T3-leader-kill-rep-3 | 1 | pass | confirmed | yes | [2, 3] | 130.7 |
| T3-rack-kill-rep-3 | 1 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 134.2 |
| T4-no-fault-rep-3 | 2 | pass | confirmed | yes | [1, 2, 3] | 121.0 |
| T4-leader-kill-rep-3 | 2 | pass | confirmed | yes | [2, 3] | 130.9 |
| T4-rack-kill-rep-3 | 2 | pass | ambiguous (NotEnoughReplicasException) | yes | [3] | 134.4 |
