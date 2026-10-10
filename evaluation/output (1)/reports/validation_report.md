# Data generation report

This report distinguishes generated records from automatically validated and human-approved records.

| M2 metric | Required | Current | Status |
|---|---:|---:|---|
| Transcript conversations | 250 | 5 | PENDING |
| Audio conversations | 100 | 0 | PENDING |
| Audio duration (hours) | 3 | 0.00 | PENDING |
| Customers with multiple sessions | 60 | 0 | PENDING |
| Customers with multiple channels | 30 | 0 | PENDING |
| Categories | 3 | 3 (gia-dung, me-be, thoi-trang) | PASS |
| Category-region pairs | 9 | 1 | PENDING |
| SKUs incl. variants | 100 | 136 | PASS |
| Noisy audio ratio | 20% | 0% | PENDING |
| Scenarios | 40 | 5 | PENDING |

| Simulator replays | 3 per scenario | 15 total (3.0/scenario) | PASS |
Category-region pairs represented: 1/9.
CRM profiles loaded: 50 including synthetic profiles when generated; seed CRM multi-session: 0; multi-channel in generated conversations: 0.
Generated scenarios: 5; conversations: 5; automatic validator+judge passes: 3; judge results: 5; human approvals: 0; golden manifest records: 0.
Model API requests: 75; cache hits: 53; prompt tokens: 474493; output tokens: 28191; ElevenLabs characters: 1454.

Audio hours and noisy ratio are based only on files with metadata. Generated is not equivalent to golden: the golden set requires validator pass and judge pass or explicit human approval.
