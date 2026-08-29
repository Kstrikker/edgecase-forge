from benchmarks.flashcart.build_variants import build_all


def pytest_sessionstart(session) -> None:
    build_all()

