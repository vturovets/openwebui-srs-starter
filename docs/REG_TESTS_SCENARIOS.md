Regression Test Scenarios

1) Method: gemini-2.5-flash, user input “Find me a trip in
   the southern hemisphere next June”, POPULARITY_IMPUTER_ENABLED=true. The expected
   result: Language: en | From: Charleroi | To: Australia, New Zealand, Chile |
   Departure date range: 2026-05-29, 2026-06-04 | Duration: 7 nights |
   Participants: Adults: 2 | Rooms: 1.
   
   

2) Method: rules-basic, user input “Find me a trip in the
   southern hemisphere next June”, POPULARITY_IMPUTER_ENABLED=true. The expected
   result: Language: en | From: Charleroi | To: Costa Rica | Departure date range:
   2026-02-11, 2026-02-17 | Duration: 7 nights | Participants: Adults: 2 | Rooms:



3) Method: hybrid-v1, user input “Find me a trip in the
   southern hemisphere next June”, POPULARITY_IMPUTER_ENABLED=true. The expected
   result: Language: en | From: Charleroi | To: Australia, New Zealand, Chile |
   Departure date range: 2026-05-29, 2026-06-04 | Duration: 7 nights |
   Participants: Adults: 2 | Rooms: 1.
   
   

4) Method: gemini-2.5-flash, “Find me a trip in the southern
   hemisphere next June from Ostend”, POPULARITY_IMPUTER_ENABLED=true.  The expected result: Language: en | From:
   Ostend | To: Australia, New Zealand, Chile | Departure date range: 2026-05-29,
   2026-06-04 | Duration: 7 nights | Participants: Adults: 2 | Rooms: 1.
   
   

5)  Method: rules-basic,
   user input “Find me a trip in the southern hemisphere next June from Ostend”, POPULARITY_IMPUTER_ENABLED=true.
   The expected result: Language: en | From: Ostend | To: Costa Rica | Departure
   date range: 2026-02-11, 2026-02-17 | Duration: 7 nights | Participants: Adults:
   2 | Rooms: 1.
