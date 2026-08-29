# Smoke fixtures

These two tiny repositories verify the benchmark pipeline before the private FlashCart suite is complete.

- `stock_race_clean` performs the stock check and decrement under one lock.
- `stock_race_mutant` separates the read and write, allowing more than one concurrent request to succeed when stock starts at one.

They expose the same FastAPI contract. The evaluated agent receives only one opaque copy and is not shown this parent README or the sibling implementation.

These smoke fixtures do not count toward the final ten-mutant score.

