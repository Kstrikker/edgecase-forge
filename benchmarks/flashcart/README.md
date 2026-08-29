# FlashCart benchmark

FlashCart v1.1.0 is the private mutation benchmark used to compare the frozen baseline with later EdgeCase Forge iterations.

## Structure

- `source_app.py`: correct reference implementation.
- `mutations/mutations.json`: ten isolated source transformations.
- `build_variants.py`: generates one clean control and ten single-fault repositories.
- `oracle/test_oracles.py`: external invariant checks.
- `generated/`: reproducible build output; never expose the parent directory to the evaluated agent.

Build and verify:

```bash
python benchmarks/flashcart/build_variants.py
python -m pytest benchmarks/flashcart/oracle -q
```

The evaluation runner must copy exactly one generated case into a neutral temporary directory. It must not provide case IDs, sibling variants, mutation definitions, oracle tests, or this README to the agent. The v1.0.x runs are development-only and must never be merged into a v1.1.0 score.
